"""
ConversationOrchestrator - منسق الحوار بين الـ Agents

3 أنماط:
- solo: نموذج واحد يرد
- round_robin: كل نموذج يرد مرة واحدة بالتسلسل
- consensus: 3 مراحل (proposals → critique → synthesis)

Events المُبثّة (للـ WebSocket):
- user_message_saved: {message_id}
- turn_start: {agent_id, agent_name, phase?}
- chunk: {agent_id, text}
- turn_complete: {agent_id, message_id, input_tokens, output_tokens, cost_usd}
- phase_change: {phase}  # consensus only
- complete: {}
- error: {agent_id?, error}
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, List, Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agents import Agent, AGENT_CLASSES, create_agent
from app.key_resolver import resolve_key_for_user, ResolvedKey
from app.models import (
    Message, MessageRole, ConversationMode, Session, User, UsageLog
)


# ============== Event Types ==============

def _evt(event_type: str, **data) -> Dict[str, Any]:
    """ينشئ event dict موحد"""
    return {"type": event_type, **data}


# ============== Helpers ==============

async def _load_session_messages(
    db: AsyncSession,
    session_id: int,
) -> List[Message]:
    """يحمل كل رسائل الجلسة بالترتيب"""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


def _msgs_to_agent_format(messages: List[Message]) -> List[Dict]:
    """يحول Message DB rows إلى dict format للـ Agent.stream()"""
    out = []
    for m in messages:
        d = {
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "content": m.content,
        }
        if m.agent_id:
            d["agent_id"] = m.agent_id
        if m.agent_name:
            d["agent_name"] = m.agent_name
        out.append(d)
    return out


async def _resolve_agents(
    user: User,
    agent_ids: List[str],
    db: AsyncSession,
) -> Dict[str, Agent]:
    """
    يحوّل قائمة agent_ids إلى agents جاهزة للاستخدام.
    يتخطى أي agent بدون مفتاح متاح.
    """
    agents: Dict[str, Agent] = {}
    for aid in agent_ids:
        resolved: Optional[ResolvedKey] = await resolve_key_for_user(user, aid, db)
        if not resolved:
            continue
        agent = create_agent(aid, resolved.key)
        if agent:
            # نخزن is_server_key للمحاسبة لاحقاً
            agent._is_server_key = resolved.is_server_key  # type: ignore
            agents[aid] = agent
    return agents


def _build_team_context(active_agents: Dict[str, Agent]) -> str:
    """
    يبني نص يخبر كل agent بزملائه في الجلسة.
    يساعد النموذج يعرف مع من يتعاون.
    """
    if len(active_agents) <= 1:
        return ""
    lines = ["زملاؤك في هذه الجلسة:"]
    for aid, agent in active_agents.items():
        lines.append(f"- {agent.info.name} ({agent.info.role})")
    return "\n".join(lines)


# ============== Single-turn streaming helper ==============

async def _stream_one_turn(
    agent: Agent,
    history_messages: List[Dict],
    team_context: str,
    db: AsyncSession,
    session_id: int,
    user: User,
    mode: ConversationMode,
    phase: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    يبث رد agent واحد:
    - turn_start
    - chunks
    - يحفظ Message + UsageLog في DB
    - turn_complete
    """
    yield _evt(
        "turn_start",
        agent_id=agent.info.id,
        agent_name=agent.info.name,
        phase=phase,
    )

    full_text = ""
    input_tokens = 0
    output_tokens = 0
    success = True
    error_message: Optional[str] = None

    try:
        async for chunk, result in agent.stream(history_messages, team_context):
            if chunk:
                full_text += chunk
                yield _evt("chunk", agent_id=agent.info.id, text=chunk)
            if result is not None:
                # نأخذ الـ usage الكامل من النتيجة النهائية
                full_text = result.full_text
                input_tokens = result.input_tokens
                output_tokens = result.output_tokens
    except Exception as e:
        success = False
        error_message = str(e)[:500]
        yield _evt("error", agent_id=agent.info.id, error=error_message)

    cost = agent.calculate_cost(input_tokens, output_tokens) if success else 0.0

    # احفظ الـ Message في DB (حتى لو فشلت - نحفظ ما بُث)
    msg = Message(
        session_id=session_id,
        role=MessageRole.AGENT,
        agent_id=agent.info.id,
        agent_name=agent.info.name,
        content=full_text,
        mode=mode,
        phase=phase,
        input_tokens=input_tokens or None,
        output_tokens=output_tokens or None,
        cost_usd=cost or None,
    )
    db.add(msg)

    # سجل الاستخدام
    is_server = bool(getattr(agent, "_is_server_key", False))
    log = UsageLog(
        user_id=user.id,
        agent_id=agent.info.id,
        used_server_key=is_server,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        success=success,
        error_message=error_message,
    )
    db.add(log)

    await db.flush()  # نريد msg.id

    yield _evt(
        "turn_complete",
        agent_id=agent.info.id,
        message_id=msg.id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        success=success,
    )


