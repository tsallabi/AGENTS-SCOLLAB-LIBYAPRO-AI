"""
Support Routes - مركز الرسائل الموحّد

Endpoints للزوّار:
- POST /api/support/threads          نموذج التواصل (channel=contact)
- POST /api/support/chat/start       بدء دردشة حيّة (channel=chat) - returns visitor_token
- POST /api/support/threads/{token}/messages  إضافة رسالة لخيط موجود
- GET  /api/support/threads/{token}  جلب الخيط + رسائله

Endpoints للـ admin (require_admin):
- GET  /api/support/admin/threads
- GET  /api/support/admin/threads/{id}
- POST /api/support/admin/threads/{id}/reply
- PATCH /api/support/admin/threads/{id}    (status / mark_read)
"""
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database import get_db
from app.deps import require_admin, get_current_user_optional
from app.models import SupportThread, SupportMessage, User


router = APIRouter(prefix="/support", tags=["support"])


# ============== Pydantic ==============

class ContactSubmit(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    subject: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=5000)


class ChatStart(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    initial_message: Optional[str] = Field(default=None, max_length=5000)


class ChatMessage(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class AdminReply(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class AdminPatch(BaseModel):
    status: Optional[str] = None
    mark_read: Optional[bool] = None


# ============== Serializers ==============

def serialize_thread(t: SupportThread, messages: List[SupportMessage] = None, include_messages: bool = False) -> dict:
    msgs = messages or []
    last_msg = msgs[-1] if msgs else None
    is_unread = bool(
        last_msg
        and last_msg.sender == "visitor"
        and (not t.last_admin_view_at or last_msg.created_at > t.last_admin_view_at)
    )
    out = {
        "id": t.id,
        "channel": t.channel,
        "name": t.name,
        "email": t.email,
        "phone": t.phone,
        "subject": t.subject,
        "status": t.status,
        "user_id": t.user_id,
        "created_at": t.created_at.isoformat(),
        "last_message_at": t.last_message_at.isoformat(),
        "last_admin_view_at": t.last_admin_view_at.isoformat() if t.last_admin_view_at else None,
        "last_visitor_view_at": t.last_visitor_view_at.isoformat() if t.last_visitor_view_at else None,
        "is_unread": is_unread,
        "message_count": len(msgs),
        "preview": (last_msg.content[:120] if last_msg else ""),
    }
    if include_messages:
        out["messages"] = [serialize_message(m) for m in msgs]
    return out


def serialize_message(m: SupportMessage) -> dict:
    return {
        "id": m.id,
        "sender": m.sender,
        "sender_name": m.sender_name,
        "content": m.content,
        "created_at": m.created_at.isoformat(),
    }


# ============== Visitor endpoints ==============

@router.post("/threads", status_code=201)
async def submit_contact(
    payload: ContactSubmit,
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    إرسال نموذج تواصل (one-shot).
    ينشئ thread جديد + رسالة واحدة.
    """
    token = uuid.uuid4().hex
    thread = SupportThread(
        channel="contact",
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        subject=payload.subject,
        visitor_token=token,
        user_id=user.id if user else None,
        ip_address=request.client.host if request.client else None,
        last_message_at=datetime.utcnow(),
    )
    db.add(thread)
    await db.flush()
    msg = SupportMessage(
        thread_id=thread.id,
        sender="visitor",
        sender_name=payload.name,
        content=payload.message,
    )
    db.add(msg)
    return {
        "ok": True,
        "thread_id": thread.id,
        "visitor_token": token,
        "message": "تم استلام رسالتك",
    }


@router.post("/chat/start", status_code=201)
async def start_chat(
    payload: ChatStart,
    request: Request,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    بدء دردشة حيّة من زائر.
    يُرجع visitor_token للزائر يحفظه في localStorage لاستئناف المحادثة.
    """
    token = uuid.uuid4().hex
    thread = SupportThread(
        channel="chat",
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        subject="دردشة حيّة",
        visitor_token=token,
        user_id=user.id if user else None,
        ip_address=request.client.host if request.client else None,
        last_message_at=datetime.utcnow(),
    )
    db.add(thread)
    await db.flush()
    if payload.initial_message:
        msg = SupportMessage(
            thread_id=thread.id,
            sender="visitor",
            sender_name=payload.name,
            content=payload.initial_message,
        )
        db.add(msg)
    return {"ok": True, "thread_id": thread.id, "visitor_token": token}


async def _get_thread_by_token(token: str, db: AsyncSession) -> SupportThread:
    result = await db.execute(
        select(SupportThread).where(SupportThread.visitor_token == token)
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.post("/threads/{token}/messages", status_code=201)
async def add_visitor_message(
    token: str,
    payload: ChatMessage,
    db: AsyncSession = Depends(get_db),
):
    """الزائر يضيف رسالة جديدة لخيطه"""
    thread = await _get_thread_by_token(token, db)
    if thread.status == "closed":
        raise HTTPException(status_code=410, detail="هذا الخيط مغلق")
    msg = SupportMessage(
        thread_id=thread.id,
        sender="visitor",
        sender_name=thread.name,
        content=payload.content,
    )
    db.add(msg)
    thread.last_message_at = datetime.utcnow()
    await db.flush()
    return {"ok": True, "message_id": msg.id}


@router.get("/threads/{token}")
async def get_visitor_thread(token: str, db: AsyncSession = Depends(get_db)):
    """الزائر يجلب خيطه + كل الرسائل"""
    thread = await _get_thread_by_token(token, db)
    msgs_q = await db.execute(
        select(SupportMessage)
        .where(SupportMessage.thread_id == thread.id)
        .order_by(SupportMessage.created_at)
    )
    messages = list(msgs_q.scalars().all())
    # سجّل أن الزائر شاف
    thread.last_visitor_view_at = datetime.utcnow()
    return serialize_thread(thread, messages=messages, include_messages=True)


# ============== Admin endpoints ==============

@router.get("/admin/threads")
async def admin_list_threads(
    status: Optional[str] = None,
    channel: Optional[str] = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """قائمة كل الخيوط (admin)"""
    q = select(SupportThread).order_by(desc(SupportThread.last_message_at)).limit(500)
    if status:
        q = q.where(SupportThread.status == status)
    if channel:
        q = q.where(SupportThread.channel == channel)
    threads = list((await db.execute(q)).scalars().all())
    out = []
    for t in threads:
        msgs_q = await db.execute(
            select(SupportMessage)
            .where(SupportMessage.thread_id == t.id)
            .order_by(SupportMessage.created_at)
        )
        messages = list(msgs_q.scalars().all())
        out.append(serialize_thread(t, messages=messages, include_messages=False))
    return out


@router.get("/admin/threads/{thread_id}")
async def admin_get_thread(
    thread_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """تفاصيل خيط محدد + كل رسائله"""
    result = await db.execute(select(SupportThread).where(SupportThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Not found")
    msgs_q = await db.execute(
        select(SupportMessage)
        .where(SupportMessage.thread_id == thread.id)
        .order_by(SupportMessage.created_at)
    )
    messages = list(msgs_q.scalars().all())
    # سجّل أن admin شاف الخيط
    thread.last_admin_view_at = datetime.utcnow()
    return serialize_thread(thread, messages=messages, include_messages=True)


@router.post("/admin/threads/{thread_id}/reply", status_code=201)
async def admin_reply(
    thread_id: int,
    payload: AdminReply,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin يرد على خيط"""
    result = await db.execute(select(SupportThread).where(SupportThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Not found")
    msg = SupportMessage(
        thread_id=thread.id,
        sender="admin",
        sender_name=user.full_name or user.email,
        content=payload.content,
    )
    db.add(msg)
    thread.last_message_at = datetime.utcnow()
    thread.last_admin_view_at = datetime.utcnow()
    if thread.status == "closed":
        thread.status = "open"
    await db.flush()
    return {"ok": True, "message_id": msg.id}


@router.patch("/admin/threads/{thread_id}")
async def admin_patch_thread(
    thread_id: int,
    payload: AdminPatch,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """تعديل حالة خيط (إغلاق/إعادة فتح/تمييز كمقروء)"""
    result = await db.execute(select(SupportThread).where(SupportThread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.status in ("open", "closed"):
        thread.status = payload.status
    if payload.mark_read:
        thread.last_admin_view_at = datetime.utcnow()
    await db.flush()
    return {"ok": True}


@router.get("/admin/stats")
async def admin_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """عدد الخيوط حسب الحالة + غير المقروءة"""
    from sqlalchemy import func
    total = (await db.execute(select(func.count(SupportThread.id)))).scalar() or 0
    open_count = (await db.execute(
        select(func.count(SupportThread.id)).where(SupportThread.status == "open")
    )).scalar() or 0
    chat_count = (await db.execute(
        select(func.count(SupportThread.id)).where(SupportThread.channel == "chat")
    )).scalar() or 0
    return {
        "total": total,
        "open": open_count,
        "chat": chat_count,
        "contact": total - chat_count,
    }
