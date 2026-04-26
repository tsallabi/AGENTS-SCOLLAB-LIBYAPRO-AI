"""
اختبارات المرحلة 2 - Orchestrator

شقّان:
1. Unit tests بـ mock agents (سريعة، بدون مفاتيح)
2. Integration tests مع APIs حقيقية (تستخدم Gemini الأرخص)

شغّل:
    cd backend
    PYTHONIOENCODING=utf-8 python tests/test_phase2_orchestrator.py
    PYTHONIOENCODING=utf-8 python tests/test_phase2_orchestrator.py --real
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple

# تأكد أن جذر الـ backend في sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from app.models import (
    Base, User, Session as DbSession, Message, MessageRole,
    ConversationMode, PlanType, ApiKey, UsageLog,
)
from app.agents import Agent, AgentInfo, StreamResult, AGENT_CLASSES
from app.orchestrator import ConversationOrchestrator
from app.security import hash_password, encrypt_api_key
from app.config import settings


# ============== Mock Agent ==============

class MockAgent(Agent):
    """Agent وهمي للاختبار - يبث نص ثابت"""

    def __init__(
        self,
        agent_id: str,
        name: str,
        reply_text: str = "هذا رد تجريبي",
        chunk_count: int = 5,
    ):
        info = AgentInfo(
            id=agent_id,
            name=name,
            provider=agent_id,
            role="agent تجريبي",
            color="#000000",
            description="mock",
            model="mock-1",
            input_price_per_mtok=1.0,
            output_price_per_mtok=2.0,
        )
        super().__init__(info, "mock-key")
        self.reply_text = reply_text
        self.chunk_count = chunk_count
        self.calls: List[Tuple[List[Dict], str]] = []  # تسجيل المكالمات للتحقق

    async def stream(
        self,
        messages: List[Dict],
        team_context: str = "",
    ) -> AsyncGenerator[Tuple[str, Optional[StreamResult]], None]:
        # سجّل المكالمة
        self.calls.append((list(messages), team_context))

        # قسّم النص إلى chunks وابعتهم
        text = self.reply_text
        size = max(1, len(text) // self.chunk_count)
        sent = ""
        for i in range(0, len(text), size):
            chunk = text[i:i + size]
            sent += chunk
            yield chunk, None
            await asyncio.sleep(0)  # السماح بـ context switch
        # النتيجة النهائية
        yield "", StreamResult(sent, input_tokens=100, output_tokens=50)


# ============== Test DB Setup ==============

TEST_DB_FILE = BACKEND_DIR / "_test_phase2.db"


async def _make_test_db():
    """ينشئ DB نظيف للاختبارات"""
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()
    url = f"sqlite+aiosqlite:///{TEST_DB_FILE.as_posix()}"
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, sm


async def _make_user_and_session(
    db: AsyncSession,
    plan: PlanType = PlanType.FREE,
    encrypted_keys: Optional[Dict[str, str]] = None,
) -> Tuple[User, DbSession]:
    """ينشئ user + session للاختبار. مفاتيح المستخدم: dict[provider]=plain_key"""
    user = User(
        email="test@test.com",
        password_hash=hash_password("password123"),
        plan=plan,
    )
    db.add(user)
    await db.flush()

    if encrypted_keys:
        for provider, plain in encrypted_keys.items():
            ak = ApiKey(
                user_id=user.id,
                provider=provider,
                encrypted_key=encrypt_api_key(plain),
            )
            db.add(ak)

    sess = DbSession(
        user_id=user.id,
        title="جلسة اختبار",
        default_mode=ConversationMode.ROUND_ROBIN,
        default_agents=["claude", "gpt"],
    )
    db.add(sess)
    await db.flush()
    return user, sess


# ============== Tests ==============

class TestRunner:
    """منظم اختبارات بسيط"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures: List[str] = []

    def assert_true(self, cond: bool, label: str):
        if cond:
            self.passed += 1
            print(f"   ✅ {label}")
        else:
            self.failed += 1
            self.failures.append(label)
            print(f"   ❌ {label}")

    def assert_eq(self, actual, expected, label: str):
        ok = actual == expected
        if ok:
            self.passed += 1
            print(f"   ✅ {label} (= {expected!r})")
        else:
            self.failed += 1
            self.failures.append(f"{label}: expected {expected!r}, got {actual!r}")
            print(f"   ❌ {label}: expected {expected!r}, got {actual!r}")


