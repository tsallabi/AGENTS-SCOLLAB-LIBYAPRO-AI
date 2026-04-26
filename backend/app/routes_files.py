"""
Files Routes - رفع وتنزيل الملفات (للـ Cowork mode)

مكان التخزين: BACKEND_DIR/uploads/{user_id}/{file_id}_{filename}
الحماية: حد أقصى 10MB لكل ملف، مصادقة لكل عملية، تنظيف اسم الملف.
"""
import os
import uuid
import re
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FileParam, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import (
    Integer, String, DateTime, ForeignKey, BigInteger, select, desc
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import get_db
from app.deps import get_current_user
from app.models import Base, User


# ============== Model (in this module to keep self-contained) ==============

class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    file_uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ============== Constants ==============

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
MAX_SIZE = 10 * 1024 * 1024  # 10MB

ALLOWED_MIME_PREFIXES = (
    "text/", "image/", "application/pdf", "application/json",
    "application/zip", "application/x-zip-compressed",
)

UNSAFE_RE = re.compile(r"[^A-Za-z0-9._\-؀-ۿ]")


def sanitize_filename(name: str) -> str:
    base = name.split("/")[-1].split("\\")[-1]
    base = UNSAFE_RE.sub("_", base)
    if not base or base in (".", ".."):
        base = "file"
    return base[:200]


router = APIRouter(prefix="/files", tags=["files"])


# ============== Endpoints ==============

def _extract_text_from_pdf(content: bytes, max_chars: int = 50_000) -> str:
    """يستخرج نص من PDF. يحتاج: pip install pypdf"""
    try:
        from pypdf import PdfReader
        from io import BytesIO
        reader = PdfReader(BytesIO(content))
        text_parts = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            total += len(page_text)
            if total > max_chars:
                break
        return "\n\n".join(text_parts)[:max_chars]
    except ImportError:
        return "[pypdf غير مثبّت - شغّل: pip install pypdf]"
    except Exception as e:
        return f"[فشل استخراج النص: {str(e)[:100]}]"


def _extract_text_from_txt(content: bytes, max_chars: int = 50_000) -> str:
    try:
        return content.decode("utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


@router.post("")
async def upload_file(
    file: UploadFile = FileParam(...),
    session_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """رفع ملف + استخراج النص من PDFs/text تلقائياً."""
    # تحقق MIME
    mime = file.content_type or "application/octet-stream"
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail=f"نوع غير مدعوم: {mime}")

    # اقرأ مع تحقق الحجم
    content = await file.read(MAX_SIZE + 1)
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=413, detail=f"الحجم > {MAX_SIZE // (1024*1024)}MB"
        )

    file_uuid = uuid.uuid4().hex
    safe_name = sanitize_filename(file.filename or "upload")
    user_dir = UPLOADS_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{file_uuid}_{safe_name}"
    storage_path = user_dir / storage_name

    with open(storage_path, "wb") as f:
        f.write(content)

    record = UploadedFile(
        user_id=user.id,
        session_id=session_id,
        file_uuid=file_uuid,
        original_name=safe_name,
        mime_type=mime,
        size_bytes=len(content),
        storage_path=str(storage_path),
    )
    db.add(record)
    await db.flush()

    # استخرج النص لو PDF أو نص
    extracted_text = None
    if mime == "application/pdf":
        extracted_text = _extract_text_from_pdf(content)
    elif mime.startswith("text/"):
        extracted_text = _extract_text_from_txt(content)
    elif mime == "application/json":
        extracted_text = _extract_text_from_txt(content)

    return {
        "id": record.id,
        "file_uuid": file_uuid,
        "name": safe_name,
        "mime_type": mime,
        "size_bytes": len(content),
        "session_id": session_id,
        "url": f"/api/files/{file_uuid}",
        "extracted_text": extracted_text,
        "extracted_chars": len(extracted_text) if extracted_text else 0,
    }


@router.get("/{file_uuid}/text")
async def get_file_text(
    file_uuid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """يستخرج النص من ملف موجود (لإعادة المعالجة)."""
    result = await db.execute(
        select(UploadedFile).where(UploadedFile.file_uuid == file_uuid)
    )
    rec = result.scalar_one_or_none()
    if not rec or rec.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    if not os.path.exists(rec.storage_path):
        raise HTTPException(status_code=410, detail="File missing on disk")

    with open(rec.storage_path, "rb") as f:
        content = f.read()

    text = None
    if rec.mime_type == "application/pdf":
        text = _extract_text_from_pdf(content)
    elif rec.mime_type.startswith("text/") or rec.mime_type == "application/json":
        text = _extract_text_from_txt(content)
    else:
        raise HTTPException(status_code=415, detail="نوع لا يدعم استخراج النص")

    return {"file_uuid": file_uuid, "name": rec.original_name, "text": text, "chars": len(text or "")}


@router.get("")
async def list_files(
    session_id: Optional[int] = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """قائمة ملفات المستخدم (اختيارياً مفلترة بـ session)"""
    q = select(UploadedFile).where(UploadedFile.user_id == user.id).order_by(desc(UploadedFile.created_at))
    if session_id is not None:
        q = q.where(UploadedFile.session_id == session_id)
    result = await db.execute(q.limit(200))
    return [
        {
            "id": f.id,
            "file_uuid": f.file_uuid,
            "name": f.original_name,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "session_id": f.session_id,
            "created_at": f.created_at.isoformat(),
            "url": f"/api/files/{f.file_uuid}",
        }
        for f in result.scalars().all()
    ]


@router.get("/{file_uuid}")
async def download_file(
    file_uuid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """تنزيل ملف (يتحقق من ملكيته)"""
    result = await db.execute(
        select(UploadedFile).where(UploadedFile.file_uuid == file_uuid)
    )
    rec = result.scalar_one_or_none()
    if not rec or rec.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    if not os.path.exists(rec.storage_path):
        raise HTTPException(status_code=410, detail="File missing on disk")
    return FileResponse(
        rec.storage_path,
        media_type=rec.mime_type,
        filename=rec.original_name,
    )


@router.delete("/{file_uuid}", status_code=204)
async def delete_file(
    file_uuid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """حذف ملف"""
    result = await db.execute(
        select(UploadedFile).where(UploadedFile.file_uuid == file_uuid)
    )
    rec = result.scalar_one_or_none()
    if not rec or rec.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        os.remove(rec.storage_path)
    except OSError:
        pass
    await db.delete(rec)
    return Response(status_code=204)
