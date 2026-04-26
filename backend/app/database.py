"""
Database Setup - Async SQLAlchemy
يدعم PostgreSQL (للإنتاج) و SQLite (للتطوير)
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine
)
from app.config import settings
from app.models import Base


# تحويل URL من sync لـ async تلقائياً إذا لزم
def _get_async_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+aiomysql://")
    if url.startswith("mysql+mysqldb://"):
        return url.replace("mysql+mysqldb://", "mysql+aiomysql://")
    return url


DATABASE_URL = _get_async_url(settings.DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    # SQLite لا يدعم pool size
    **(({"pool_size": 10, "max_overflow": 20}) if ("postgresql" in DATABASE_URL or "mysql" in DATABASE_URL) else {})
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection للـ DB session"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """إنشاء كل الجداول (للتطوير - في الإنتاج استخدم Alembic)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """إغلاق الاتصال عند توقف التطبيق"""
    await engine.dispose()