async def test_solo_mock(t: TestRunner):
    print("\n📋 1. Solo mode (mock agent)")
    engine, sm = await _make_test_db()
    try:
        async with sm() as db:
            user, sess = await _make_user_and_session(
                db, plan=PlanType.PRO,  # PRO يستخدم server keys (موجودة بـ env)
            )
            # نُحقن mock agent مباشرة عبر patching
            mock = MockAgent("claude", "Claude", reply_text="مرحباً، أنا Claude.")

            orch = ConversationOrchestrator(user, sess, db)

            # patch resolve_agents بدلاً من الحقيقي
            from app import orchestrator as orch_mod
            original = orch_mod._resolve_agents
            async def fake_resolve(u, ids, dbb):
                return {"claude": mock}
            orch_mod._resolve_agents = fake_resolve

            try:
                events = []
                async for evt in orch.run(
                    user_message="اختبار",
                    mode=ConversationMode.SOLO,
                    agent_ids=["claude"],
                ):
                    events.append(evt)
                await db.commit()
            finally:
                orch_mod._resolve_agents = original

            event_types = [e["type"] for e in events]
            t.assert_true("user_message_saved" in event_types, "user_message_saved مُبثّ")
            t.assert_true("turn_start" in event_types, "turn_start مُبثّ")
            t.assert_true("chunk" in event_types, "chunks مُبثّة")
            t.assert_true("turn_complete" in event_types, "turn_complete مُبثّ")
            t.assert_true(event_types[-1] == "complete", "آخر event هو complete")

            # تحقّق DB
            msgs = await db.execute(select(Message).where(Message.session_id == sess.id))
            msgs_list = list(msgs.scalars().all())
            t.assert_eq(len(msgs_list), 2, "رسالتان في DB (user + agent)")
            t.assert_eq(msgs_list[0].role, MessageRole.USER, "أول رسالة من user")
            t.assert_eq(msgs_list[1].role, MessageRole.AGENT, "ثاني رسالة من agent")
            t.assert_eq(msgs_list[1].agent_id, "claude", "agent_id = claude")
            t.assert_eq(msgs_list[1].content, "مرحباً، أنا Claude.", "نص الرد محفوظ كاملاً")
            t.assert_true(msgs_list[1].cost_usd is not None and msgs_list[1].cost_usd > 0, "cost محفوظة")

            # تحقّق UsageLog
            logs = await db.execute(select(UsageLog).where(UsageLog.user_id == user.id))
            logs_list = list(logs.scalars().all())
            t.assert_eq(len(logs_list), 1, "UsageLog واحد")
            t.assert_eq(logs_list[0].agent_id, "claude", "log.agent_id = claude")
    finally:
        await engine.dispose()


async def test_round_robin_mock(t: TestRunner):
    print("\n📋 2. Round-robin mode (3 mock agents)")
    engine, sm = await _make_test_db()
    try:
        async with sm() as db:
            user, sess = await _make_user_and_session(db, plan=PlanType.PRO)
            mocks = {
                "claude": MockAgent("claude", "Claude", "رد كلود"),
                "gpt": MockAgent("gpt", "GPT", "رد جي بي تي"),
                "gemini": MockAgent("gemini", "Gemini", "رد جيميني"),
            }

            from app import orchestrator as orch_mod
            original = orch_mod._resolve_agents
            async def fake(u, ids, dbb):
                return {k: mocks[k] for k in ids if k in mocks}
            orch_mod._resolve_agents = fake

            orch = ConversationOrchestrator(user, sess, db)
            try:
                events = []
                async for evt in orch.run(
                    "تعاونوا على هذه المهمة",
                    ConversationMode.ROUND_ROBIN,
                    ["claude", "gpt", "gemini"],
                ):
                    events.append(evt)
                await db.commit()
            finally:
                orch_mod._resolve_agents = original

            # 3 turn_start، 3 turn_complete
            starts = [e for e in events if e["type"] == "turn_start"]
            completes = [e for e in events if e["type"] == "turn_complete"]
            t.assert_eq(len(starts), 3, "3 turn_start")
            t.assert_eq(len(completes), 3, "3 turn_complete")
            t.assert_eq(
                [s["agent_id"] for s in starts],
                ["claude", "gpt", "gemini"],
                "الترتيب صحيح claude → gpt → gemini",
            )

            # كل agent يجب أن يرى رسائل السابقين
            t.assert_eq(len(mocks["claude"].calls[0][0]), 1, "Claude رأى رسالة واحدة (user فقط)")
            t.assert_eq(len(mocks["gpt"].calls[0][0]), 2, "GPT رأى 2 رسائل (user + claude)")
            t.assert_eq(len(mocks["gemini"].calls[0][0]), 3, "Gemini رأى 3 رسائل (user + claude + gpt)")

            # 4 رسائل في DB (user + 3 agents)
            msgs = await db.execute(select(Message).where(Message.session_id == sess.id))
            t.assert_eq(len(list(msgs.scalars().all())), 4, "4 رسائل في DB")
    finally:
        await engine.dispose()


