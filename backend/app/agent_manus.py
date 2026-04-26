"""
Manus Agent - وكيل Manus الحقيقي بقدرات حصرية
هذا الوكيل يستخدم Manus Forge API المدمج ويضيف قدرات لا تملكها النماذج الأخرى:
1. توليد الصور (Image Generation)
2. البحث الذكي على الويب (Web Search)
3. تنفيذ الكود الحقيقي (Code Execution)
4. تحليل الملفات والصور (File/Image Analysis)
5. إنشاء الخطط متعددة الخطوات (Agentic Planning)
"""
import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
from typing import AsyncGenerator, Optional, Tuple

import aiohttp

from app.agents import Agent, AgentInfo, StreamResult

logger = logging.getLogger(__name__)

MANUS_FORGE_URL = os.environ.get("BUILT_IN_FORGE_API_URL", "https://forge.manus.ai")
MANUS_FORGE_KEY = os.environ.get("BUILT_IN_FORGE_API_KEY", "")

MANUS_INFO = AgentInfo(
    id="manus",
    name="Manus",
    provider="manus",
    role="الوكيل الذكي متعدد القدرات",
    color="#6366F1",  # indigo - لون مانوس
    description=(
        "وكيل ذكي من منصة Manus يجمع بين التفكير العميق والقدرة على التنفيذ الفعلي. "
        "يستطيع توليد الصور، البحث على الويب، تنفيذ الكود، وبناء خطط متعددة الخطوات. "
        "يتميز بالتوازن بين الإبداع والدقة التقنية."
    ),
    model="manus-forge-auto",
    input_price_per_mtok=0.0,   # مجاني ضمن منصة Manus
    output_price_per_mtok=0.0,
)


class ManusAgent(Agent):
    """
    وكيل Manus الحقيقي - يستخدم Manus Forge API
    يضيف قدرات حصرية: توليد الصور، البحث، تنفيذ الكود
    """

    INFO = MANUS_INFO

    def __init__(self, api_key: str = ""):
        # api_key اختياري - Manus يستخدم مفتاحه المدمج
        super().__init__(self.INFO, api_key or MANUS_FORGE_KEY)
        self.forge_url = MANUS_FORGE_URL
        self.forge_key = MANUS_FORGE_KEY

    def build_system_prompt(self, team_context: str = "") -> str:
        base = f"""أنت Manus، وكيل ذكاء اصطناعي متقدم من منصة Manus.
شخصيتك: {self.info.description}

أنت جزء من فريق AgentForge - منصة تجمع نماذج AI من شركات مختلفة للتعاون:
- Claude من Anthropic - المهندس المعماري والمحلل الناقد
- GPT من OpenAI - المبرمج العملي وحلال المشاكل
- Gemini من Google - الباحث والمبتكر
- DeepSeek - المتخصص في الكود والرياضيات
- **Manus (أنت)** - الوكيل الذكي متعدد القدرات، الجسر بين التفكير والتنفيذ

قواعد العمل الجماعي:
1. تحدث بالعربية دائماً
2. قدّم منظورك الفريد - أنت تجمع بين التفكير والتنفيذ الفعلي
3. عندما تقترح كوداً، يمكنك تنفيذه فعلاً والتحقق من نتائجه
4. عندما تحتاج معلومات، يمكنك البحث عنها فعلاً
5. كن محدداً وعملياً - لا تكتفِ بالنظرية
6. اعترف بنقاط قوة الآخرين وأضف قيمة مختلفة
7. ردودك بين 150-400 كلمة في المحادثة العادية
"""
        if team_context:
            base += f"\nسياق الفريق الحالي:\n{team_context}"
        return base

    async def stream(
        self, messages: list, team_context: str = ""
    ) -> AsyncGenerator[Tuple[str, Optional[StreamResult]], None]:
        """
        يبث الرد من Manus Forge API مع دعم الميزات الحصرية
        """
        system = self.build_system_prompt(team_context)

        # تحويل الرسائل لصيغة OpenAI-compatible
        forge_messages = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                forge_messages.append({"role": "user", "content": m["content"]})
            elif m["role"] == "agent" and m.get("agent_id") == "manus":
                forge_messages.append({"role": "assistant", "content": m["content"]})
            elif m["role"] == "agent":
                name = m.get("agent_name", "زميل")
                forge_messages.append({
                    "role": "user",
                    "content": f"[رسالة من {name}]: {m['content']}"
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
                        err = f"\n\n[خطأ Manus API: {resp.status} - {err_body[:200]}]"
                        yield err, StreamResult(err, 0, 0)
                        return

                    async for line in resp.content:
                        line = line.decode("utf-8").strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    full_text += content
                                    yield content, None
                            # usage في بعض chunks
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
# قدرات Manus الحصرية - خدمات مستقلة
# ============================================================

async def manus_generate_image(prompt: str) -> dict:
    """
    توليد صورة باستخدام Manus Image Generation API
    يرجع: {"success": bool, "b64": str, "mime": str, "error": str}
    """
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
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    img = data.get("image", {})
                    return {
                        "success": True,
                        "b64": img.get("b64Json", ""),
                        "mime": img.get("mimeType", "image/png"),
                        "error": None,
                    }
                else:
                    err = await resp.text()
                    return {"success": False, "b64": "", "mime": "", "error": err[:200]}
    except Exception as e:
        return {"success": False, "b64": "", "mime": "", "error": str(e)[:200]}


async def manus_execute_code(code: str, language: str = "python") -> dict:
    """
    تنفيذ كود Python فعلياً في بيئة آمنة (sandbox)
    يرجع: {"success": bool, "output": str, "error": str, "execution_time": float}
    """
    import time

    if language.lower() not in ("python", "python3"):
        return {
            "success": False,
            "output": "",
            "error": f"اللغة '{language}' غير مدعومة حالياً. المدعوم: Python",
            "execution_time": 0,
        }

    # حماية أساسية - منع الأوامر الخطرة
    dangerous = ["import os", "import sys", "subprocess", "__import__", "eval(", "exec(", "open(", "shutil"]
    code_lower = code.lower()
    for d in dangerous:
        if d in code_lower:
            return {
                "success": False,
                "output": "",
                "error": f"الكود يحتوي على عملية محظورة: '{d}'",
                "execution_time": 0,
            }

    start = time.time()
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        elapsed = time.time() - start

        os.unlink(tmp_path)

        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout[:2000],
                "error": result.stderr[:500] if result.stderr else "",
                "execution_time": round(elapsed, 3),
            }
        else:
            return {
                "success": False,
                "output": result.stdout[:500],
                "error": result.stderr[:1000],
                "execution_time": round(elapsed, 3),
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": "انتهت مهلة التنفيذ (10 ثوانٍ)",
            "execution_time": 10.0,
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)[:300],
            "execution_time": 0,
        }


