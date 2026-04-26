"""
نظام الأمان:
1. تشفير كلمات المرور (bcrypt مباشرة)
2. JWT للمصادقة
3. تشفير مفاتيح API الخاصة بالمستخدم (Fernet symmetric encryption)
"""
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import bcrypt
from jose import jwt, JWTError
from cryptography.fernet import Fernet
from app.config import settings


# ============== Password Hashing ==============

def hash_password(password: str) -> str:
    """تشفير كلمة مرور باستخدام bcrypt مباشرة"""
    # bcrypt يحد الـ password بـ 72 byte - نقصّه إذا أطول
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """التحقق من كلمة مرور"""
    try:
        pw_bytes = plain.encode("utf-8")[:72]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except Exception:
        return False


# ============== JWT Tokens ==============

def create_access_token(
    user_id: int,
    email: str,
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """إنشاء JWT token"""
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    
    expire = datetime.now(timezone.utc) + expires_delta
    
    payload = {
        "sub": str(user_id),
        "email": email,
        "is_admin": is_admin,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """فك JWT - يرجع payload أو None إذا غير صالح"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


# ============== API Key Encryption ==============

def _get_fernet() -> Fernet:
    """يبني Fernet key من SECRET_KEY"""
    # نحتاج 32 byte key مشفر base64
    key_bytes = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_api_key(plain_key: str) -> str:
    """تشفير مفتاح API"""
    f = _get_fernet()
    return f.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> Optional[str]:
    """فك تشفير مفتاح API - يرجع None إذا فشل"""
    try:
        f = _get_fernet()
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        return None


def mask_api_key(key: str) -> str:
    """إخفاء مفتاح للعرض: sk-...abc123 -> sk-•••••••...c123"""
    if not key or len(key) < 12:
        return "•" * 8
    return f"{key[:5]}{'•' * 8}{key[-4:]}"
