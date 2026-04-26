"""
Agents Collab + Manus Edition - Main Server
النسخة المحسّنة بوكيل Manus الحصري + 5 نماذج
"""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.middleware_ratelimit import RateLimitMiddleware

from app.config import settings
from app.database import init_db, close_db
from app.routes_auth import router as auth_router
from app.routes_api_keys import router as api_keys_router
from app.routes_agents import router as agents_router
from app.routes_sessions import router as sessions_router
from app.routes_usage import router as usage_router
from app.routes_chat import router as chat_router
from app.routes_contact import router as contact_router
from app.routes_admin import router as admin_router
from app.routes_billing import router as billing_router
from app.routes_files import router as files_router
from app.routes_code import router as code_router
from app.routes_support import router as support_router
from app.routes_auth_google import router as auth_google_router
from app.routes_billing_lemon import router as billing_lemon_router
from app.routes_images import router as images_router
from app.routes_video import router as video_router
from app.routes_audio import router as audio_router
from app.routes_search import router as search_router
from app.routes_manus_exclusive import router as manus_exclusive_router
from app.routes_manus_tts import router as manus_tts_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """تشغيل عند بدء/إيقاف السيرفر"""
    print(f"🚀 Starting {settings.APP_NAME} v2.1 ({settings.APP_ENV})")
    
    if settings.APP_ENV == "development":
        await init_db()
        print("✅ Database initialized")
    
    # عرض حالة المفاتيح
    print("\n📋 Server API Keys status:")
    for provider in ["anthropic", "openai", "gemini", "deepseek"]:
        has_key = settings.has_server_key(provider)
        status_icon = "✅" if has_key else "⚪"
        print(f"   {status_icon} {provider}: {'configured' if has_key else 'not configured'}")
    
    # Manus exclusive features status
    import os
    forge_key = os.environ.get("BUILT_IN_FORGE_API_KEY", "")
    forge_url = os.environ.get("BUILT_IN_FORGE_API_URL", "")
    forge_icon = "✅" if forge_key else "⚠️"
    print("\n✦ Manus Exclusive Features:")
    print(f"   {forge_icon} Manus Forge API: {'configured' if forge_key else 'not configured'}")
    print("   ✅ Manus Agent (5th model - FREE, no API key needed)")
    print("   ✅ Web Search (DuckDuckGo - no API key needed)")
    print("   ✅ Code Execution (Python sandbox)")
    print("   ✅ Image Generation (Manus Image API - FREE)")
    print("   ✅ Voice TTS (Manus TTS - FREE, no OpenAI key needed)")
    print(f"\n🌐 Server ready at http://{settings.HOST}:{settings.PORT}")
    yield
    
    print("\n👋 Shutting down...")
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    description="منصة تعاون 5 نماذج ذكاء اصطناعي - النسخة المحسّنة بوكيل Manus",
    version="2.1.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)


# Rate limiting
app.add_middleware(RateLimitMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes - Standard (same as Claude version)
app.include_router(auth_router, prefix="/api")
app.include_router(api_keys_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(usage_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(contact_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(code_router, prefix="/api")
app.include_router(support_router, prefix="/api")
app.include_router(auth_google_router, prefix="/api")
app.include_router(billing_lemon_router, prefix="/api")
app.include_router(images_router, prefix="/api")
app.include_router(video_router, prefix="/api")
app.include_router(audio_router, prefix="/api")
app.include_router(search_router, prefix="/api")

# ✦ Manus Exclusive Routes - /api/manus/*
app.include_router(manus_exclusive_router, prefix="/api")
app.include_router(manus_tts_router, prefix="/api")  # /api/manus/tts/*


@app.get("/api/health")
async def health():
    import os
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "2.1.0",
        "edition": "Manus Enhanced",
        "env": settings.APP_ENV,
        "manus_forge": bool(os.environ.get("BUILT_IN_FORGE_API_KEY")),
        "models": 5,
    }


# --- Frontend serving ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"


@app.get("/")
async def root():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return {
        "name": settings.APP_NAME,
        "version": "2.1.0",
        "edition": "Manus Enhanced",
        "docs": "/docs",
    }


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if settings.DEBUG:
        import traceback
        traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) if settings.DEBUG else "Internal server error"},
    )
