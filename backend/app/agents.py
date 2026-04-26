"""
AI Agents - 5 نماذج (نسخة Manus):
- Claude (Anthropic)
- GPT (OpenAI)
- Gemini (Google)
- DeepSeek
- Manus (مدمج - مجاني)

كل agent يعرف:
- كيف يبث ردود (streaming)
- كم يكلف الاستخدام
- ما هو دوره في الفريق

البنية قابلة للتوسع: لإضافة نموذج جديد، أنشئ كلاس يرث Agent.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, List, Dict, Optional, Tuple

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from google import genai as google_genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


# Retry helper - يُعيد المحاولة عند فشل API مؤقت
async def _retry_async(coro_factory, *, max_retries: int = 2, base_delay: float = 1.0):
    """يستدعي coro_factory() ويُعيد المحاولة عند failures عابرة"""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            # Don't retry on auth/quota/rate-limit errors - they need user action
            if any(s in err_str for s in ['401', '403', '429', 'quota', 'invalid', 'permission', 'leaked']):
                raise
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"API attempt {attempt+1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                raise
    if last_exc:
        raise last_exc


@dataclass
class AgentInfo:
    """معلومات عرض agent للواجهة"""
    id: str
    name: str
    provider: str  # anthropic, openai, gemini, deepseek
    role: str
    color: str
    description: str
    model: str
    
    # تكلفة لكل مليون token (USD)
    input_price_per_mtok: float
    output_price_per_mtok: float


@dataclass
class StreamResult:
    """نتيجة streaming"""
    full_text: str
    input_tokens: int = 0
    output_tokens: int = 0
    
    @property
    def cost_usd(self) -> float:
        # سيُحسب من خارج الكلاس بناء على الأسعار
        return 0.0


class Agent(ABC):
    """الكلاس الأساسي لكل agent"""
    
    def __init__(self, info: AgentInfo, api_key: str):
        self.info = info
        self.api_key = api_key
    
    def build_system_prompt(self, team_context: str = "") -> str:
        """يبني system prompt يشرح للنموذج دوره وقواعد الفريق"""
        return f"""أنت {self.info.name}، {self.info.role}.

شخصيتك: {self.info.description}

أنت جزء من فريق AgentForge - منصة تجمع نماذج AI من شركات مختلفة للتعاون:
- Claude من Anthropic - المهندس المعماري والمحلل الناقد
- GPT من OpenAI - المبرمج العملي وحلال المشاكل
- Gemini من Google - الباحث والمبتكر
- DeepSeek - المتخصص في الكود والرياضيات

قواعد العمل:
1. عند قراءة رد زميل، انتقده بصدق - أشر للأخطاء والتحسينات
2. لا تجامل - الهدف هو أفضل حل، ليس إرضاء الزملاء
3. استخدم "أتفق مع X في..." أو "أختلف مع X لأن..." بوضوح
4. كن مختصراً - اكتب فقط ما يضيف قيمة جديدة
5. عند طلب كود، اكتبه فعلياً وقابلاً للتشغيل
6. ركز على دورك الأساسي ولا تكرر ما قاله الآخرون

{team_context}