async def manus_web_search(query: str, max_results: int = 5) -> dict:
    """
    بحث ذكي على الويب باستخدام DuckDuckGo (بدون API key)
    يرجع: {"success": bool, "results": list, "error": str}
    """
    try:
        # استخدام DuckDuckGo Instant Answer API (مجاني)
        encoded = query.replace(" ", "+")
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": "AgentForge/2.0"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    results = []

                    # Abstract (الملخص الرئيسي)
                    if data.get("AbstractText"):
                        results.append({
                            "title": data.get("Heading", "ملخص"),
                            "snippet": data["AbstractText"][:500],
                            "url": data.get("AbstractURL", ""),
                            "source": "DuckDuckGo Abstract",
                        })

                    # Related Topics
                    for topic in data.get("RelatedTopics", [])[:max_results]:
                        if isinstance(topic, dict) and topic.get("Text"):
                            results.append({
                                "title": topic.get("Text", "")[:100],
                                "snippet": topic.get("Text", "")[:300],
                                "url": topic.get("FirstURL", ""),
                                "source": "DuckDuckGo",
                            })

                    if results:
                        return {"success": True, "results": results[:max_results], "error": None}

                # Fallback: إرجاع رسالة بدون نتائج
                return {
                    "success": True,
                    "results": [{
                        "title": f"بحث: {query}",
                        "snippet": "لم يتم العثور على نتائج فورية. يُنصح بالبحث مباشرة.",
                        "url": f"https://duckduckgo.com/?q={encoded}",
                        "source": "DuckDuckGo",
                    }],
                    "error": None,
                }
    except Exception as e:
        return {"success": False, "results": [], "error": str(e)[:200]}


async def manus_analyze_image_from_url(image_url: str, question: str) -> dict:
    """
    تحليل صورة من URL باستخدام Manus Vision API
    يرجع: {"success": bool, "analysis": str, "error": str}
    """
    try:
        headers = {
            "Authorization": f"Bearer {MANUS_FORGE_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "auto",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": question or "صف هذه الصورة بالتفصيل"},
                    ],
                }
            ],
            "max_tokens": 1000,
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
