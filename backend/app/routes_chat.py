"""
Chat Routes - WebSocket للـ streaming + REST endpoint كـ fallback

WebSocket protocol:
- Client → Server (JSON):
    {type: "auth", token: str}            # إن لم يكن JWT في query param
    {type: "message", content, mode, agents}
    {type: "ping"}

- Server → Client (JSON):
    {type: "ready"}
    {type: "auth_ok"} | {type: "auth_failed", error}
    {type: "user_message_saved", message_id}
    {type: "turn_start", agent_id, agent_name, phase?}
    {type: "chunk", agent_id, text}
    {type: "turn_complete", agent_id, message_id, input_tokens, output_tokens, cost_usd, success}
    {type: "phase_change", phase}                    # consensus only
    {type: "complete"}
    {type: "limit_reached", used, limit, plan}
    {type: "error", error, agent_id?}
"""
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, async_session_maker
from app.models import User, Session as DbSession, ConversationMode
from app.security import decode_access_token
from app.orchestrator import ConversationOrchestrator
from app.routes_usage import check_usage_limit


router = APIRouter(prefix="/chat", tags=["chat"])


async def _authenticate_websocket(
    websocket: WebSocket,
    token: Optional[str],
    db: AsyncSession,
) -> Optional[User]:
    """يصادق على المستخدم من JWT في query param أو من رسالة auth"""
    if not token:
        # حاول قراءة رسالة auth أولى
        try:
            first = await websocket.receive_json()
            if first.get("type") == "auth":
                token = first.get("token")
        except Exception:
            return None
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = int(sub)
    except Exception:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and user.is_active:
        return user
    return None


@router.websocket("/ws/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: int,
    token: Optional[str] = Query(default=None),
):
    """
    WebSocket endpoint للمحادثة في جلسة محددة.
    JWT يُمرّر إما عبر ?token=... أو رسالة auth أولى.
    """
    await websocket.accept()

    # Authenticate (نُفتح session DB خاص بالـ WS)
    async with async_session_maker() as db:
        try:
            user = await _authenticate_websocket(websocket, token, db)
            if not user:
                await websocket.send_json({
                    "type": "auth_failed",
                    "error": "غير مُصادق - access denied",
                })
                await websocket.close(code=4401)
                return

            # تحقق من ملكية الجلسة
            result = await db.execute(
                select(DbSession).where(
                    DbSession.id == session_id,
                    DbSession.user_id == user.id,
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                await websocket.send_json({
                    "type": "error",
                    "error": "الجلسة غير موجودة أو ليست لك",
                })
                await websocket.close(code=4404)
                return

            await websocket.send_json({"type": "ready", "session_id": session.id})
        except Exception as e:
            try:
                await websocket.send_json({"type": "error", "error": str(e)[:300]})
            except Exception:
                pass
            await websocket.close()
            return

        # حلقة الاستقبال
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue

                if msg_type != "message":
                    await websocket.send_json({
                        "type": "error",
                        "error": f"نوع غير مدعوم: {msg_type}",
                    })
                    continue

                content = (msg.get("content") or "").strip()
                images = msg.get("images") or []
                # تحقق صحة الصور (max 4، كل واحدة <= 5MB base64)
                if images:
                    if len(images) > 4:
                        await websocket.send_json({"type": "error", "error": "حد أقصى 4 صور"})
                        continue
                    for img in images:
                        if not isinstance(img, str) or len(img) > 7_000_000:
                            await websocket.send_json({"type": "error", "error": "صورة غير صالحة أو أكبر من 5MB"})
                            continue
                if not content and not images:
                    await websocket.send_json({
                        "type": "error",
                        "error": "الرسالة فارغة",
                    })
                    continue

                # تحقق الحد الشهري
                allowed, usage_info = await check_usage_limit(user, db)
                if not allowed:
                    await websocket.send_json({
                        "type": "limit_reached",
                        **usage_info,
                        "message": (
                            f"تجاوزت الحد الشهري ({usage_info['limit']} رسالة) "
                            f"للخطة {usage_info['plan']}. "
                            "اشترك للحصول على مزيد من الرسائل."
                        ),
                    })
                    continue

                # حدّد mode + agents
                mode_str = msg.get("mode") or session.default_mode.value
                try:
                    mode = ConversationMode(mode_str)
                except ValueError:
                    mode = session.default_mode

                agents = msg.get("agents") or session.default_agents or []
                if not agents:
                    await websocket.send_json({
                        "type": "error",
                        "error": "لم يتم اختيار أي agent",
                    })
                    continue

                # شغّل الـ orchestrator وابعت الـ events
                orch = ConversationOrchestrator(user, session, db)
                try:
                    async for event in orch.run(content, mode, agents, images=images):
                        await websocket.send_json(event)
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    await websocket.send_json({
                        "type": "error",
                        "error": f"فشل: {str(e)[:300]}",
                    })

        except WebSocketDisconnect:
            return
        except Exception as e:
            try:
                await websocket.send_json({
                    "type": "error",
                    "error": f"خطأ غير متوقع: {str(e)[:300]}",
                })
            except Exception:
                pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass
