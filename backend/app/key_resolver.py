"""
Key Resolution Logic
هذه أهم منطق في النظام: لكل user + agent، أي مفتاح نستخدم؟

القواعد:
- المستخدم Free: يجب أن يكون لديه مفتاحه الخاص
- المستخدم Basic/Pro: يستخدم مفتاح السيرفر إذا متوفر، وإلا مفتاحه

نرجع أيضاً معلومة هل استُخدم مفتاح السيرفر (للمحاسبة).
"""
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models import User, ApiKey, PlanType
from app.security import decrypt_api_key


@dataclass
class ResolvedKey:
    """مفتاح جاهز للاستخدام"""
    key: str
    is_server_key: bool  # True إذا من السيرفر، False إذا من المستخدم
    provider: str


PROVIDER_FROM_AGENT = {
    "claude": "anthropic",
    "gpt": "openai",
    "gemini": "gemini",
    "deepseek": "deepseek",
    "manus": "manus",  # مدمج - لا يحتاج API key
}


def get_server_key(provider: str) -> Optional[str]:
    """يجلب مفتاح السيرفر لـ provider محدد"""
    keys = {
        "anthropic": settings.SERVER_ANTHROPIC_KEY,
        "openai": settings.SERVER_OPENAI_KEY,
        "gemini": settings.SERVER_GEMINI_KEY,
        "deepseek": settings.SERVER_DEEPSEEK_KEY,
    }
    key = keys.get(provider)
    if key and len(key.strip()) > 10:
        return key.strip()
    return None


async def resolve_key_for_user(
    user: User,
    agent_id: str,
    db: AsyncSession,
) -> Optional[ResolvedKey]:
    """
    يحدد أي مفتاح يستخدم المستخدم لـ agent معين.
    يرجع None إذا لا يوجد مفتاح متاح.
    
    منطق الاختيار:
    1. خطة Pro/Basic: يحاول مفتاح السيرفر أولاً
    2. fallback لمفتاح المستخدم
    3. خطة Free: مفتاح المستخدم فقط
    """
    provider = PROVIDER_FROM_AGENT.get(agent_id)
    if not provider:
        return None

    # Manus مدمج دائماً - متاح لجميع المستخدمين بدون API key
    if provider == "manus":
        return ResolvedKey(key="manus-built-in", is_server_key=True, provider="manus")
    
    # خطة مدفوعة: حاول مفتاح السيرفر أولاً
    if user.plan in (PlanType.BASIC, PlanType.PRO):
        server_key = get_server_key(provider)
        if server_key:
            return ResolvedKey(
                key=server_key,
                is_server_key=True,
                provider=provider,
            )
    
    # حاول مفتاح المستخدم
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user.id,
            ApiKey.provider == provider,
        )
    )
    user_key = result.scalar_one_or_none()
    
    if user_key:
        decrypted = decrypt_api_key(user_key.encrypted_key)
        if decrypted:
            return ResolvedKey(
                key=decrypted,
                is_server_key=False,
                provider=provider,
            )
    
    return None


async def get_available_agents_for_user(
    user: User,
    db: AsyncSession,
) -> dict[str, dict]:
    """
    يرجع dict: {agent_id: {"available": bool, "reason": str}}
    """
    from app.agents import AGENT_CLASSES
    
    result = {}
    for agent_id in AGENT_CLASSES.keys():
        resolved = await resolve_key_for_user(user, agent_id, db)
        if resolved:
            result[agent_id] = {
                "available": True,
                "reason": "server_key" if resolved.is_server_key else "user_key",
            }
        else:
            result[agent_id] = {
                "available": False,
                "reason": None,
            }
    
    return result
