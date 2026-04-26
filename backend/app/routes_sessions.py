"""
Sessions Routes - CRUD للجلسات + تصدير
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.database import get_db
from app.deps import get_current_user
from app.models import User, Session as DbSession, Message, MessageRole, ConversationMode
from app.schemas import SessionCreate, SessionUpdate, SessionResponse, MessageResponse


router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _get_owned_session(
    session_id: int,
    user: User,
    db: AsyncSession,
) -> DbSession:
    """يجلب جلسة ويتحقق أنها للمستخدم الحالي"""
    result = await db.execute(
        select(DbSession).where(
            DbSession.id == session_id,
            DbSession.user_id == user.id,
        )
    )
    sess = result.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    return sess


@router.get("", response_model=List[SessionResponse])
async def list_sessions(
    archived: bool = Query(False, description="عرض المؤرشفة فقط"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """قائمة جلسات المستخدم (الحديث أولاً)"""
    result = await db.execute(
        select(DbSession)
        .where(
            DbSession.user_id == user.id,
            DbSession.is_archived == archived,
        )
        .order_by(DbSession.updated_at.desc())
    )
    sessions = list(result.scalars().all())

    # احسب عدد الرسائل لكل جلسة
    out: List[SessionResponse] = []
    for s in sessions:
        count_result = await db.execute(
            select(func.count(Message.id)).where(Message.session_id == s.id)
        )
        msg_count = count_result.scalar() or 0
        out.append(
            SessionResponse(
                id=s.id,
                title=s.title,
                default_mode=s.default_mode,
                default_agents=s.default_agents or [],
                is_archived=s.is_archived,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=msg_count,
            )
        )
    return out


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: SessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """إنشاء جلسة جديدة"""
    sess = DbSession(
        user_id=user.id,
        title=payload.title or "محادثة جديدة",
        default_mode=payload.default_mode,
        default_agents=payload.default_agents or [],
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return SessionResponse(
        id=sess.id,
        title=sess.title,
        default_mode=sess.default_mode,
        default_agents=sess.default_agents or [],
        is_archived=sess.is_archived,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        message_count=0,
    )


@router.get("/{session_id}", response_model=dict)
async def get_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تفاصيل جلسة + كل رسائلها"""
    sess = await _get_owned_session(session_id, user, db)
    msgs = await db.execute(
        select(Message)
        .where(Message.session_id == sess.id)
        .order_by(Message.created_at)
    )
    messages = [
        MessageResponse(
            id=m.id,
            role=m.role,
            agent_id=m.agent_id,
            agent_name=m.agent_name,
            content=m.content,
            mode=m.mode,
            phase=m.phase,
            created_at=m.created_at,
        )
        for m in msgs.scalars().all()
    ]
    return {
        "session": SessionResponse(
            id=sess.id,
            title=sess.title,
            default_mode=sess.default_mode,
            default_agents=sess.default_agents or [],
            is_archived=sess.is_archived,
            created_at=sess.created_at,
            updated_at=sess.updated_at,
            message_count=len(messages),
        ),
        "messages": messages,
    }


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: int,
    payload: SessionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تحديث الجلسة (title/mode/agents/archived)"""
    sess = await _get_owned_session(session_id, user, db)
    if payload.title is not None:
        sess.title = payload.title
    if payload.default_mode is not None:
        sess.default_mode = payload.default_mode
    if payload.default_agents is not None:
        sess.default_agents = payload.default_agents
    if payload.is_archived is not None:
        sess.is_archived = payload.is_archived
    await db.flush()
    await db.refresh(sess)

    count_result = await db.execute(
        select(func.count(Message.id)).where(Message.session_id == sess.id)
    )
    return SessionResponse(
        id=sess.id,
        title=sess.title,
        default_mode=sess.default_mode,
        default_agents=sess.default_agents or [],
        is_archived=sess.is_archived,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        message_count=count_result.scalar() or 0,
    )


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حذف الجلسة وكل رسائلها"""
    sess = await _get_owned_session(session_id, user, db)
    await db.delete(sess)


@router.post("/{session_id}/export", response_class=PlainTextResponse)
async def export_session(
    session_id: int,
    format: str = Query("markdown", pattern="^(markdown|text)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تصدير الجلسة كـ markdown أو text"""
    sess = await _get_owned_session(session_id, user, db)
    msgs = await db.execute(
        select(Message)
        .where(Message.session_id == sess.id)
        .order_by(Message.created_at)
    )
    messages = list(msgs.scalars().all())

    lines: list[str] = []
    if format == "markdown":
        lines.append(f"# {sess.title}\n")
        lines.append(f"_تاريخ الإنشاء: {sess.created_at.strftime('%Y-%m-%d %H:%M')}_\n")
        lines.append(f"_النمط: {sess.default_mode.value}_\n\n---\n")
        for m in messages:
            ts = m.created_at.strftime("%H:%M")
            if m.role == MessageRole.USER:
                lines.append(f"\n## 👤 المستخدم — {ts}\n\n{m.content}\n")
            elif m.role == MessageRole.AGENT:
                phase = f" _[{m.phase}]_" if m.phase else ""
                lines.append(f"\n## 🤖 {m.agent_name or m.agent_id}{phase} — {ts}\n\n{m.content}\n")
            else:
                lines.append(f"\n_{m.content}_\n")
    else:  # text
        lines.append(f"{sess.title}\n{'=' * len(sess.title)}\n")
        for m in messages:
            ts = m.created_at.strftime("%Y-%m-%d %H:%M")
            if m.role == MessageRole.USER:
                lines.append(f"\n[المستخدم - {ts}]\n{m.content}\n")
            elif m.role == MessageRole.AGENT:
                phase = f" ({m.phase})" if m.phase else ""
                lines.append(f"\n[{m.agent_name or m.agent_id}{phase} - {ts}]\n{m.content}\n")
    return "".join(lines)
