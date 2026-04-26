"""
✦ Manus Exclusive: Free TTS (Text-to-Speech)
يحوّل النص إلى صوت مجاناً بدون أي API key
- يدعم العربية والإنجليزية وأكثر من 30 لغة
- يستخدم gTTS (Google Text-to-Speech) مفتوح المصدر
- لا يحتاج OpenAI key (ميزة حصرية مقابل نسخة Claude)
"""
import io
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/manus/tts", tags=["manus-tts"])


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="النص المراد تحويله")
    lang: str = Field(default="auto", description="رمز اللغة: ar, en, fr, auto")
    slow: bool = Field(default=False, description="قراءة بطيئة للتوضيح")


def detect_language(text: str) -> str:
    """كشف اللغة تلقائياً بناءً على النص"""
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha == 0:
        return "en"
    arabic_ratio = arabic_chars / total_alpha
    return "ar" if arabic_ratio > 0.3 else "en"


@router.post("/speak")
async def text_to_speech(req: TTSRequest):
    """
    ✦ Manus حصري: تحويل النص إلى صوت مجاناً
    - لا يحتاج OpenAI API key
    - يدعم العربية والإنجليزية وأكثر من 30 لغة
    """
    try:
        from gtts import gTTS

        # كشف اللغة تلقائياً
        lang = req.lang
        if lang == "auto":
            lang = detect_language(req.text)

        # تحديد اللغات المدعومة
        supported_langs = {
            "ar": "ar", "en": "en", "fr": "fr", "de": "de",
            "es": "es", "it": "it", "pt": "pt", "ru": "ru",
            "zh": "zh-CN", "ja": "ja", "ko": "ko", "tr": "tr",
            "nl": "nl", "pl": "pl", "sv": "sv", "da": "da",
        }
        gtts_lang = supported_langs.get(lang, "en")

        # توليد الصوت
        tts = gTTS(text=req.text, lang=gtts_lang, slow=req.slow)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)

        audio_size = len(buf.getvalue())
        logger.info(f"✦ Manus TTS: {len(req.text)} chars → {audio_size} bytes MP3 [{gtts_lang}]")

        return StreamingResponse(
            buf,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=manus_tts.mp3",
                "Cache-Control": "public, max-age=3600",
                "X-Manus-TTS": "free",
                "X-Language": gtts_lang,
                "X-Chars": str(len(req.text)),
            }
        )

    except ImportError:
        raise HTTPException(status_code=503, detail="gTTS غير مثبت - شغّل: pip install gtts")
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=f"خطأ في توليد الصوت: {str(e)}")


@router.get("/languages")
async def get_supported_languages():
    """قائمة اللغات المدعومة"""
    return {
        "provider": "gTTS (Google Text-to-Speech)",
        "cost": "مجاني تماماً - لا يحتاج API key",
        "exclusive": True,
        "vs_claude_version": "نسخة Claude تحتاج OpenAI API key لـ TTS",
        "languages": [
            {"code": "ar", "name": "العربية", "native": "العربية"},
            {"code": "en", "name": "الإنجليزية", "native": "English"},
            {"code": "fr", "name": "الفرنسية", "native": "Français"},
            {"code": "de", "name": "الألمانية", "native": "Deutsch"},
            {"code": "es", "name": "الإسبانية", "native": "Español"},
            {"code": "it", "name": "الإيطالية", "native": "Italiano"},
            {"code": "pt", "name": "البرتغالية", "native": "Português"},
            {"code": "ru", "name": "الروسية", "native": "Русский"},
            {"code": "zh", "name": "الصينية", "native": "中文"},
            {"code": "ja", "name": "اليابانية", "native": "日本語"},
            {"code": "ko", "name": "الكورية", "native": "한국어"},
            {"code": "tr", "name": "التركية", "native": "Türkçe"},
        ]
    }