async def test_consensus_mock(t: TestRunner):
    print("\n📋 3. Consensus mode (3 mock agents, 3 phases)")
    engine, sm = await _make_test_db()
    try:
        async with sm() as db:
            user, sess = await _make_user_and_session(db, plan=PlanType.PRO)
            mocks = {
                "claude": MockAgent("claude", "Claude", "اقتراح كلود"),
                "gpt": MockAgent("gpt", "GPT", "اقتراح جي بي تي"),
                "gemini": MockAgent("gemini", "Gemini", "اقتراح جيميني"),
            }

            from app import orchestrator as orch_mod
            original = orch_mod._resolve_agents
            async def fake(u, ids, dbb):
                return {k: mocks[k] for k in ids if k in mocks}
            orch_mod._resolve_agents = fake

            orch = ConversationOrchestrator(user, sess, db)
            try:
                events = []
                async for evt in orch.run(
                    "صمّم لي architecture لتطبيق",
                    ConversationMode.CONSENSUS,
                    ["claude", "gpt", "gemini"],
                ):
                    events.append(evt)
                await db.commit()
            finally:
                orch_mod._resolve_agents = original

            phase_changes = [e for e in events if e["type"] == "phase_change"]
            t.assert_eq(
                [p["phase"] for p in phase_changes],
                ["proposals", "critique", "synthesis"],
                "3 مراحل بالترتيب الصحيح",
            )

            # turn_start: 3 (proposals) + 3 (critique) + 1 (synthesis) = 7
            starts = [e for e in events if e["type"] == "turn_start"]
            t.assert_eq(len(starts), 7, "7 turn_start (3+3+1)")

            # phases في turn_start
            phases = [s.get("phase") for s in starts]
            t.assert_eq(
                phases,
                ["proposals"] * 3 + ["critique"] * 3 + ["synthesis"],
                "phase صحيح في كل turn_start",
            )

            # في DB: user + 3 proposals + 3 critique + 1 synthesis = 8
            msgs = await db.execute(
                select(Message).where(Message.session_id == sess.id).order_by(Message.id)
            )
            msgs_list = list(msgs.scalars().all())
            t.assert_eq(len(msgs_list), 8, "8 رسائل في DB")
            phases_db = [m.phase for m in msgs_list[1:]]  # تخطّى رسالة المستخدم
            t.assert_eq(
                phases_db,
                ["proposals"] * 3 + ["critique"] * 3 + ["synthesis"],
                "phases محفوظة في DB بالترتيب",
            )
    finally:
        await engine.dispose()


async def test_no_keys_error(t: TestRunner):
    print("\n📋 4. عدم وجود مفاتيح يُرجع error")
    engine, sm = await _make_test_db()
    try:
        async with sm() as db:
            # FREE plan بدون مفاتيح user → resolve_key يُرجع None
            user, sess = await _make_user_and_session(db, plan=PlanType.FREE)
            orch = ConversationOrchestrator(user, sess, db)

            events = []
            async for evt in orch.run(
                "اختبار", ConversationMode.SOLO, ["claude"],
            ):
                events.append(evt)
            await db.commit()

            error_evts = [e for e in events if e["type"] == "error"]
            t.assert_eq(len(error_evts), 1, "event واحد من نوع error")
            t.assert_true(
                "لا يوجد مفتاح" in error_evts[0]["error"],
                "رسالة الخطأ تذكر عدم وجود مفتاح",
            )
    finally:
        await engine.dispose()


# ============== Real API tests ==============

