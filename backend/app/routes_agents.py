"""
Agents Routes
- GET /agents - قائمة كل الـ agents مع حالة التوفر للمستخدم الحالي
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.deps import get_current_user
from app.schemas import AgentInfoResponse
from app.agents import get_all_agent_infos
from app.key_resolver import get_available_agents_for_user


router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfoResponse])
async def list_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """قائمة الـ agents مع حالة التوفر للمستخدم"""
    infos = get_all_agent_infos()
    availability = await get_available_agents_for_user(user, db)
    
    return [
        AgentInfoResponse(
            id=info.id,
            name=info.name,
            provider=info.provider,
            role=info.role,
            color=info.color,
            description=info.description,
            model=info.model,
            input_price_per_mtok=info.input_price_per_mtok,
            output_price_per_mtok=info.output_price_per_mtok,
            available=availability[info.id]["available"],
            available_reason=availability[info.id]["reason"],
        )
        for info in infos
    ]
