"""
Contact Routes - نموذج التواصل من صفحة الهبوط
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db
from app.deps import require_admin
from app.models import ContactMessage, User


router = APIRouter(prefix="/contact", tags=["contact"])


class ContactCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    subject: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=5000)


@router.post("", status_code=201)
async def submit_contact(
    payload: ContactCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """رسالة تواصل من زائر (لا يحتاج تسجيل دخول)"""
    msg = ContactMessage(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        subject=payload.subject,
        message=payload.message,
        ip_address=(request.client.host if request.client else None),
    )
    db.add(msg)
    await db.flush()
    return {"ok": True, "id": msg.id, "message": "تم استلام رسالتك"}


# --- Admin endpoints ---

@router.get("/admin/list")
async def list_contacts(
    unread_only: bool = False,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """قائمة الرسائل (admin only)"""
    q = select(ContactMessage).order_by(desc(ContactMessage.created_at)).limit(200)
    if unread_only:
        q = q.where(ContactMessage.is_read == False)
    result = await db.execute(q)
    return [
        {
            "id": m.id,
            "name": m.name,
            "email": m.email,
            "phone": m.phone,
            "subject": m.subject,
            "message": m.message,
            "is_read": m.is_read,
            "is_replied": m.is_replied,
            "created_at": m.created_at.isoformat(),
        }
        for m in result.scalars().all()
    ]


@router.patch("/admin/{contact_id}")
async def update_contact(
    contact_id: int,
    is_read: Optional[bool] = None,
    is_replied: Optional[bool] = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """تحديث حالة رسالة"""
    result = await db.execute(select(ContactMessage).where(ContactMessage.id == contact_id))
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    if is_read is not None:
        m.is_read = is_read
    if is_replied is not None:
        m.is_replied = is_replied
    return {"ok": True}
