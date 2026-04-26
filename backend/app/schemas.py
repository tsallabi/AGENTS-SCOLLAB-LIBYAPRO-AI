"""
Pydantic Schemas - validation و serialization للـ API
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from app.models import PlanType, SubscriptionStatus, ConversationMode, MessageRole


# ============== Auth ==============

class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    full_name: Optional[str] = Field(default=None, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    email: str
    full_name: Optional[str]
    is_active: bool
    is_admin: bool
    is_verified: bool
    plan: PlanType
    created_at: datetime


# ============== API Keys ==============

class ApiKeyCreate(BaseModel):
    provider: str = Field(pattern="^(anthropic|openai|gemini|deepseek)$")
    key: str = Field(min_length=10, max_length=500)


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    provider: str
    masked_key: str  # sk-•••••...abc
    is_valid: bool
    last_used_at: Optional[datetime]
    usage_count: int
    created_at: datetime


# ============== Agents ==============

class AgentInfoResponse(BaseModel):
    id: str
    name: str
    provider: str
    role: str
    color: str
    description: str
    model: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    
    # هل المستخدم يستطيع استخدامه الآن؟
    available: bool
    available_reason: Optional[str] = None  # "user_key" or "server_key" or None


# ============== Sessions ==============

class SessionCreate(BaseModel):
    title: Optional[str] = Field(default="محادثة جديدة", max_length=200)
    default_mode: ConversationMode = ConversationMode.ROUND_ROBIN
    default_agents: List[str] = Field(default_factory=list)


class SessionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    default_mode: Optional[ConversationMode] = None
    default_agents: Optional[List[str]] = None
    is_archived: Optional[bool] = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    title: str
    default_mode: ConversationMode
    default_agents: List[str]
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


# ============== Messages ==============

class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    role: MessageRole
    agent_id: Optional[str]
    agent_name: Optional[str]
    content: str
    mode: Optional[ConversationMode]
    phase: Optional[str]
    created_at: datetime


# ============== Subscriptions ==============

class CheckoutSessionCreate(BaseModel):
    plan: PlanType


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    plan: PlanType
    status: SubscriptionStatus
    current_period_end: datetime
    cancel_at_period_end: bool


# ============== Usage ==============

class UsageStats(BaseModel):
    period_start: datetime
    period_end: datetime
    total_messages: int
    limit: int
    remaining: int
    by_agent: dict[str, int]  # {"claude": 10, "gpt": 5}
    total_cost_usd: float


# ============== Admin ==============

class AdminStats(BaseModel):
    total_users: int
    active_users_30d: int
    paid_users: int
    total_revenue_mrr: float  # Monthly Recurring Revenue
    total_messages: int
    total_cost_usd: float
    by_plan: dict[str, int]
    by_agent: dict[str, int]


# Forward refs
TokenResponse.model_rebuild()
