"""
Billing Routes - Stripe checkout (هيكلي - يحتاج إعداد Stripe لاحقاً)

عند نشر التطبيق:
1. أنشئ products في Stripe Dashboard:
   - Basic ($9/شهر) → احفظ price_id في .env STRIPE_PRICE_ID_BASIC
   - Pro ($49/شهر)  → STRIPE_PRICE_ID_PRO
2. أضف STRIPE_SECRET_KEY و STRIPE_WEBHOOK_SECRET
3. أنشئ webhook endpoint عبر Stripe Dashboard يشير إلى /api/billing/webhook
4. أحداث webhook المطلوبة: checkout.session.completed, customer.subscription.updated, customer.subscription.deleted
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.deps import get_current_user
from app.config import settings
from app.models import User, Subscription, PlanType, SubscriptionStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str  # "basic" or "pro"


@router.get("/plans")
async def list_plans():
    """
    خطط الاشتراك - مُسعّرة للسوق الليبي + USD للدفع الدولي.
    سعر الصرف يُحدَّث من config (مصدره: المصرف المركزي الليبي).
    """
    rate = settings.LYD_PER_USD

    def lyd(usd: int) -> float:
        return round(usd * rate, 2)

    return {
        "_meta": {
            "lyd_per_usd": rate,
            "source": settings.EXCHANGE_RATE_SOURCE,
            "source_url": "https://cbl.gov.ly",
        },
        "free": {
            "name": "مجاني",
            "price_usd": 0, "price_lyd": 0,
            "period": "شهري",
            "messages_per_month": 50,
            "features": [
                "50 رسالة جماعية/شهر",
                "كل النماذج الـ 4 (Claude/GPT/Gemini/DeepSeek)",
                "نمط الإجماع الكامل",
                "5 صور لتحليلها بالـ Vision",
                "ملفات حتى 50MB",
                "حفظ وتصدير المحادثات",
            ],
        },
        "basic": {
            "name": "شخصي",
            "price_usd": 9, "price_lyd": lyd(9),
            "period": "شهري",
            "messages_per_month": 250,
            "stripe_price_id": settings.STRIPE_PRICE_ID_BASIC,
            "features": [
                "250 رسالة جماعية/شهر",
                "بدون الحاجة لمفاتيح API",
                "30 صورة لتحليلها/شهر",
                "5 صور تُولّدها AI/شهر",
                "ملفات حتى 200MB",
                "أولوية أعلى في الاستجابة",
            ],
        },
        "pro": {
            "name": "محترف",
            "price_usd": 29, "price_lyd": lyd(29),
            "period": "شهري",
            "messages_per_month": 1500,
            "stripe_price_id": settings.STRIPE_PRICE_ID_PRO,
            "features": [
                "1500 رسالة جماعية/شهر",
                "200 صورة لتحليلها/شهر",
                "50 صورة تُولّدها AI/شهر",
                "5 فيديوهات تُولّد بـ AI/شهر",
                "ملفات حتى 2GB",
                "تصدير الكود والمستندات",
                "دعم بأولوية",
            ],
        },
        "business": {
            "name": "أعمال",
            "price_usd": 99, "price_lyd": lyd(99),
            "period": "شهري",
            "messages_per_month": 6000,
            "stripe_price_id": None,
            "features": [
                "6000 رسالة جماعية/شهر",
                "تحليل صور غير محدود",
                "200 صورة تُولّد/شهر",
                "30 فيديو يُولّد/شهر",
                "ملفات حتى 10GB",
                "API access للمطوّرين",
                "دعم مخصّص للشركات",
                "Onboarding للفريق",
            ],
        },
    }


@router.post("/checkout")
async def create_checkout_session(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    ينشئ Stripe checkout session.
    حالياً (حتى يتم إعداد Stripe): يُرجع رسالة عن الإعداد المطلوب.
    """
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail=(
                "Stripe لم يتم إعداده بعد. "
                "أضف STRIPE_SECRET_KEY و STRIPE_PRICE_ID_BASIC/PRO في .env."
            ),
        )

    if payload.plan not in ("basic", "pro"):
        raise HTTPException(status_code=400, detail="خطة غير صالحة")

    price_id = (
        settings.STRIPE_PRICE_ID_BASIC if payload.plan == "basic"
        else settings.STRIPE_PRICE_ID_PRO
    )
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"STRIPE_PRICE_ID_{payload.plan.upper()} غير معرّف",
        )

    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
    except ImportError:
        raise HTTPException(status_code=503, detail="مكتبة stripe غير مثبتة")

    try:
        # ابحث/أنشئ stripe customer
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.full_name or user.email,
                metadata={"user_id": str(user.id)},
            )
            user.stripe_customer_id = customer.id
            await db.flush()

        success_url = f"{settings.FRONTEND_URL}/?upgrade=success"
        cancel_url = f"{settings.FRONTEND_URL}/?upgrade=cancel"

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=user.stripe_customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": str(user.id), "plan": payload.plan},
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.exception("Stripe checkout failed")
        raise HTTPException(status_code=500, detail=f"فشل: {str(e)[:200]}")


@router.post("/portal")
async def create_portal_session(
    user: User = Depends(get_current_user),
):
    """فتح Stripe Customer Portal لإدارة الاشتراك"""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe لم يتم إعداده")
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="لا يوجد اشتراك مفعّل")

    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=settings.FRONTEND_URL,
        )
        return {"portal_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """يستقبل أحداث Stripe ويُحدّث خطة المستخدم"""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()
    try:
        import stripe
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.error("Invalid stripe signature: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {})

    # نتعامل فقط مع الأحداث المهمة
    if event_type == "checkout.session.completed":
        user_id = (obj.get("metadata") or {}).get("user_id")
        plan_str = (obj.get("metadata") or {}).get("plan")
        if user_id and plan_str:
            result = await db.execute(select(User).where(User.id == int(user_id)))
            u = result.scalar_one_or_none()
            if u:
                u.plan = PlanType(plan_str)
                logger.info(f"User {u.id} upgraded to {plan_str}")

    elif event_type == "customer.subscription.deleted":
        customer_id = obj.get("customer")
        if customer_id:
            result = await db.execute(
                select(User).where(User.stripe_customer_id == customer_id)
            )
            u = result.scalar_one_or_none()
            if u:
                u.plan = PlanType.FREE
                logger.info(f"User {u.id} downgraded to free (subscription canceled)")

    return {"received": True}
