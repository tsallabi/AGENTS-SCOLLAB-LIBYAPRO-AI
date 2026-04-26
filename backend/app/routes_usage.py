"""
Usage Routes - تتبع الاستخدام + الحدود
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.deps import get_current_user
from app.models import User, UsageLog, Message, MessageRole, PlanType
from app.config import settings


router = APIRouter(prefix="/usage", tags=["usage"])


def _plan_limit(plan: PlanType) -> int:
    """الحد الشهري لكل خطة"""
    if plan == PlanType.PRO:
        return settings.PLAN_PRO_MESSAGES_PER_MONTH
    if plan == PlanType.BASIC:
        return settings.PLAN_BASIC_MESSAGES_PER_MONTH
    return settings.PLAN_FREE_MESSAGES_PER_MONTH


def _month_start(now: datetime) -> datetime:
    """بداية الشهر الحالي"""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def count_user_messages_this_month(
    user_id: int,
    db: AsyncSession,
) -> int:
    """يحسب عدد رسائل المستخدم (role=USER) في الشهر الحالي"""
    period_start = _month_start(datetime.utcnow())
    result = await db.execute(
        select(func.count(Message.id))
        .join(Message.session)
        .where(
            Message.role == MessageRole.USER,
            Message.created_at >= period_start,
        )
    )
    # الحاجة لربط على user عبر session - نستخدم استعلام أبسط
    from app.models import Session as DbSession
    result = await db.execute(
        select(func.count(Message.id))
        .select_from(Message)
        .join(DbSession, Message.session_id == DbSession.id)
        .where(
            DbSession.user_id == user_id,
            Message.role == MessageRole.USER,
            Message.created_at >= period_start,
        )
    )
    return result.scalar() or 0


async def check_usage_limit(user: User, db: AsyncSession) -> tuple[bool, dict]:
    """
    يفحص ما إذا كان المستخدم تحت الحد.
    يرجع (allowed, info_dict)
    """
    limit = _plan_limit(user.plan)
    used = await count_user_messages_this_month(user.id, db)
    return (used < limit), {
        "plan": user.plan.value,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
    }


@router.get("/me")
async def get_my_usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """إحصائيات استخدامي للشهر الحالي"""
    period_start = _month_start(datetime.utcnow())
    period_end = (period_start + timedelta(days=32)).replace(day=1)

    # عدد الرسائل
    used = await count_user_messages_this_month(user.id, db)
    limit = _plan_limit(user.plan)

    # تكلفة + tokens من UsageLog
    cost_result = await db.execute(
        select(
            func.sum(UsageLog.cost_usd),
            func.sum(UsageLog.input_tokens),
            func.sum(UsageLog.output_tokens),
        ).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= period_start,
        )
    )
    total_cost, total_in, total_out = cost_result.one_or_none() or (0, 0, 0)

    # تفصيل بـ agent
    by_agent_result = await db.execute(
        select(UsageLog.agent_id, func.count(UsageLog.id))
        .where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= period_start,
        )
        .group_by(UsageLog.agent_id)
    )
    by_agent = {row[0]: row[1] for row in by_agent_result.all()}

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "plan": user.plan.value,
        "total_messages": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "limit_reached": used >= limit,
        "by_agent": by_agent,
        "total_cost_usd": float(total_cost or 0),
        "total_input_tokens": int(total_in or 0),
        "total_output_tokens": int(total_out or 0),
    }
