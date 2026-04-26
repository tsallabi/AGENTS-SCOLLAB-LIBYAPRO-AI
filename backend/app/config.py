"""
إعدادات التطبيق المركزية
كل الإعدادات تُقرأ من .env بطريقة type-safe
"""
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # --- App ---
    APP_NAME: str = "AgentForge"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production"
    
    # --- JWT ---
    JWT_SECRET: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080  # 7 days
    
    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:5173"
    
    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./agentforge.db"
    
    # --- AI Provider Keys (server-side, للخطة المدفوعة) ---
    SERVER_ANTHROPIC_KEY: Optional[str] = None
    SERVER_OPENAI_KEY: Optional[str] = None
    SERVER_GEMINI_KEY: Optional[str] = None
    SERVER_DEEPSEEK_KEY: Optional[str] = None
    
    # --- Stripe ---
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_ID_BASIC: Optional[str] = None
    STRIPE_PRICE_ID_PRO: Optional[str] = None

    # --- Lemon Squeezy (بديل Stripe لليبيا والعالم العربي) ---
    LEMON_API_KEY: Optional[str] = None
    LEMON_STORE_ID: Optional[str] = None
    LEMON_VARIANT_BASIC: Optional[str] = None
    LEMON_VARIANT_PRO: Optional[str] = None
    LEMON_VARIANT_BUSINESS: Optional[str] = None
    LEMON_WEBHOOK_SECRET: Optional[str] = None
    
    # --- Plan Limits ---
    PLAN_FREE_MESSAGES_PER_MONTH: int = 50
    PLAN_BASIC_MESSAGES_PER_MONTH: int = 200
    PLAN_PRO_MESSAGES_PER_MONTH: int = 1000

    # --- Exchange rate (Central Bank of Libya) ---
    # سعر الصرف الرسمي المعتمد من مصرف ليبيا المركزي - cbl.gov.ly
    # حدّث هذه القيمة شهرياً أو عند تغيّر السعر الرسمي
    LYD_PER_USD: float = 6.50
    EXCHANGE_RATE_SOURCE: str = "مصرف ليبيا المركزي · cbl.gov.ly"
    
    # --- Admin ---
    ADMIN_EMAIL: str = "admin@agentforge.com"

    # --- Google OAuth (مشترك مع Macchina) ---
    GOOGLE_OAUTH2_KEY: Optional[str] = None
    GOOGLE_OAUTH2_SECRET: Optional[str] = None
    # callback URL - يجب أن يكون مُسجَّلاً في Google Cloud Console
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    
    @property
    def cors_origins(self) -> List[str]:
        return [
            self.FRONTEND_URL,
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"
    
    def has_server_key(self, provider: str) -> bool:
        """هل لدينا مفتاح سيرفر لهذا النموذج؟"""
        keys = {
            "anthropic": self.SERVER_ANTHROPIC_KEY,
            "openai": self.SERVER_OPENAI_KEY,
            "gemini": self.SERVER_GEMINI_KEY,
            "deepseek": self.SERVER_DEEPSEEK_KEY,
        }
        key = keys.get(provider, "")
        return bool(key) and len(key.strip()) > 10


# Singleton instance
settings = Settings()
