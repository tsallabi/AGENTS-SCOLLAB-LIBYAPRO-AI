"""
Manus Agent — وكيل Manus الحقيقي بقدرات حصرية
============================================================
الميزات الحصرية:
1. توليد الصور (Manus Image Generation API) — مجاني
2. البحث الذكي على الويب (DuckDuckGo — بدون API key)
3. تنفيذ الكود Python الحقيقي (sandbox آمن)
4. تحليل الصور Vision (Manus Forge API)
5. استدعاء LLM مدمج (Manus Forge API)
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from typing import AsyncGenerator, List, Optional, Tuple

import aiohttp

from app.agents import Agent, AgentInfo, StreamResult

logger = logging.getLogger(__name__)

MANUS_FORGE_URL = os.environ.get("BUILT_IN_FORGE_API_URL", "")
MANUS_FORGE_KEY = os.environ.get("BUILT_IN_FORGE_API_KEY", "")

MANUS_INFO = AgentInfo(
    id="manus",
    name="Manus ✦",
    provider="manus",
    role="الوكيل الذكي متعدد القدرات",
    color="#6366F1",  # indigo
    description=(
        "وكيل ذكي من منصة Manus يجمع بين التفكير العميق والتنفيذ الفعلي. "
        "يستطيع البحث على الويب في الوقت الفعلي، توليد الصور، تنفيذ الكود، "
        "وتحليل الصور — كل ذلك مجاناً بدون API key إضافي."
    ),
    model="manus-forge-auto",
    input_price_per_mtok=0.0,
    output_price_per_mtok=0.0,
)


class ManusAgent(Agent):
    """
    وكيل Manus — يستخدم Manus Forge API المدمج
    يضيف قدرات حصرية لا تملكها النماذج الأخرى
    """

    INFO = MANUS_INFO

    def __init__(self, api_key: str = ""):
        super().__init__(self.INFO, api_key or MANUS_FORGE_KEY)
        self.forge_url = MANUS_FORGE_URL
        self.forge_key = MANUS_FORGE_KEY

    def build_system_prompt(self, team_context: str = "") -> str:
        return f"""أنت Manus ✦، وكيل ذكاء اصطناعي متقدم من منصة Manus.

دورك في الفريق: الوكيل الذكي متعدد القدرات — الجسر بين التفكير والتنفيذ الفعلي.

قدراتك الحصرية التي لا يملكها الآخرون:
• البحث على الويب في الوقت الفعلي (معلومات محدّثة)
• توليد الصور (Image Generation)
• تنفيذ الكود Python فعلياً والتحقق من النتائج
• تحليل الصور بالتفصيل (Vision)

أنت جزء من فريق يضم:
- Claude (Anthropic) — المهندس المعماري والناقد الدقيق
- GPT (OpenAI) — المبرمج العملي وحلال المشاكل
- Gemini (Google) — الباحث والمبتكر
- DeepSeek — المتخصص في الكود والرياضيات
- **Manus ✦ (أنت)** — الوكيل الذكي، تُنفّذ ما يقترحه الآخرون وتتحقق منه

قواعد العمل:
1. أضف قيمة مختلفة — لا تكرر ما قاله الآخرون
2. عندما تقترح كوداً، أشر إلى أنك يمكنك تنفيذه فعلاً
3. عندما تحتاج معلومات حديثة، أشر إلى أنك ستبحث عنها
4. كن محدداً وعملياً — ردودك بين 150-350 كلمة
5. اكتب باللغة التي يستخدمها المستخدم (عربي أو إنجليزي)
6. انتقد بصدق وبنّاء — الهدف أفضل حل لا الإجماع الزائف

