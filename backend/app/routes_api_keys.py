"""
API Keys Routes
- GET /api-keys - قائمة مفاتيح المستخدم (مع masking)
- POST /api-keys - إضافة/تحديث مفتاح
- DELETE /api-keys/{provider} - حذف مفتاح
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models import User, ApiKey
from app.deps import get_current_user
from app.schemas import ApiKeyCreate, ApiKeyResponse
from app.security import encrypt_api_key, decrypt_api_key, mask_api_key


router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _to_response(key: ApiKey) -> ApiKeyResponse:
    """تحويل ApiKey لـ response مع masking"""
    decrypted = decrypt_api_key(key.encrypted_key) or ""
    return ApiKeyResponse(
        id=key.id,
        provider=key.provider,
        masked_key=mask_api_key(decrypted),
        is_valid=key.is_valid,
        last_used_at=key.last_used_at,
        usage_count=key.usage_count,
        created_at=key.created_at,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """قائمة مفاتيح المستخدم"""
    result = await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id)
    )
    keys = result.scalars().all()
    return [_to_response(k) for k in keys]


@router.post("", response_model=ApiKeyResponse)
async def add_api_key(
    data: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """إضافة أو تحديث مفتاح API"""
    # هل يوجد مفتاح لهذا الـ provider بالفعل؟
    existing = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user.id,
            ApiKey.provider == data.provider,
        )
    )
    existing_key = existing.scalar_one_or_none()
    
    encrypted = encrypt_api_key(data.key)
    
    if existing_key:
        # تحديث
        existing_key.encrypted_key = encrypted
        existing_key.is_valid = True  # نفترض أنه صالح حتى نتحقق
        await db.commit()
        await db.refresh(existing_key)
        return _to_response(existing_key)
    else:
        # إضافة
        new_key = ApiKey(
            user_id=user.id,
            provider=data.provider,
            encrypted_key=encrypted,
            is_valid=True,
        )
        db.add(new_key)
        await db.commit()
        await db.refresh(new_key)
        return _to_response(new_key)


@router.delete("/{provider}", status_code=204)
async def delete_api_key(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حذف مفتاح"""
    result = await db.execute(
        delete(ApiKey).where(
            ApiKey.user_id == user.id,
            ApiKey.provider == provider,
        )
    )
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="API key not found")
    return None
