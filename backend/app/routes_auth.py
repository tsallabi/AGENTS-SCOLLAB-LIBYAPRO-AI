"""
Auth Routes
- POST /auth/signup - تسجيل مستخدم جديد
- POST /auth/login - تسجيل دخول
- GET /auth/me - معلومات المستخدم الحالي
- PATCH /auth/me - تحديث الملف الشخصي
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, PlanType
from app.deps import get_current_user
from app.schemas import (
    UserSignup, UserLogin, TokenResponse, UserResponse
)
from app.security import (
    hash_password, verify_password, create_access_token
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(data: UserSignup, db: AsyncSession = Depends(get_db)):
    """تسجيل مستخدم جديد"""
    # تحقق من وجود الإيميل
    existing = await db.execute(
        select(User).where(User.email == data.email.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    
    # إنشاء المستخدم
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        plan=PlanType.FREE,
        is_active=True,
        is_verified=False,  # سنضيف email verification لاحقاً
    )
    db.add(user)
    await db.flush()  # للحصول على user.id
    
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )
    
    await db.commit()
    await db.refresh(user)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """تسجيل دخول"""
    result = await db.execute(
        select(User).where(User.email == data.email.lower())
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    
    # تحديث last_login
    user.last_login_at = datetime.utcnow()
    await db.commit()
    
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )
    
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """معلومات المستخدم الحالي"""
    return UserResponse.model_validate(user)
