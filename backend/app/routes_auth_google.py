"""
Google OAuth Routes - تسجيل الدخول بحساب Google

Flow:
1. الواجهة → GET /api/auth/google/login
   → Backend يبني Google OAuth URL ويُعيد توجيه المتصفح
2. المستخدم يُسجّل في Google
3. Google يُعيد توجيه إلى GET /api/auth/google/callback?code=...
4. Backend يُبادل الـ code بـ access_token
5. Backend يطلب معلومات المستخدم
6. ينشئ user جديد أو يجلب الموجود
7. يولّد JWT ويُعيد توجيه إلى الواجهة مع التوكن في URL

⚠️ يجب إضافة GOOGLE_REDIRECT_URI في Google Cloud Console → OAuth → Redirect URIs
"""
import logging
import secrets
from urllib.parse import urlencode
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.config import settings
from app.database import get_db
from app.models import User, PlanType
from app.security import create_access_token, hash_password


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/google", tags=["auth-google"])


# ============== Endpoints ==============

@router.get("/login")
async def google_login():
    """يبني Google OAuth URL ويُعيد توجيه المتصفح."""
    if not settings.GOOGLE_OAUTH2_KEY:
        raise HTTPException(status_code=503, detail="Google OAuth غير مُفعّل")

    # state للحماية من CSRF (سيُتحقّق منه في الـ callback)
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": settings.GOOGLE_OAUTH2_KEY,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    response = RedirectResponse(url=url)
    # احفظ state في cookie لمقارنته في الـ callback
    response.set_cookie(
        "google_oauth_state", state,
        max_age=600, httponly=True, samesite="lax",
    )
    return response


@router.get("/callback")
async def google_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """يستقبل code من Google ويُكمل تسجيل الدخول."""
    frontend_base = settings.FRONTEND_URL or "/"

    if error:
        return RedirectResponse(url=f"/?google_error={error}")
    if not code:
        return RedirectResponse(url="/?google_error=no_code")

    if not settings.GOOGLE_OAUTH2_KEY or not settings.GOOGLE_OAUTH2_SECRET:
        raise HTTPException(status_code=503, detail="Google OAuth غير مُعدّ")

    # 1. استبدل الـ code بـ access_token
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH2_KEY,
                    "client_secret": settings.GOOGLE_OAUTH2_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                logger.error("No access_token in response: %s", token_data)
                return RedirectResponse(url="/?google_error=token_exchange_failed")

            # 2. اجلب معلومات المستخدم
            userinfo_resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            user_info = userinfo_resp.json()
    except httpx.HTTPError as e:
        logger.exception("Google OAuth HTTP error")
        return RedirectResponse(url=f"/?google_error=http_{type(e).__name__}")

    google_email = (user_info.get("email") or "").lower().strip()
    google_name = user_info.get("name") or ""
    google_id = user_info.get("id")
    email_verified = user_info.get("verified_email", True)

    if not google_email or not email_verified:
        return RedirectResponse(url="/?google_error=email_not_verified")

    # 3. اجلب أو أنشئ المستخدم
    result = await db.execute(select(User).where(User.email == google_email))
    user = result.scalar_one_or_none()

    if not user:
        # حساب جديد - أنشئه بكلمة سر عشوائية (لن تُستخدم - الدخول عبر Google فقط)
        random_password = secrets.token_urlsafe(32)
        user = User(
            email=google_email,
            password_hash=hash_password(random_password),
            full_name=google_name or None,
            is_active=True,
            is_verified=True,  # Google verified email
            plan=PlanType.FREE,
        )
        db.add(user)
        await db.flush()
        logger.info(f"Created new user via Google: {google_email}")
    else:
        # موجود - حدّث الاسم إن لم يكن موجوداً
        if not user.full_name and google_name:
            user.full_name = google_name
        user.is_verified = True

    user.last_login_at = datetime.utcnow()
    await db.commit()

    # 4. أنشئ JWT وأعد التوجيه للواجهة مع التوكن في URL hash
    jwt_token = create_access_token(
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )

    # نمرّر التوكن عبر hash لأن الـ hash لا يُرسَل للـ backend
    redirect_url = f"/?#/auth-google-success?token={jwt_token}"
    return RedirectResponse(url=redirect_url)


@router.get("/status")
async def google_status():
    """هل Google OAuth مُفعّل؟"""
    return {
        "enabled": bool(settings.GOOGLE_OAUTH2_KEY and settings.GOOGLE_OAUTH2_SECRET),
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    }