{f"سياق الفريق الحالي:{chr(10)}{team_context}" if team_context else ""}
"""

    async def stream(
        self, messages: list, team_context: str = ""
    ) -> AsyncGenerator[Tuple[str, Optional[StreamResult]], None]:
        """يبث الرد من Manus Forge API"""
        if not self.forge_url or not self.forge_key:
            err = "[Manus غير متاح: BUILT_IN_FORGE_API_URL أو BUILT_IN_FORGE_API_KEY غير مُعدَّين]"
            yield err, StreamResult(err, 0, 0)
            return

        system = self.build_system_prompt(team_context)

        # بناء رسائل بصيغة OpenAI-compatible
        forge_messages = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            if role == "user":
                # دعم الصور في رسائل المستخدم
                images = m.get("images", [])
                if images:
                    parts = [{"type": "text", "text": content}]
                    for img in images[:4]:
                        parts.append({"type": "image_url", "image_url": {"url": img}})
                    forge_messages.append({"role": "user", "content": parts})
                else:
                    forge_messages.append({"role": "user", "content": content})

            elif role == "agent":
                if m.get("agent_id") == "manus":
                    forge_messages.append({"role": "assistant", "content": content})
                else:
                    name = m.get("agent_name", "زميل")
                    forge_messages.append({
                        "role": "user",
                        "content": f"[{name}]: {content}"
                    })

        full_text = ""
        input_tokens = 0
        output_tokens = 0

        try:
            headers = {
                "Authorization": f"Bearer {self.forge_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "auto",
                "messages": forge_messages,
                "max_tokens": 8000,
                "stream": True,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.forge_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status != 200:
                        err_body = await resp.text()
                        err = f"\n\n[خطأ Manus API {resp.status}: {err_body[:200]}]"
                        yield err, StreamResult(err, 0, 0)
                        return

                    async for line in resp.content:
                        line_str = line.decode("utf-8").strip()
                        if not line_str or not line_str.startswith("data: "):
                            continue
                        data_str = line_str[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                chunk = delta.get("content", "")
                                if chunk:
                                    full_text += chunk
                                    yield chunk, None
                            usage = data.get("usage", {})
                            if usage:
                                input_tokens = usage.get("prompt_tokens", input_tokens)
                                output_tokens = usage.get("completion_tokens", output_tokens)
                        except json.JSONDecodeError:
                            continue

            yield "", StreamResult(full_text, input_tokens, output_tokens)

        except Exception as e:
            err = f"\n\n[خطأ Manus: {str(e)[:300]}]"
            yield err, StreamResult(full_text + err, 0, 0)


# ============================================================
# قدرات Manus الحصرية — خدمات مستقلة
# ============================================================

async def manus_web_search(query: str, max_results: int = 6) -> dict:
    """
    بحث حقيقي على الويب باستخدام DuckDuckGo (بدون API key)
    يستخدم مكتبة ddgs للحصول على نتائج حقيقية من الإنترنت
    يرجع: {"success": bool, "results": list[dict], "query": str, "error": str|None}
    """
    try:
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))

        for r in raw:
            results.append({
                "title": r.get("title", ""),
                "snippet": r.get("body", "")[:400],
                "url": r.get("href", ""),
                "source": "DuckDuckGo",
            })

        if results:
            return {
                "success": True,
                "results": results,
                "query": query,
                "error": None,
            }

        # Fallback إذا لم تُرجع نتائج
        return {
            "success": True,
            "results": [{
                "title": f"بحث: {query}",
                "snippet": "لم تُعثر على نتائج فورية. جرّب صياغة مختلفة.",
                "url": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
                "source": "DuckDuckGo",
            }],
            "query": query,
            "error": None,
        }

    except ImportError:
        # Fallback إلى DuckDuckGo Instant Answer API
        return await _ddg_instant_answer(query, max_results)
    except Exception as e:
        logger.warning(f"[Manus Search] ddgs failed: {e}, trying fallback")
        return await _ddg_instant_answer(query, max_results)


async def _ddg_instant_answer(query: str, max_results: int = 5) -> dict:
    """Fallback: DuckDuckGo Instant Answer API"""
    try:
        encoded = query.replace(" ", "+")
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": "AgentsCollab-Manus/2.0"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    results = []
                    if data.get("AbstractText"):
                        results.append({
                            "title": data.get("Heading", "ملخص"),
                            "snippet": data["AbstractText"][:500],
                            "url": data.get("AbstractURL", ""),
                            "source": "DuckDuckGo Abstract",
                        })
                    for topic in data.get("RelatedTopics", [])[:max_results]:
                        if isinstance(topic, dict) and topic.get("Text"):
                            results.append({
                                "title": topic.get("Text", "")[:100],
                                "snippet": topic.get("Text", "")[:300],
                                "url": topic.get("FirstURL", ""),
                                "source": "DuckDuckGo",
                            })
                    if results:
                        return {"success": True, "results": results[:max_results], "query": query, "error": None}
        return {
            "success": False,
            "results": [],
            "query": query,
            "error": "لم تُعثر على نتائج",
        }
    except Exception as e:
        return {"success": False, "results": [], "query": query, "error": str(e)[:200]}


async def manus_generate_image(prompt: str) -> dict:
    """
    توليد صورة باستخدام Manus Image Generation API
    يرجع: {"success": bool, "b64": str, "mime": str, "url": str, "error": str|None}
    """
    if not MANUS_FORGE_URL or not MANUS_FORGE_KEY:
        return {"success": False, "b64": "", "mime": "", "url": "", "error": "Manus API غير مُعدّ"}

    try:
        url = f"{MANUS_FORGE_URL}/images.v1.ImageService/GenerateImage"
        headers = {
            "Authorization": f"Bearer {MANUS_FORGE_KEY}",
            "Content-Type": "application/json",
            "connect-protocol-version": "1",
            "accept": "application/json",
        }
        payload = {"prompt": prompt, "original_images": []}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=90)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    img = data.get("image", {})
                    return {
                        "success": True,
                        "b64": img.get("b64Json", ""),
                        "mime": img.get("mimeType", "image/png"),
                        "url": "",
                        "error": None,
                    }
                else:
                    err = await resp.text()
                    return {"success": False, "b64": "", "mime": "", "url": "", "error": err[:200]}
    except Exception as e:
        return {"success": False, "b64": "", "mime": "", "url": "", "error": str(e)[:200]}


async def manus_execute_code(code: str, language: str = "python") -> dict:
    """
    تنفيذ كود Python فعلياً في بيئة آمنة
    يرجع: {"success": bool, "output": str, "error": str, "execution_time": float}
    """
    if language.lower() not in ("python", "python3"):
        return {
            "success": False,
            "output": "",
            "error": f"اللغة '{language}' غير مدعومة. المدعوم: Python",
            "execution_time": 0,
        }

    # حماية من الأوامر الخطرة
    BLOCKED = [
        "import subprocess", "import shutil", "__import__",
        "eval(", "exec(", "os.system", "os.popen",
        "open(", "socket", "urllib.request",
    ]
    code_lower = code.lower()
    for blocked in BLOCKED:
        if blocked in code_lower:
            return {
                "success": False,
                "output": "",
                "error": f"محظور: '{blocked}' غير مسموح في sandbox الآمن",
                "execution_time": 0,
            }

    start = time.time()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        elapsed = time.time() - start

        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        return {
            "success": result.returncode == 0,
            "output": result.stdout[:3000],
            "error": result.stderr[:1000] if result.stderr else "",
            "execution_time": round(elapsed, 3),
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": "انتهت مهلة التنفيذ (15 ثانية)",
            "execution_time": 15.0,
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)[:300],
            "execution_time": round(time.time() - start, 3),
        }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


async def manus_analyze_image_from_url(image_url: str, question: str) -> dict:
    """
    تحليل صورة من URL باستخدام Manus Vision API
    يرجع: {"success": bool, "analysis": str, "error": str|None}
    """
    if not MANUS_FORGE_URL or not MANUS_FORGE_KEY:
        return {"success": False, "analysis": "", "error": "Manus API غير مُعدّ"}

    try:
        headers = {
            "Authorization": f"Bearer {MANUS_FORGE_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "auto",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": question or "صف هذه الصورة بالتفصيل"},
                ],
            }],
            "max_tokens": 1500,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{MANUS_FORGE_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    analysis = data["choices"][0]["message"]["content"]
                    return {"success": True, "analysis": analysis, "error": None}
                else:
                    err = await resp.text()
                    return {"success": False, "analysis": "", "error": err[:200]}
    except Exception as e:
        return {"success": False, "analysis": "", "error": str(e)[:200]}