اكتب باللغة التي يكتب بها المستخدم.
"""
    
    @abstractmethod
    async def stream(
        self,
        messages: List[Dict],
        team_context: str = "",
    ) -> AsyncGenerator[Tuple[str, Optional[StreamResult]], None]:
        """
        يبث الرد. ينتج tuple:
        - chunk: نص جزئي
        - result: None خلال الـ streaming، StreamResult في النهاية

        Multimodal: messages قد تحتوي على 'images' (list of base64 data URLs أو URLs)
        مثال: {"role": "user", "content": "ما في هذه الصورة؟", "images": ["data:image/png;base64,..."]}
        """
        ...
    
    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """حساب التكلفة بالدولار"""
        in_cost = (input_tokens / 1_000_000) * self.info.input_price_per_mtok
        out_cost = (output_tokens / 1_000_000) * self.info.output_price_per_mtok
        return round(in_cost + out_cost, 6)


# ============== Claude (Anthropic) ==============

class ClaudeAgent(Agent):
    INFO = AgentInfo(
        id="claude",
        name="Claude",
        provider="anthropic",
        role="المهندس المعماري والمحلل الناقد",
        color="#D97706",
        description="تحليلي، دقيق، ينتبه للتفاصيل والمخاطر، يفكر في البنية الكلية قبل التفاصيل",
        model="claude-sonnet-4-6",
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
    )
    
    def __init__(self, api_key: str):
        super().__init__(self.INFO, api_key)
        self.client = AsyncAnthropic(api_key=api_key)
    
    async def stream(self, messages, team_context=""):
        system = self.build_system_prompt(team_context)

        # تحويل لصيغة Anthropic مع دعم الصور (multimodal)
        anthropic_msgs = []
        for m in messages:
            role = "user"
            content_text = m["content"]

            if m["role"] == "agent" and m.get("agent_id") == "claude":
                role = "assistant"
            elif m["role"] == "agent":
                role = "user"
                content_text = f"[رسالة من {m.get('agent_name', 'زميل')}]: {content_text}"

            # بناء content - إذا فيه صور، نستخدم list of blocks
            images = m.get("images") or []
            if images and role == "user":
                blocks = []
                for img in images:
                    # دعم data URLs (data:image/png;base64,xxx) أو URLs خارجية
                    if isinstance(img, str) and img.startswith("data:"):
                        try:
                            header, b64 = img.split(",", 1)
                            mime = header.split(":")[1].split(";")[0] or "image/png"
                            blocks.append({
                                "type": "image",
                                "source": {"type": "base64", "media_type": mime, "data": b64},
                            })
                        except Exception:
                            pass
                    elif isinstance(img, str):
                        blocks.append({
                            "type": "image",
                            "source": {"type": "url", "url": img},
                        })
                if content_text:
                    blocks.append({"type": "text", "text": content_text})
                content_for_role = blocks
            else:
                content_for_role = content_text

            # دمج رسائل user متتالية (فقط إذا الاثنان نص)
            if (anthropic_msgs and anthropic_msgs[-1]["role"] == role
                    and isinstance(anthropic_msgs[-1]["content"], str)
                    and isinstance(content_for_role, str)):
                anthropic_msgs[-1]["content"] += "\n\n" + content_for_role
            else:
                anthropic_msgs.append({"role": role, "content": content_for_role})
        
        full_text = ""
        input_tokens = 0
        output_tokens = 0
        
        # Anthropic prompt caching: نضع system prompt في cache (ttl 5min)
        # يخفّض التكلفة ~60% للجلسات المتكررة
        system_with_cache = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

        try:
            async with self.client.messages.stream(
                model=self.info.model,
                max_tokens=8000,
                system=system_with_cache,
                messages=anthropic_msgs,
            ) as stream:
                async for text in stream.text_stream:
                    full_text += text
                    yield text, None

                final_msg = await stream.get_final_message()
                input_tokens = final_msg.usage.input_tokens
                output_tokens = final_msg.usage.output_tokens
                # Log cache effectiveness
                cached = getattr(final_msg.usage, 'cache_read_input_tokens', 0) or 0
                if cached:
                    logger.info(f"Claude cache hit: {cached} tokens cached")

            yield "", StreamResult(full_text, input_tokens, output_tokens)
        except Exception as e:
            err = f"\n\n[خطأ Claude: {str(e)[:200]}]"
            yield err, StreamResult(full_text + err, input_tokens, output_tokens)


# ============== GPT (OpenAI) ==============

class GPTAgent(Agent):
    INFO = AgentInfo(
        id="gpt",
        name="GPT",
        provider="openai",
        role="المبرمج العملي وحلال المشاكل",
        color="#10A37F",
        description="عملي، سريع، يفضل الحلول الواقعية والكود الذي يعمل، يكره النظريات بدون تطبيق",
        model="gpt-4o",
        input_price_per_mtok=2.50,
        output_price_per_mtok=10.0,
    )
    
    def __init__(self, api_key: str):
        super().__init__(self.INFO, api_key)
        self.client = AsyncOpenAI(api_key=api_key)
    
    async def stream(self, messages, team_context=""):
        system = self.build_system_prompt(team_context)

        oai_msgs = [{"role": "system", "content": system}]
        for m in messages:
            images = m.get("images") or []
            if m["role"] == "user":
                if images:
                    # OpenAI multimodal: content is array of {type:"text"} و {type:"image_url"}
                    parts = [{"type": "image_url", "image_url": {"url": img}} for img in images]
                    if m["content"]:
                        parts.append({"type": "text", "text": m["content"]})
                    oai_msgs.append({"role": "user", "content": parts})
                else:
                    oai_msgs.append({"role": "user", "content": m["content"]})
            elif m["role"] == "agent" and m.get("agent_id") == "gpt":
                oai_msgs.append({"role": "assistant", "content": m["content"]})
            elif m["role"] == "agent":
                name = m.get("agent_name", "زميل")
                oai_msgs.append({"role": "user", "content": f"[رسالة من {name}]: {m['content']}"})
        
        full_text = ""
        try:
            stream = await self.client.chat.completions.create(
                model=self.info.model,
                messages=oai_msgs,
                stream=True,
                max_tokens=8000,
                stream_options={"include_usage": True},
            )
            
            input_tokens = 0
            output_tokens = 0
            
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_text += text
                    yield text, None
                
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens
                    output_tokens = chunk.usage.completion_tokens
            
            yield "", StreamResult(full_text, input_tokens, output_tokens)
        except Exception as e:
            err = f"\n\n[خطأ GPT: {str(e)[:200]}]"
            yield err, StreamResult(full_text + err, 0, 0)


# ============== Gemini (Google) ==============

class GeminiAgent(Agent):
    INFO = AgentInfo(
        id="gemini",
        name="Gemini",
        provider="gemini",
        role="الباحث والمبتكر",
        color="#4285F4",
        description="فضولي، يحب الأفكار الجديدة والمقاربات غير التقليدية، يبحث عن الزوايا المخفية",
        model="gemini-2.5-flash",
        input_price_per_mtok=0.10,
        output_price_per_mtok=0.40,
    )
    
    def __init__(self, api_key: str):
        super().__init__(self.INFO, api_key)
        self.client = google_genai.Client(api_key=api_key)
    
    async def stream(self, messages, team_context=""):
        system = self.build_system_prompt(team_context)

        # Gemini يدعم multimodal عبر contents = list of parts (text + inline_data)
        # نبني conversation string مع inline image parts
        conversation_parts = []
        last_user_images = []
        text_buffer = ""
        for m in messages:
            if m["role"] == "user":
                text_buffer += f"المستخدم: {m['content']}\n\n"
                last_user_images = m.get("images") or []
            elif m["role"] == "agent" and m.get("agent_id") == "gemini":
                text_buffer += f"أنت (Gemini): {m['content']}\n\n"
            elif m["role"] == "agent":
                name = m.get("agent_name", "زميل")
                text_buffer += f"{name}: {m['content']}\n\n"
        text_buffer += "Gemini: "

        # إن وُجدت صور في آخر رسالة user، نُمرّرها مع النص
        if last_user_images:
            import base64
            for img in last_user_images:
                if isinstance(img, str) and img.startswith("data:"):
                    try:
                        header, b64 = img.split(",", 1)
                        mime = header.split(":")[1].split(";")[0] or "image/png"
                        conversation_parts.append({
                            "inline_data": {"mime_type": mime, "data": b64}
                        })
                    except Exception:
                        pass
            conversation_parts.append({"text": text_buffer})
            conversation = conversation_parts
        else:
            conversation = text_buffer
        
        full_text = ""
        try:
            response = self.client.aio.models.generate_content_stream(
                model=self.info.model,
                contents=conversation,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=8000,
                ),
            )

            input_tokens = 0
            output_tokens = 0

            async for chunk in response:
                if chunk.text:
                    full_text += chunk.text
                    yield chunk.text, None
                
                # Gemini يرجع usage في metadata
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    input_tokens = chunk.usage_metadata.prompt_token_count or 0
                    output_tokens = chunk.usage_metadata.candidates_token_count or 0
            
            yield "", StreamResult(full_text, input_tokens, output_tokens)
        except Exception as e:
            err = f"\n\n[خطأ Gemini: {str(e)[:200]}]"
            yield err, StreamResult(full_text + err, 0, 0)


# ============== DeepSeek ==============

class DeepSeekAgent(Agent):
    """DeepSeek يستخدم OpenAI-compatible API"""
    
    INFO = AgentInfo(
        id="deepseek",
        name="DeepSeek",
        provider="deepseek",
        role="المتخصص في الكود والرياضيات",
        color="#7C3AED",
        description="عميق، يفكر بمنطق رياضي، ممتاز في تحليل الخوارزميات وتحسين الكود",
        model="deepseek-chat",
        input_price_per_mtok=0.27,
        output_price_per_mtok=1.10,
    )
    
    def __init__(self, api_key: str):
        super().__init__(self.INFO, api_key)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )
    
    async def stream(self, messages, team_context=""):
        system = self.build_system_prompt(team_context)
        
        ds_msgs = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                ds_msgs.append({"role": "user", "content": m["content"]})
            elif m["role"] == "agent" and m.get("agent_id") == "deepseek":
                ds_msgs.append({"role": "assistant", "content": m["content"]})
            elif m["role"] == "agent":
                name = m.get("agent_name", "زميل")
                ds_msgs.append({"role": "user", "content": f"[رسالة من {name}]: {m['content']}"})
        
        full_text = ""
        try:
            stream = await self.client.chat.completions.create(
                model=self.info.model,
                messages=ds_msgs,
                stream=True,
                max_tokens=8000,
            )
            
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_text += text
                    yield text, None
            
            # DeepSeek لا يرجع usage في streaming - تقدير
            yield "", StreamResult(
                full_text,
                input_tokens=sum(len(m["content"]) for m in ds_msgs) // 4,
                output_tokens=len(full_text) // 4,
            )
        except Exception as e:
            err = f"\n\n[خطأ DeepSeek: {str(e)[:200]}]"
            yield err, StreamResult(full_text + err, 0, 0)


# ============== Registry ==============

# استيراد Manus Agent الحصري
try:
    from app.agent_manus import ManusAgent as _ManusAgent
    _MANUS_AVAILABLE = True
except Exception:
    _MANUS_AVAILABLE = False
    _ManusAgent = None

AGENT_CLASSES = {
    "claude": ClaudeAgent,
    "gpt": GPTAgent,
    "gemini": GeminiAgent,
    "deepseek": DeepSeekAgent,
}

# أضف Manus تلقائياً (لا يحتاج API key)
if _MANUS_AVAILABLE and _ManusAgent:
    AGENT_CLASSES["manus"] = _ManusAgent


def get_all_agent_infos() -> List[AgentInfo]:
    """يرجع info كل الـ agents (سواء كانت مفعلة أم لا)"""
    return [cls.INFO for cls in AGENT_CLASSES.values()]


def create_agent(agent_id: str, api_key: str) -> Optional[Agent]:
    """ينشئ instance من agent بالمفتاح المعطى"""
    cls = AGENT_CLASSES.get(agent_id)
    if not cls:
        return None
    return cls(api_key)
