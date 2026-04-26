"""
Manus Exclusive Features Routes
ميزات حصرية لا تتوفر في نسخة Claude:
1. POST /api/manus/generate-image  - توليد صور بالذكاء الاصطناعي
2. POST /api/manus/execute-code    - تنفيذ كود Python فعلياً
3. POST /api/manus/web-search      - بحث ذكي على الويب
4. POST /api/manus/analyze-image   - تحليل صورة من URL
5. GET  /api/manus/capabilities    - قائمة القدرات المتاحة
"""
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manus", tags=["manus-exclusive"])


# ============== Schemas ==============

class ImageGenRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)


class CodeExecRequest(BaseModel):
    code: str = Field(min_length=1, max_length=5000)
    language: str = Field(default="python")


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)


class ImageAnalyzeRequest(BaseModel):
    image_url: str = Field(min_length=10)
    question: Optional[str] = Field(default="صف هذه الصورة بالتفصيل", max_length=500)


# ============== Endpoints ==============

@router.get("/capabilities")
async def get_manus_capabilities():
    """
    قائمة القدرات الحصرية لـ Manus في هذه النسخة
    """
    import os
    forge_key = os.environ.get("BUILT_IN_FORGE_API_KEY", "")
    forge_available = bool(forge_key)

    return {
        "manus_version": "2.0-exclusive",
        "forge_api_available": forge_available,
        "capabilities": [
            {
                "id": "image_generation",
                "name": "توليد الصور",
                "description": "توليد صور بالذكاء الاصطناعي من وصف نصي",
                "available": forge_available,
                "exclusive": True,
                "endpoint": "/api/manus/generate-image",
            },
            {
                "id": "code_execution",
                "name": "تنفيذ الكود",
                "description": "تنفيذ كود Python فعلياً والحصول على النتائج",
                "available": True,
                "exclusive": True,
                "endpoint": "/api/manus/execute-code",
            },
            {
                "id": "web_search",
                "name": "البحث على الويب",
                "description": "بحث ذكي على الإنترنت وإرجاع النتائج",
                "available": True,
                "exclusive": True,
                "endpoint": "/api/manus/web-search",
            },
            {
                "id": "image_analysis",
                "name": "تحليل الصور",
                "description": "تحليل صورة من URL والإجابة على أسئلة عنها",
                "available": forge_available,
                "exclusive": True,
                "endpoint": "/api/manus/analyze-image",
            },
            {
                "id": "multi_model_chat",
                "name": "محادثة 5 نماذج",
                "description": "Claude + GPT + Gemini + DeepSeek + Manus في نفس المحادثة",
                "available": True,
                "exclusive": True,
                "endpoint": "/api/chat/ws/{session_id}",
            },
        ],
        "vs_claude_version": {
            "models_count": 5,
            "claude_version_models": 4,
            "extra_model": "Manus (مجاني، لا يحتاج API key)",
            "exclusive_features": ["توليد الصور", "تنفيذ الكود", "البحث على الويب", "تحليل الصور"],
        },
    }


@router.post("/generate-image")
async def generate_image(
    req: ImageGenRequest,
    user: User = Depends(get_current_user),
):
    """
    توليد صورة باستخدام Manus Image Generation API
    ميزة حصرية - غير متوفرة في نسخة Claude
    """
    from app.agent_manus import manus_generate_image

    logger.info(f"Image generation request from user {user.id}: {req.prompt[:50]}")

    result = await manus_generate_image(req.prompt)

    if not result["success"]:
        raise HTTPException(
            status_code=503,
            detail=f"فشل توليد الصورة: {result['error']}",
        )

    return {
        "success": True,
        "prompt": req.prompt,
        "image_b64": result["b64"],
        "mime_type": result["mime"],
        "data_url": f"data:{result['mime']};base64,{result['b64']}",
    }


@router.post("/execute-code")
async def execute_code(
    req: CodeExecRequest,
    user: User = Depends(get_current_user),
):
    """
    تنفيذ كود Python فعلياً في بيئة آمنة
    ميزة حصرية - غير متوفرة في نسخة Claude
    """
    from app.agent_manus import manus_execute_code

    logger.info(f"Code execution request from user {user.id}, language: {req.language}")

    result = await manus_execute_code(req.code, req.language)

    return {
        "success": result["success"],
        "language": req.language,
        "output": result["output"],
        "error": result["error"],
        "execution_time_seconds": result["execution_time"],
    }


@router.post("/web-search")
async def web_search(
    req: WebSearchRequest,
    user: User = Depends(get_current_user),
):
    """
    بحث ذكي على الويب
    ميزة حصرية - غير متوفرة في نسخة Claude
    """
    from app.agent_manus import manus_web_search

    logger.info(f"Web search request from user {user.id}: {req.query[:50]}")

    result = await manus_web_search(req.query, req.max_results)

    if not result["success"]:
        raise HTTPException(
            status_code=503,
            detail=f"فشل البحث: {result['error']}",
        )

    return {
        "success": True,
        "query": req.query,
        "results": result["results"],
        "count": len(result["results"]),
    }


@router.post("/analyze-image")
async def analyze_image(
    req: ImageAnalyzeRequest,
    user: User = Depends(get_current_user),
):
    """
    تحليل صورة من URL باستخدام Manus Vision
    ميزة حصرية - غير متوفرة في نسخة Claude
    """
    from app.agent_manus import manus_analyze_image_from_url

    logger.info(f"Image analysis request from user {user.id}")

    result = await manus_analyze_image_from_url(req.image_url, req.question)

    if not result["success"]:
        raise HTTPException(
            status_code=503,
            detail=f"فشل تحليل الصورة: {result['error']}",
        )

    return {
        "success": True,
        "image_url": req.image_url,
        "question": req.question,
        "analysis": result["analysis"],
    }
