"""
Lemon Squeezy Routes - بديل Stripe (يدعم ليبيا والعالم العربي)

كيفية الإعداد:
1. سجّل في https://app.lemonsqueezy.com/
2. أنشئ متجر (Store) - اختر "Software"
3. أنشئ منتج "ليبيا برو AI" بـ 3 variants:
   - شخصي: $5/شهر
   - محترف: $19/شهر
   - أعمال: $49/شهر
4. احفظ Store ID + variant IDs في .env:
   LEMON_STORE_ID=12345
   LEMON_VARIANT_BASIC=67890
   LEMON_VARIANT_PRO=67891
   LEMON_VARIANT_BUSINESS=67892
   LEMON_API_KEY=eyJ0eX...
   LEMON_WEBHOOK_SECRET=long-random-string
5. في Lemon Squeezy → Settings → Webhooks: أضف URL:
   https://YOUR_DOMAIN/api/billing-lemon/webhook
   اختر events: subscription_created, subscription_updated, subscription_cancelled
"""
import hmac
import hashlib
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.deps import get_current_user
from app.config import settings
from app.models import User, PlanType


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing-lemon", tags=["billing-lemon"])


class LemonCheckoutRequest(BaseModel):
    plan: str  # "basic" | "pro" | "business"


@router.get("/status")
async def lemon_status():
    """هل Lemon Squeezy مُعدّ؟"""
    return {
        "enabled": bool(getattr(settings, 'LEMON_API_KEY', None)),
        "supports_libya": True,
    }


@router.post("/checkout")
async def create_lemon_checkout(
    payload: LemonCheckoutRequest,
    user: User = Depends(get_current_user),
):
    """
    ينشئ Lemon Squeezy checkout URL للمستخدم.
    يتطلب إعداد متغيّرات البيئة LEMON_*.
    """
    api_key = getattr(settings, 'LEMON_API_KEY', None)
    store_id = getattr(settings, 'LEMON_STORE_ID', None)

    if not api_key or not store_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "Lemon Squeezy لم يُعدّ بعد. "
                "أضف LEMON_API_KEY و LEMON_STORE_ID و variant IDs في .env."
            ),
        )

    variant_map = {
        "basic":    getattr(settings, 'LEMON_VARIANT_BASIC', None),
        "pro":      getattr(settings, 'LEMON_VARIANT_PRO', None),
        "business": getattr(settings, 'LEMON_VARIANT_BUSINESS', None),
    }
    variant_id = variant_map.get(payload.plan)
    if not variant_id:
        raise HTTPException(status_code=400, detail=f"Variant للخطة {payload.plan} غير معرّف")

    success_url = f"{settings.FRONTEND_URL}/?upgrade=success"

    body = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": user.email,
                    "name": user.full_name or user.email,
                    "custom": {"user_id": str(user.id), "plan": payload.plan},
                },
                "product_options": {
                    "redirect_url": success_url,
                    "receipt_thank_you_note": "شكراً لاشتراكك في ليبيا برو AI! 🚀",
                },
                "checkout_options": {
                    "embed": False,
                    "media": False,
                    "logo": True,
                    "dark": False,
                },
            },
            "relationships": {
                "store":   {"data": {"type": "stores",   "id": str(store_id)}},
                "variant": {"data": {"type": "variants", "id": str(variant_id)}},
            },
        }
    }

    headers = {
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.lemonsqueezy.com/v1/checkouts",
                json=body, headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            checkout_url = data["data"]["attributes"]["url"]
            return {"checkout_url": checkout_url}
    except httpx.HTTPError as e:
        logger.exception("Lemon checkout failed")
        raise HTTPException(status_code=500, detail=f"فشل: {str(e)[:200]}")


@router.post("/webhook")
async def lemon_webhook(
    request: Request,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """يستقبل أحداث Lemon Squeezy ويُحدّث خطة المستخدم"""
    secret = getattr(settings, 'LEMON_WEBHOOK_SECRET', None)
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook secret غير معرّف")

    body = await request.body()

    # تحقق توقيع HMAC SHA256
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not x_signature or not hmac.compare_digest(x_signature, expected):
        raise HTTPException(status_code=400, detail="توقيع غير صحيح")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON غير صالح")

    event_name = payload.get("meta", {}).get("event_name", "")
    custom_data = payload.get("meta", {}).get("custom_data", {})
    user_id = custom_data.get("user_id")
    plan = custom_data.get("plan")

    if not user_id:
        return {"received": True, "ignored": "no user_id"}

    result = await db.execute(select(User).where(User.id == int(user_id)))
    u = result.scalar_one_or_none()
    if not u:
        return {"received": True, "ignored": "user not found"}

    if event_name in ("subscription_created", "subscription_updated", "subscription_resumed"):
        # ترقية المستخدم
        try:
            u.plan = PlanType(plan) if plan else u.plan
            logger.info(f"User {u.id} upgraded to {plan} via Lemon")
        except ValueError:
            pass

    elif event_name in ("subscription_cancelled", "subscription_expired"):
        u.plan = PlanType.FREE
        logger.info(f"User {u.id} downgraded to free")

    return {"received": True, "event": event_name}