async def test_real_solo_gemini(t: TestRunner):
    print("\n🌐 5. [حقيقي] Solo مع Gemini")
    if not settings.SERVER_GEMINI_KEY:
        print("   ⏭ تخطّى: SERVER_GEMINI_KEY غير مضبوط")
        return
    engine, sm = await _make_test_db()
    try:
        async with sm() as db:
            user, sess = await _make_user_and_session(db, plan=PlanType.PRO)
            orch = ConversationOrchestrator(user, sess, db)

            text_received = ""
            events = []
            async for evt in orch.run(
                "قل مرحبا بالعربية في كلمتين فقط",
                ConversationMode.SOLO,
                ["gemini"],
            ):
                events.append(evt)
                if evt["type"] == "chunk":
                    text_received += evt["text"]
                    print(f"      📡 {evt['text']}", end="", flush=True)
            print()
            await db.commit()

            t.assert_true(len(text_received) > 0, "Gemini رد بنص")
            completes = [e for e in events if e["type"] == "turn_complete"]
            t.assert_eq(len(completes), 1, "turn_complete واحد")
            t.assert_true(completes[0]["success"], "turn ناجح")
            t.assert_true(completes[0]["output_tokens"] > 0, "tokens > 0")
            print(f"   💰 cost: ${completes[0]['cost_usd']:.6f}")
    finally:
        await engine.dispose()


async def test_real_round_robin_two_models(t: TestRunner):
    print("\n🌐 6. [حقيقي] Round-robin: Claude + Gemini يتعاونان")
    if not (settings.SERVER_GEMINI_KEY and settings.SERVER_ANTHROPIC_KEY):
        print("   ⏭ تخطّى: مفاتيح ناقصة")
        return
    engine, sm = await _make_test_db()
    try:
        async with sm() as db:
            user, sess = await _make_user_and_session(db, plan=PlanType.PRO)
            orch = ConversationOrchestrator(user, sess, db)

            events = []
            current_agent = None
            agent_texts: Dict[str, str] = {}

            async for evt in orch.run(
                "أعطوني فكرة بسيطة لتطبيق ويب مفيد. ردّ في جملتين فقط.",
                ConversationMode.ROUND_ROBIN,
                ["gemini", "claude"],  # gemini أولاً (أرخص)، ثم claude يرد عليه
            ):
                events.append(evt)
                if evt["type"] == "turn_start":
                    current_agent = evt["agent_id"]
                    agent_texts[current_agent] = ""
                    print(f"\n   🤖 {evt['agent_name']}: ", end="", flush=True)
                elif evt["type"] == "chunk":
                    agent_texts[current_agent] += evt["text"]
                    print(evt["text"], end="", flush=True)
                elif evt["type"] == "turn_complete":
                    print(f"\n      💰 ${evt['cost_usd']:.6f} ({evt['input_tokens']} in, {evt['output_tokens']} out)")
            print()
            await db.commit()

            t.assert_true("gemini" in agent_texts and len(agent_texts["gemini"]) > 0, "Gemini تكلّم")
            t.assert_true("claude" in agent_texts and len(agent_texts["claude"]) > 0, "Claude تكلّم")
            completes = [e for e in events if e["type"] == "turn_complete"]
            t.assert_eq(len(completes), 2, "اثنان أكملا دورهما")
            t.assert_true(all(c["success"] for c in completes), "كلاهما نجح")

            total_cost = sum(c["cost_usd"] for c in completes)
            print(f"   💰 إجمالي التكلفة: ${total_cost:.6f}")
    finally:
        await engine.dispose()


# ============== Main ==============

async def main():
    real = "--real" in sys.argv
    print("=" * 60)
    print("🧪 اختبارات المرحلة 2 - Orchestrator")
    print("=" * 60)
    if real:
        print("🌐 وضع حقيقي - سيستخدم APIs ويصرف من الرصيد")
    else:
        print("🤖 وضع mock فقط (مرّر --real لتشغيل اختبارات API حقيقية)")

    t = TestRunner()

    # Mock tests دائماً
    await test_solo_mock(t)
    await test_round_robin_mock(t)
    await test_consensus_mock(t)
    await test_no_keys_error(t)

    if real:
        await test_real_solo_gemini(t)
        await test_real_round_robin_two_models(t)

    # نظّف
    if TEST_DB_FILE.exists():
        try:
            TEST_DB_FILE.unlink()
        except Exception:
            pass

    print("\n" + "=" * 60)
    print(f"✅ نجح: {t.passed}    ❌ فشل: {t.failed}")
    if t.failures:
        print("\nفشل:")
        for f in t.failures:
            print(f"  - {f}")
    print("=" * 60)
    return t.failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
