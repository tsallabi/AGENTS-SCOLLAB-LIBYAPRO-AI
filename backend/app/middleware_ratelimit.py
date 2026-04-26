"""
Rate Limiting Middleware - حماية من الإفراط في الاستخدام
يحدّ سرعة الطلبات لكل IP لحماية الـ APIs والسيرفر.
"""
import time
from collections import defaultdict, deque
from typing import Dict, Deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# In-memory rate limit storage. للنشر متعدد الـ workers يُفضّل Redis.
_buckets: Dict[str, Deque[float]] = defaultdict(deque)


# قواعد الحدود لكل path-prefix
# (path_prefix, max_requests, window_seconds)
RATE_LIMITS = [
    ("/api/auth/login",       10,  60),    # 10 محاولات/دقيقة
    ("/api/auth/signup",      5,   300),   # 5 تسجيلات/5 دقائق
    ("/api/auth/google",      30,  60),    # 30 طلب OAuth/دقيقة
    ("/api/support/threads",  20,  60),    # 20 رسالة تواصل/دقيقة
    ("/api/support/chat",     30,  60),    # 30 رسالة دردشة/دقيقة
    ("/api/contact",          5,   60),    # 5 رسائل/دقيقة (legacy)
    ("/api/code/execute",     20,  60),    # 20 تنفيذ كود/دقيقة
    ("/api/files",            30,  60),    # 30 رفع/تنزيل/دقيقة
    ("/api/",                 200, 60),    # عام: 200 طلب/دقيقة لكل IP
]


def _client_ip(request: Request) -> str:
    # احترم Cloudflare/proxy
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_limit(key: str, max_req: int, window: int) -> tuple[bool, int]:
    """يرجع (allowed, retry_after_seconds)"""
    now = time.time()
    bucket = _buckets[key]
    # إزالة الطلبات القديمة خارج النافذة
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    if len(bucket) >= max_req:
        # احسب متى ينتهي أقدم طلب
        retry_after = int(bucket[0] + window - now) + 1
        return False, retry_after
    bucket.append(now)
    return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """يطبّق حدود بسيطة في الذاكرة بناءً على IP + المسار"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # WebSocket connections لا تمر بهذا الـ middleware
        if request.scope.get("type") == "websocket":
            return await call_next(request)

        ip = _client_ip(request)
        # ابحث عن أول قاعدة تنطبق
        for prefix, max_req, window in RATE_LIMITS:
            if path.startswith(prefix):
                key = f"{ip}:{prefix}"
                ok, retry_after = _check_limit(key, max_req, window)
                if not ok:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": f"عدد الطلبات تجاوز الحد - أعد المحاولة بعد {retry_after} ثانية",
                            "retry_after": retry_after,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )
                break  # طبّق أول match فقط

        return await call_next(request)
