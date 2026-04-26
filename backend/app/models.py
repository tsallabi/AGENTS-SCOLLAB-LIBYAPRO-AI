"""
Database Models - SQLAlchemy
كل جداول التطبيق:
- User: المستخدمون
- Subscription: الاشتراكات
- ApiKey: مفاتيح المستخدم المشفرة
- Session: جلسات المحادثة
- Message: الرسائل
- UsageLog: سجل الاستخدام (للحدود والتحليلات)
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Integer, DateTime, Boolean, Text, ForeignKey,
    Enum as SQLEnum, JSON, Index, Float
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    pass


# ============== Enums ==============

class PlanType(str, enum.Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    INCOMPLETE = "incomplete"
    TRIALING = "trialing"


class MessageRole(str, enum.Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class ConversationMode(str, enum.Enum):
    SOLO = "solo"
    ROUND_ROBIN = "round_robin"
    CONSENSUS = "consensus"


# ============== Models ==============

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Plan
    plan: Mapped[PlanType] = mapped_column(
        SQLEnum(PlanType, native_enum=False),
        default=PlanType.FREE,
        nullable=False
    )
    
    # Stripe
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Relationships
    subscription: Mapped[Optional["Subscription"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    api_keys: Mapped[List["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    usage_logs: Mapped[List["UsageLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    
    # Stripe
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    stripe_price_id: Mapped[str] = mapped_column(String(255))
    
    # Status
    status: Mapped[SubscriptionStatus] = mapped_column(
        SQLEnum(SubscriptionStatus, native_enum=False),
        nullable=False
    )
    plan: Mapped[PlanType] = mapped_column(
        SQLEnum(PlanType, native_enum=False),
        nullable=False
    )
    
    # Periods
    current_period_start: Mapped[datetime] = mapped_column(DateTime)
    current_period_end: Mapped[datetime] = mapped_column(DateTime)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user: Mapped["User"] = relationship(back_populates="subscription")


class ApiKey(Base):
    """
    مفاتيح API للمستخدم (للخطة المجانية)
    مشفرة في قاعدة البيانات
    """
    __tablename__ = "api_keys"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # anthropic, openai, gemini, deepseek
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    
    # متى استُخدم آخر مرة وعدد المرات
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)  # هل آخر استخدام نجح؟
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    user: Mapped["User"] = relationship(back_populates="api_keys")
    
    __table_args__ = (
        Index("idx_user_provider", "user_id", "provider", unique=True),
    )


class Session(Base):
    """جلسة محادثة"""
    __tablename__ = "sessions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    title: Mapped[str] = mapped_column(String(200), default="محادثة جديدة")
    
    # الإعدادات الافتراضية للجلسة
    default_mode: Mapped[ConversationMode] = mapped_column(
        SQLEnum(ConversationMode, native_enum=False),
        default=ConversationMode.ROUND_ROBIN
    )
    default_agents: Mapped[List[str]] = mapped_column(JSON, default=list)  # ["claude", "gpt", "gemini"]
    
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user: Mapped["User"] = relationship(back_populates="sessions")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    """رسالة في جلسة"""
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    
    role: Mapped[MessageRole] = mapped_column(
        SQLEnum(MessageRole, native_enum=False),
        nullable=False
    )
    
    # إذا كانت من agent، أي agent؟
    agent_id: Mapped[Optional[str]] = mapped_column(String(50))
    agent_name: Mapped[Optional[str]] = mapped_column(String(100))
    
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Meta
    mode: Mapped[Optional[ConversationMode]] = mapped_column(
        SQLEnum(ConversationMode, native_enum=False)
    )
    phase: Mapped[Optional[str]] = mapped_column(String(50))  # proposals, critique, synthesis
    
    # Tokens & cost (للتحليلات)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    session: Mapped["Session"] = relationship(back_populates="messages")


class UsageLog(Base):
    """سجل استخدام لأغراض الحدود والتحليلات"""
    __tablename__ = "usage_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    agent_id: Mapped[str] = mapped_column(String(50))
    used_server_key: Mapped[bool] = mapped_column(Boolean, default=False)  # مفتاح السيرفر أم المستخدم؟
    
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    user: Mapped["User"] = relationship(back_populates="usage_logs")
    
    __table_args__ = (
        Index("idx_user_date", "user_id", "created_at"),
    )


class ContactMessage(Base):
    """رسائل التواصل من صفحة الهبوط (legacy - تُبقى للتوافق)"""
    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    subject: Mapped[Optional[str]] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_replied: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_notes: Mapped[Optional[str]] = mapped_column(Text)

    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SupportThread(Base):
    """
    خيط محادثة دعم موحّد - يجمع:
    - رسائل نموذج التواصل (channel='contact')
    - الدردشة الحيّة من الزوّار (channel='chat')
    """
    __tablename__ = "support_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(20), default="contact", index=True)  # contact | chat

    # معلومات الزائر
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    subject: Mapped[Optional[str]] = mapped_column(String(200))

    # token للزائر لاسترجاع المحادثة (للدردشة الحيّة)
    visitor_token: Mapped[str] = mapped_column(String(36), unique=True, index=True)

    # ربط بحساب مستخدم إن كان مسجّلاً
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # حالة
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | closed
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_admin_view_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_visitor_view_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[List["SupportMessage"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", order_by="SupportMessage.created_at"
    )


class SupportMessage(Base):
    """رسالة داخل خيط الدعم - من زائر أو من admin"""
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("support_threads.id", ondelete="CASCADE"), index=True)
    sender: Mapped[str] = mapped_column(String(20), nullable=False)  # visitor | admin
    sender_name: Mapped[Optional[str]] = mapped_column(String(100))  # admin reply: اسم المسؤول
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    thread: Mapped["SupportThread"] = relationship(back_populates="messages")
