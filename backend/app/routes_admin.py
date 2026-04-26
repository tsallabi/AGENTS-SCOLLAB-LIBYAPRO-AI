"""
Admin Routes - dashboard للمشرفين
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.database import get_db
from app.deps import require_admin
from app.models import (
    User, UsageLog, Message, MessageRole, Session as DbSession,
    PlanType, ContactMessage,
)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def admin_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """إحصائيات شاملة للداش بورد"""
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Users
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.last_login_at >= thirty_days_ago)
    )).scalar() or 0
    paid_users = (await db.execute(
        select(func.count(User.id)).where(User.plan != PlanType.FREE)
    )).scalar() or 0

    # By plan
    by_plan_result = await db.execute(
        select(User.plan, func.count(User.id)).group_by(User.plan)
    )
    by_plan = {row[0].value: row[1] for row in by_plan_result.all()}

    # Messages this month
    total_msgs_month = (await db.execute(
        select(func.count(Message.id)).where(
            Message.role == MessageRole.USER,
            Message.created_at >= month_start,
        )
    )).scalar() or 0

    # Cost this month
    cost_result = await db.execute(
        select(
            func.sum(UsageLog.cost_usd),
            func.sum(UsageLog.input_tokens),
            func.sum(UsageLog.output_tokens),
        ).where(UsageLog.created_at >= month_start)
    )
    total_cost, total_in, total_out = cost_result.one_or_none() or (0, 0, 0)

    # By agent
    by_agent_result = await db.execute(
        select(UsageLog.agent_id, func.count(UsageLog.id), func.sum(UsageLog.cost_usd))
        .where(UsageLog.created_at >= month_start)
        .group_by(UsageLog.agent_id)
    )
    by_agent = {
        row[0]: {"count": row[1], "cost": float(row[2] or 0)}
        for row in by_agent_result.all()
    }

    # MRR (rough estimate based on plan)
    mrr_basic = (await db.execute(
        select(func.count(User.id)).where(User.plan == PlanType.BASIC)
    )).scalar() or 0
    mrr_pro = (await db.execute(
        select(func.count(User.id)).where(User.plan == PlanType.PRO)
    )).scalar() or 0
    mrr = (mrr_basic * 9) + (mrr_pro * 49)

    # Unread contacts
    unread_contacts = (await db.execute(
        select(func.count(ContactMessage.id)).where(ContactMessage.is_read == False)
    )).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "active_30d": active_users,
            "paid": paid_users,
            "by_plan": by_plan,
        },
        "revenue": {
            "mrr_estimate_usd": mrr,
            "paying_users": mrr_basic + mrr_pro,
        },
        "this_month": {
            "messages": total_msgs_month,
            "cost_usd": float(total_cost or 0),
            "input_tokens": int(total_in or 0),
            "output_tokens": int(total_out or 0),
            "by_agent": by_agent,
        },
        "contacts": {
            "unread": unread_contacts,
        },
    }


@router.get("/users")
async def list_users(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """قائمة المستخدمين"""
    result = await db.execute(
        select(User).order_by(desc(User.created_at)).limit(200)
    )
    users = []
    for u in result.scalars().all():
        # Count messages this month per user
        msg_count = (await db.execute(
            select(func.count(Message.id))
            .select_from(Message)
            .join(DbSession, Message.session_id == DbSession.id)
            .where(
                DbSession.user_id == u.id,
                Message.role == MessageRole.USER,
            )
        )).scalar() or 0

        cost = (await db.execute(
            select(func.sum(UsageLog.cost_usd)).where(UsageLog.user_id == u.id)
        )).scalar() or 0

        users.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "plan": u.plan.value,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "total_messages": msg_count,
            "total_cost_usd": float(cost or 0),
        })
    return users


@router.get("/insights")
async def admin_insights(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Marketing Insights - يجمع بيانات سلوك المستخدمين لاستهداف الحملات.
    يُرجع: top topics, active users, popular sessions, search trends.
    """
    from collections import Counter
    import re
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    # 1. أكثر المستخدمين نشاطاً (آخر 30 يوم)
    active_users_q = await db.execute(
        select(User.id, User.email, User.full_name, User.plan,
               func.count(Message.id).label("msg_count"))
        .select_from(User)
        .join(DbSession, DbSession.user_id == User.id, isouter=True)
        .join(Message, Message.session_id == DbSession.id, isouter=True)
        .where(Message.created_at >= thirty_days_ago, Message.role == MessageRole.USER)
        .group_by(User.id)
        .order_by(desc("msg_count"))
        .limit(20)
    )
    top_users = [
        {
            "id": r.id, "email": r.email, "full_name": r.full_name,
            "plan": r.plan.value, "messages_30d": r.msg_count or 0,
        }
        for r in active_users_q.all()
    ]

    # 2. أكثر الكلمات تكراراً في رسائل المستخدمين (لاستخراج الاهتمامات)
    user_messages_q = await db.execute(
        select(Message.content)
        .where(Message.role == MessageRole.USER, Message.created_at >= thirty_days_ago)
        .limit(2000)
    )
    word_counter = Counter()
    # كلمات يجب تجاهلها (stop words عربية + إنجليزية)
    stopwords = {
        'في','من','الى','على','مع','عن','ما','هل','كيف','هذا','هذه','ذلك','تلك','أن','إن','قد',
        'the','a','an','is','are','was','were','of','to','in','on','at','for','with','by',
        'and','or','but','if','so','as','it','this','that','these','those','what','how','can',
        'i','you','he','she','we','they','me','my','your','his','her','our','their',
        'do','does','did','have','has','had','be','been','being','will','would','could','should',
    }
    for (content,) in user_messages_q.all():
        if not content:
            continue
        # استخرج كلمات (دعم العربية + الإنجليزية)
        words = re.findall(r'[\w؀-ۿ]{3,}', content.lower())
        for w in words:
            if w not in stopwords and not w.isdigit():
                word_counter[w] += 1
    top_topics = [{"keyword": w, "count": c} for w, c in word_counter.most_common(50)]

    # 3. توزيع الأنماط (consensus vs round_robin vs solo)
    mode_q = await db.execute(
        select(Message.mode, func.count(Message.id))
        .where(Message.role == MessageRole.USER, Message.created_at >= thirty_days_ago,
               Message.mode.isnot(None))
        .group_by(Message.mode)
    )
    by_mode = {row[0].value if hasattr(row[0], 'value') else str(row[0]): row[1] for row in mode_q.all()}

    # 4. ملفات مرفوعة (لو كان جدول uploaded_files موجوداً)
    upload_count = 0
    try:
        from app.routes_files import UploadedFile
        uc = await db.execute(
            select(func.count(UploadedFile.id)).where(UploadedFile.created_at >= thirty_days_ago)
        )
        upload_count = uc.scalar() or 0
    except Exception:
        pass

    # 5. توزيع الخطط (للاستهداف التسويقي)
    by_plan_q = await db.execute(
        select(User.plan, func.count(User.id)).group_by(User.plan)
    )
    by_plan = {row[0].value: row[1] for row in by_plan_q.all()}

    return {
        "period_days": 30,
        "top_active_users": top_users,
        "top_topics": top_topics,
        "by_conversation_mode": by_mode,
        "files_uploaded_30d": upload_count,
        "users_by_plan": by_plan,
        "free_users_for_targeting": [
            u for u in top_users if u["plan"] == "free" and u["messages_30d"] >= 5
        ],
    }


@router.patch("/users/{user_id}")
async def update_user_admin(
    user_id: int,
    plan: str | None = None,
    is_active: bool | None = None,
    is_admin: bool | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """تعديل خطة/تفعيل/admin لمستخدم"""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if plan is not None:
        try:
            target.plan = PlanType(plan)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid plan: {plan}")
    if is_active is not None:
        target.is_active = is_active
    if is_admin is not None:
        target.is_admin = is_admin
    return {"ok": True, "user_id": target.id}
