"""
Image Generation Routes - توليد صور بـ DALL-E 3 (OpenAI)

Pricing (DALL-E 3):
- standard 1024x1024: $0.040
- standard 1024x1792 / 1792x1024: $0.080
- HD 1024x1024: $0.080

نُلاحظ في DB:
- generated_images table: user, prompt, url, cost, model, size, created_at

⚠️ يحتاج SERVER_OPENAI_KEY في .env
"""
import logging
import uuid
from typing import Optional
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import (
    Integer, String, Float, DateTime, ForeignKey, Text, select, desc
)
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Base, User, PlanType
from app.routes_usage import count_user_messages_this_month

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["images"])


# ============== Model ==============

class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)

    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    revised_prompt: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)

    model: Mapped[str] = mapped_column(String(50), default="dall-e-3")
    size: Mapped[str] = mapped_column(String(20), default="1024x1024")
    quality: Mapped[str] = mapped_column(String(20), default="standard")
    cost_usd: Mapped[float] = mapped_column(Float, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ============== Quotas per plan ==============
IMAGE_QUOTAS = {
    "free":     0,
    "basic":    5,
    "pro":      50,
    "business": 200,
}

DALLE3_PRICES = {
    ("standard", "1024x1024"): 0.040,
    ("standard", "1024x1792"): 0.080,
    ("standard", "1792x1024"): 0.080,
    ("hd", "1024x1024"):       0.080,
    ("hd", "1024x1792"):       0.120,
    ("hd", "1792x1024"):       0.120,
}


# ============== Pydantic ==============

class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    size: str = Field(default="1024x1024", pattern="^(1024x1024|1024x1792|1792x1024)$")
    quality: str = Field(default="standard", pattern="^(standard|hd)$")
    style: str = Field(default="vivid", pattern="^(vivid|natural)$")
    session_id: Optional[int] = None


# ============== Endpoints ==============

@router.post("/generate")
async def generate_image(
    payload: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """يُولّد صورة بـ DALL-E 3 ويحفظها في DB"""
    if not settings.SERVER_OPENAI_KEY:
        raise HTTPException(status_code=503, detail="OpenAI API key غير مُعدّ")

    # تحقّق من الحصة الشهرية حسب الخطة
    plan_key = user.plan.value if hasattr(user.plan, 'value') else str(user.plan)
    quota = IMAGE_QUOTAS.get(plan_key, 0)
    if quota == 0:
        raise HTTPException(
            status_code=403,
            detail=f"خطة {plan_key} لا تشمل توليد الصور. ترقّ لخطة أعلى.",
        )

    from sqlalchemy import func
    from datetime import timedelta
    period_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = (await db.execute(
        select(func.count(GeneratedImage.id))
        .where(GeneratedImage.user_id == user.id, GeneratedImage.created_at >= period_start)
    )).scalar() or 0

    if used >= quota:
        raise HTTPException(
            status_code=429,
            detail=f"تجاوزت حد توليد الصور ({quota}/شهر) لخطة {plan_key}.",
        )

    # طلب DALL-E 3
    cost = DALLE3_PRICES.get((payload.quality, payload.size), 0.040)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {settings.SERVER_OPENAI_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "dall-e-3",
                    "prompt": payload.prompt,
                    "n": 1,
                    "size": payload.size,
                    "quality": payload.quality,
                    "style": payload.style,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.exception("DALL-E 3 failed")
        raise HTTPException(status_code=500, detail=f"فشل توليد الصورة: {str(e)[:200]}")

    img_data = data["data"][0]
    img_url = img_data["url"]
    revised = img_data.get("revised_prompt")

    # احفظ في DB
    record = GeneratedImage(
        user_id=user.id,
        session_id=payload.session_id,
        prompt=payload.prompt,
        revised_prompt=revised,
        image_url=img_url,
        model="dall-e-3",
        size=payload.size,
        quality=payload.quality,
        cost_usd=cost,
    )
    db.add(record)
    await db.flush()

    return {
        "id": record.id,
        "image_url": img_url,
        "prompt": payload.prompt,
        "revised_prompt": revised,
        "size": payload.size,
        "quality": payload.quality,
        "cost_usd": cost,
        "remaining_this_month": max(0, quota - used - 1),
        "quota_per_month": quota,
    }


@router.get("/my")
async def list_my_images(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """قائمة صوري المُولَّدة"""
    result = await db.execute(
        select(GeneratedImage)
        .where(GeneratedImage.user_id == user.id)
        .order_by(desc(GeneratedImage.created_at))
        .limit(100)
    )
    return [
        {
            "id": r.id,
            "prompt": r.prompt,
            "revised_prompt": r.revised_prompt,
            "image_url": r.image_url,
            "size": r.size,
            "quality": r.quality,
            "cost_usd": r.cost_usd,
            "created_at": r.created_at.isoformat(),
        }
        for r in result.scalars().all()
    ]


@router.get("/quota")
async def my_image_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """الحصة المتبقية"""
    plan_key = user.plan.value if hasattr(user.plan, 'value') else str(user.plan)
    quota = IMAGE_QUOTAS.get(plan_key, 0)
    period_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    from sqlalchemy import func
    used = (await db.execute(
        select(func.count(GeneratedImage.id))
        .where(GeneratedImage.user_id == user.id, GeneratedImage.created_at >= period_start)
    )).scalar() or 0
    return {
        "plan": plan_key,
        "quota_per_month": quota,
        "used_this_month": used,
        "remaining": max(0, quota - used),
    }