# ============== ConversationOrchestrator ==============

class ConversationOrchestrator:
    """
    منسق الحوار - واجهة عالية المستوى لإجراء محادثة:

    orch = ConversationOrchestrator(user, session, db)
    async for event in orch.run(user_msg, mode, agent_ids):
        # ابعت الـ event للعميل عبر WebSocket
    """

    def __init__(self, user: User, session: Session, db: AsyncSession):
        self.user = user
        self.session = session
        self.db = db

    async def run(
        self,
        user_message: str,
        mode: ConversationMode,
        agent_ids: List[str],
        images: Optional[List[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """نقطة الدخول الرئيسية - يدعم الصور (multimodal)"""
        self._current_user_images = images or []
        # 1. احفظ رسالة المستخدم
        # نُضيف ملاحظة في النص لو فيها صور (لكن الصور لا تُخزَّن في DB لأنها كبيرة)
        content_for_db = user_message
        if self._current_user_images:
            content_for_db = (user_message or "") + f"\n\n[تم إرفاق {len(self._current_user_images)} صورة]"
        user_msg = Message(
            session_id=self.session.id,
            role=MessageRole.USER,
            content=content_for_db,
            mode=mode,
        )
        self.db.add(user_msg)
        await self.db.flush()
        yield _evt("user_message_saved", message_id=user_msg.id)

        # 2. حضّر agents
        if not agent_ids:
            yield _evt("error", error="لم يتم اختيار أي agent")
            return

        agents = await _resolve_agents(self.user, agent_ids, self.db)
        if not agents:
            yield _evt(
                "error",
                error="لا يوجد مفتاح API متاح لأي من الـ agents المختارة",
            )
            return

        # 3. شغّل النمط المطلوب
        try:
            if mode == ConversationMode.SOLO:
                async for evt in self._run_solo(agents):
                    yield evt
            elif mode == ConversationMode.ROUND_ROBIN:
                async for evt in self._run_round_robin(agents):
                    yield evt
            elif mode == ConversationMode.CONSENSUS:
                async for evt in self._run_consensus(agents):
                    yield evt
            else:
                yield _evt("error", error=f"نمط غير معروف: {mode}")
                return
        except Exception as e:
            yield _evt("error", error=f"خطأ في الـ orchestrator: {str(e)[:300]}")
            return

        # 4. اختم
        yield _evt("complete")

    # ------------- Solo -------------

    async def _run_solo(
        self,
        agents: Dict[str, Agent],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """نموذج واحد يرد - أول agent في القائمة"""
        agent_id, agent = next(iter(agents.items()))
        history = await self._load_history()
        team_ctx = _build_team_context(agents)
        async for evt in _stream_one_turn(
            agent=agent,
            history_messages=history,
            team_context=team_ctx,
            db=self.db,
            session_id=self.session.id,
            user=self.user,
            mode=ConversationMode.SOLO,
        ):
            yield evt

    # ------------- Round Robin -------------

    async def _run_round_robin(
        self,
        agents: Dict[str, Agent],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """كل agent يرد مرة واحدة بالتسلسل، يرى ردود السابقين"""
        team_ctx = _build_team_context(agents)
        for agent_id, agent in agents.items():
            history = await self._load_history()
            async for evt in _stream_one_turn(
                agent=agent,
                history_messages=history,
                team_context=team_ctx,
                db=self.db,
                session_id=self.session.id,
                user=self.user,
                mode=ConversationMode.ROUND_ROBIN,
            ):
                yield evt

    # ------------- Consensus (3 phases) -------------

    async def _run_consensus(
        self,
        agents: Dict[str, Agent],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        3 مراحل:
        1. proposals: كل agent يقترح بشكل مستقل (لا يرى ردود الآخرين)
        2. critique: كل agent يرى كل الاقتراحات وينتقدها
        3. synthesis: agent واحد (الأول) يكتب الحل النهائي المدمج
        """
        team_ctx = _build_team_context(agents)
        # نحفظ history الأصلي (قبل المرحلة 1) لاستخدامه لكل agent في proposals
        base_history = await self._load_history()

        # === Phase 1: Proposals ===
        yield _evt("phase_change", phase="proposals")
        proposal_prompt = (
            "\n\n[نظام الإجماع - مرحلة الاقتراحات]\n"
            "اكتب اقتراحك المستقل لحل هذه المشكلة. "
            "لا ترى زملاءك في هذه المرحلة. ركّز على وجهة نظرك ودورك."
        )
        # نضيف تعليمة phase لآخر رسالة user
        history_p1 = base_history.copy()
        if history_p1 and history_p1[-1]["role"] == "user":
            history_p1[-1] = {**history_p1[-1], "content": history_p1[-1]["content"] + proposal_prompt}

        for agent_id, agent in agents.items():
            async for evt in _stream_one_turn(
                agent=agent,
                history_messages=history_p1,  # كل واحد يرى نفس الـ history (بدون اقتراحات الآخرين)
                team_context=team_ctx,
                db=self.db,
                session_id=self.session.id,
                user=self.user,
                mode=ConversationMode.CONSENSUS,
                phase="proposals",
            ):
                yield evt

        # === Phase 2: Critique ===
        yield _evt("phase_change", phase="critique")
        critique_prompt = (
            "\n\n[نظام الإجماع - مرحلة النقد]\n"
            "اقرأ اقتراحات زملائك أعلاه وانتقدها بصدق. "
            "أشر للأخطاء والنقاط القوية والتحسينات الممكنة. "
            "كن مختصراً ومركّزاً."
        )
        history_p2_base = await self._load_history()
        # أضف تعليمة critique قبل آخر رسالة (الاقتراحات)
        if history_p2_base:
            history_p2_base.append({
                "role": "user",
                "content": critique_prompt,
            })

        for agent_id, agent in agents.items():
            async for evt in _stream_one_turn(
                agent=agent,
                history_messages=history_p2_base,
                team_context=team_ctx,
                db=self.db,
                session_id=self.session.id,
                user=self.user,
                mode=ConversationMode.CONSENSUS,
                phase="critique",
            ):
                yield evt

        # === Phase 3: Synthesis ===
        yield _evt("phase_change", phase="synthesis")
        synthesis_prompt = (
            "\n\n[نظام الإجماع - مرحلة التركيب]\n"
            "اقرأ كل الاقتراحات والنقد أعلاه. "
            "اكتب الإجابة النهائية المدمجة التي تأخذ أفضل ما في كل اقتراح "
            "وتعالج النقاط التي رفعها النقد. "
            "هذه هي الإجابة التي ستُسلّم للمستخدم."
        )
        history_p3 = await self._load_history()
        history_p3.append({"role": "user", "content": synthesis_prompt})

        # نختار synthesizer ديناميكياً (لا نُهيمن Claude دائماً)
        # القاعدة: نختار النموذج الذي قدّم أقل عدد رسائل في هذه الجلسة
        # هذا يضمن العدالة + يتيح لكل نموذج فرصة الـ synthesis
        import hashlib
        # استخدم hash من session_id لاختيار قابل للتكرار في نفس الجلسة
        # لكن مختلف بين الجلسات (لا توجد هيمنة دائمة لنموذج)
        agent_ids_list = list(agents.keys())
        seed = int(hashlib.md5(f"{self.session.id}-synth".encode()).hexdigest()[:8], 16)
        synth_idx = seed % len(agent_ids_list)
        synth_agent_id = agent_ids_list[synth_idx]
        synth_agent = agents[synth_agent_id]
        async for evt in _stream_one_turn(
            agent=synth_agent,
            history_messages=history_p3,
            team_context=team_ctx,
            db=self.db,
            session_id=self.session.id,
            user=self.user,
            mode=ConversationMode.CONSENSUS,
            phase="synthesis",
        ):
            yield evt

    # ------------- Utility -------------

    async def _load_history(self) -> List[Dict]:
        """يحمّل كل رسائل الجلسة بصيغة agent_format. يُلصق الصور بآخر رسالة user."""
        msgs = await _load_session_messages(self.db, self.session.id)
        history = _msgs_to_agent_format(msgs)
        # ألصق الصور المُرفقة في الـ turn الحالي بآخر رسالة user
        imgs = getattr(self, "_current_user_images", None) or []
        if imgs and history:
            for i in range(len(history) - 1, -1, -1):
                if history[i]["role"] == "user":
                    history[i] = {**history[i], "images": imgs}
                    break
        return history
