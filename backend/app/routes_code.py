"""
Code Execution Routes - تنفيذ كود في sandbox

⚠️ تحذير أمني:
هذا التنفيذ يستخدم subprocess مع timeout فقط - مناسب لتنفيذ كود يكتبه المستخدم
لنفسه (نموذج الاستخدام الحالي). ليس آمناً تماماً ضد كود خبيث محترف.

للـ Production مع كود مستخدمين غير موثوقين:
- استخدم Docker container منفصل لكل تنفيذ
- أو خدمة مثل Judge0 / Piston / Firecracker microVMs
- أو عيّن user منفصل بصلاحيات محدودة (chroot)
- شدّد resource limits عبر cgroups

Currently supported:
- Python (يستخدم python -c)
- JavaScript (Node.js إذا متوفر)
- HTML/CSS preview (يُرجع كما هو، الـ frontend يعرضه في iframe sandboxed)
"""
import asyncio
import os
import shutil
import sys
import tempfile
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.models import User


router = APIRouter(prefix="/code", tags=["code"])


# ============== Request/Response ==============

class ExecuteRequest(BaseModel):
    language: str = Field(pattern="^(python|javascript|html)$")
    code: str = Field(min_length=1, max_length=50_000)
    stdin: Optional[str] = Field(default=None, max_length=10_000)


class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    runtime_ms: int


# ============== Configuration ==============

EXEC_TIMEOUT_SECONDS = 8
MAX_OUTPUT = 100_000  # 100KB

# نتحقق من أن node متوفر
NODE_PATH = shutil.which("node")
PYTHON_PATH = sys.executable


async def _run_subprocess(
    cmd: list, code: str, stdin: Optional[str] = None
) -> dict:
    """يشغّل subprocess مع timeout ويُرجع stdout/stderr"""
    import time
    start = time.time()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # على Linux/Mac يمكن إضافة preexec_fn=set_resource_limits
    )

    timed_out = False
    try:
        input_data = (code + "\n" + (stdin or "")).encode("utf-8")
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=input_data if cmd[-1] == "-" else None),
            timeout=EXEC_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        stdout, stderr = b"", b"[Timeout - execution exceeded limit]"

    runtime_ms = int((time.time() - start) * 1000)
    return {
        "stdout": stdout[:MAX_OUTPUT].decode("utf-8", errors="replace"),
        "stderr": stderr[:MAX_OUTPUT].decode("utf-8", errors="replace"),
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "timed_out": timed_out,
        "runtime_ms": runtime_ms,
    }


@router.post("/execute", response_model=ExecuteResponse)
async def execute_code(
    payload: ExecuteRequest,
    user: User = Depends(get_current_user),
):
    """ينفّذ كود وي أعطي النتيجة. timeout = 8s."""
    if payload.language == "html":
        # HTML لا يُنفّذ - الـ frontend يعرضه في iframe sandboxed
        return ExecuteResponse(
            stdout=payload.code,
            stderr="",
            exit_code=0,
            timed_out=False,
            runtime_ms=0,
        )

    # احفظ الكود في ملف مؤقت لتجنب مشاكل stdin
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        suffix=".py" if payload.language == "python" else ".js"
    )
    tmp.write(payload.code)
    tmp.close()

    try:
        if payload.language == "python":
            cmd = [PYTHON_PATH, "-I", tmp.name]  # -I = isolated mode
        elif payload.language == "javascript":
            if not NODE_PATH:
                raise HTTPException(status_code=503, detail="Node.js غير مثبّت على السيرفر")
            cmd = [NODE_PATH, tmp.name]
        else:
            raise HTTPException(status_code=400, detail="Unsupported language")

        result = await _run_subprocess(cmd, payload.code, payload.stdin)
        return ExecuteResponse(**result)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.get("/info")
async def runtime_info():
    """معلومات عن البيئات المتاحة"""
    return {
        "python": {
            "available": True,
            "version": sys.version.split()[0],
        },
        "javascript": {
            "available": bool(NODE_PATH),
            "version": None,  # placeholder
        },
        "html": {"available": True},
        "timeout_seconds": EXEC_TIMEOUT_SECONDS,
        "max_output_bytes": MAX_OUTPUT,
        "warning": (
            "هذا sandbox أساسي (subprocess + timeout). للإنتاج مع كود مستخدمين "
            "غير موثوقين استخدم Docker isolation أو خدمة مثل Judge0/Piston."
        ),
    }
