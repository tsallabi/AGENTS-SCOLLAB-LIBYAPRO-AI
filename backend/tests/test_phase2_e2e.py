"""
اختبار E2E للمرحلة 2 - sessions + WebSocket + orchestrator
يشغّل سيرفر uvicorn حقيقي ويختبر:
- إنشاء جلسة
- WebSocket auth
- إرسال رسالة + streaming
- حفظ الرسائل في DB
- تتبع الاستخدام
- محادثة حقيقية مع Gemini

شغّل:
    cd backend
    PYTHONIOENCODING=utf-8 python tests/test_phase2_e2e.py
"""
from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import websockets

BACKEND_DIR = Path(__file__).resolve().parent.parent
PORT = 8200
BASE = f"http://127.0.0.1:{PORT}"
WS_BASE = f"ws://127.0.0.1:{PORT}"


async def wait_for_server(timeout=45):
    for _ in range(timeout):
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                r = await c.get(f"{BASE}/api/health")
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def run_tests():
    print("\n" + "=" * 60)
    print("🧪 اختبار E2E - المرحلة 2")
    print("=" * 60)

    failures = []

    def check(cond, label):
        if cond:
            print(f"   ✅ {label}")
            return True
        else:
            print(f"   ❌ {label}")
            failures.append(label)
            return False

    async with httpx.AsyncClient(timeout=20.0, base_url=BASE) as client:
        # 1. Health
        print("\n📋 1. Health")
        r = await client.get("/api/health")
        check(r.status_code == 200, "/api/health = 200")

        # 2. Signup
        print("\n📋 2. Signup")
        email = f"e2e_phase2@test.com"
        r = await client.post("/api/auth/signup", json={
            "email": email, "password": "password123", "full_name": "E2E"
        })
        check(r.status_code in (200, 201), f"signup ok (got {r.status_code})")
        data = r.json()
        token = data["access_token"]
        user_id = data["user"]["id"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2b. ترقية المستخدم لـ PRO عبر DB مباشرةً (لاستخدام server keys)
        print("\n📋 2b. ترقية المستخدم لـ PRO (للاختبار)")
        # نستخدم async session مباشرةً
        sys.path.insert(0, str(BACKEND_DIR))
        from app.database import async_session_maker
        from app.models import User, PlanType
        from sqlalchemy import select
        async with async_session_maker() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            u = result.scalar_one()
            u.plan = PlanType.PRO
            await db.commit()
        check(True, "user upgraded to PRO")

        # 3. List sessions (empty)
        print("\n📋 3. List sessions (empty)")
        r = await client.get("/api/sessions", headers=headers)
        check(r.status_code == 200, "list sessions = 200")
        check(r.json() == [], "empty list")

        # 4. Create session
        print("\n📋 4. Create session")
        r = await client.post(
            "/api/sessions",
            headers=headers,
            json={
                "title": "اختبار المرحلة 2",
                "default_mode": "round_robin",
                "default_agents": ["gemini"],
            },
        )
        check(r.status_code == 201, f"create = 201 (got {r.status_code})")
        sess = r.json()
        session_id = sess["id"]
        check(sess["title"] == "اختبار المرحلة 2", "title saved")
        check(sess["default_mode"] == "round_robin", "mode saved")

        # 5. Update session
        print("\n📋 5. Update session")
        r = await client.patch(
            f"/api/sessions/{session_id}",
            headers=headers,
            json={"title": "اسم محدّث"},
        )
        check(r.status_code == 200, "patch = 200")
        check(r.json()["title"] == "اسم محدّث", "title updated")

        # 6. Get session details (no messages yet)
        print("\n📋 6. Get session details")
        r = await client.get(f"/api/sessions/{session_id}", headers=headers)
        check(r.status_code == 200, "get = 200")
        body = r.json()
        check(body["session"]["id"] == session_id, "session id matches")
        check(body["messages"] == [], "no messages yet")

        # 7. Usage initial
        print("\n📋 7. Initial usage")
        r = await client.get("/api/usage/me", headers=headers)
        check(r.status_code == 200, "usage = 200")
        usage = r.json()
        check(usage["total_messages"] == 0, "0 messages")
        check(usage["limit"] > 0, f"limit > 0 ({usage['limit']})")

        # 8. WebSocket - send message + receive streaming
        print("\n📋 8. WebSocket - real Gemini conversation")
        ws_url = f"{WS_BASE}/api/chat/ws/{session_id}?token={token}"
        events = []
        text_received = ""
        try:
            async with websockets.connect(ws_url) as ws:
                # نتوقّع 'ready'
                ready = json.loads(await ws.recv())
                check(ready.get("type") == "ready", "received 'ready'")

                # ابعت رسالة
                await ws.send(json.dumps({
                    "type": "message",
                    "content": "قل مرحبا بكلمتين فقط",
                    "mode": "solo",
                    "agents": ["gemini"],
                }))

                # استلم events حتى complete أو error
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                    events.append(msg)
                    if msg["type"] == "chunk":
                        text_received += msg["text"]
                        print(f"      📡 {msg['text']}", end="", flush=True)
                    if msg["type"] in ("complete", "error", "limit_reached"):
                        break
                print()
        except Exception as e:
            failures.append(f"websocket exception: {e}")
            print(f"   ❌ ws exception: {e}")

        types = [e["type"] for e in events]
        check("user_message_saved" in types, "user_message_saved")
        check("turn_start" in types, "turn_start")
        check("chunk" in types, "chunks streamed")
        check("turn_complete" in types, "turn_complete")
        check(types[-1] == "complete", f"last event = complete (got {types[-1]})")
        check(len(text_received) > 0, "Gemini responded with text")

        # 9. Messages saved
        print("\n📋 9. Messages persisted")
        r = await client.get(f"/api/sessions/{session_id}", headers=headers)
        msgs = r.json()["messages"]
        check(len(msgs) == 2, f"2 messages in DB (got {len(msgs)})")
        if len(msgs) >= 2:
            check(msgs[0]["role"] == "user", "msg 0 is user")
            check(msgs[1]["role"] == "agent", "msg 1 is agent")
            check(msgs[1]["agent_id"] == "gemini", "msg 1 from gemini")

        # 10. Usage incremented
        print("\n📋 10. Usage tracked")
        r = await client.get("/api/usage/me", headers=headers)
        usage2 = r.json()
        check(usage2["total_messages"] == 1, f"messages = 1 (got {usage2['total_messages']})")
        check(usage2.get("by_agent", {}).get("gemini", 0) >= 1, "gemini in by_agent")
        check(usage2["total_cost_usd"] > 0, f"cost > 0 (${usage2['total_cost_usd']:.6f})")
        print(f"      💰 ${usage2['total_cost_usd']:.6f}")

        # 11. Export markdown
        print("\n📋 11. Export markdown")
        r = await client.post(f"/api/sessions/{session_id}/export?format=markdown", headers=headers)
        check(r.status_code == 200, "export = 200")
        md = r.text
        check("اسم محدّث" in md, "title in export")
        check("👤 المستخدم" in md, "user marker in export")
        check("🤖" in md, "agent marker in export")

        # 12. Delete session
        print("\n📋 12. Delete session")
        r = await client.delete(f"/api/sessions/{session_id}", headers=headers)
        check(r.status_code == 204, f"delete = 204 (got {r.status_code})")

        # 13. Verify deleted
        r = await client.get(f"/api/sessions/{session_id}", headers=headers)
        check(r.status_code == 404, "deleted session returns 404")

        # 14. WebSocket auth fails without token
        print("\n📋 13. WebSocket without token rejected")
        # نُنشئ جلسة جديدة لأن السابقة محذوفة
        r = await client.post(
            "/api/sessions", headers=headers,
            json={"title": "test2", "default_mode": "solo", "default_agents": ["gemini"]},
        )
        sid2 = r.json()["id"]
        try:
            async with websockets.connect(f"{WS_BASE}/api/chat/ws/{sid2}") as ws:
                # نتوقّع auth_failed أو إغلاق فوري
                got_failed = False
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    got_failed = msg.get("type") == "auth_failed"
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    got_failed = True  # closed = effectively rejected
                check(got_failed, "WS rejected without token")
        except websockets.exceptions.ConnectionClosed:
            check(True, "ws closed on auth fail")
        except Exception as e:
            check(False, f"unexpected: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ فشل {len(failures)} اختبار:")
        for f in failures:
            print(f"   - {f}")
    else:
        print("✅ كل اختبارات المرحلة 2 E2E نجحت!")
    print("=" * 60)
    return len(failures) == 0


async def main():
    db_file = BACKEND_DIR / "agentforge.db"
    if db_file.exists():
        db_file.unlink()

    print(f"🚀 تشغيل السيرفر على المنفذ {PORT}...")
    log_file = open(BACKEND_DIR / "_test_phase2.log", "w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=BACKEND_DIR,
        stdout=log_file, stderr=subprocess.STDOUT, env=env,
    )

    ready = await wait_for_server(45)
    if not ready:
        print("❌ السيرفر لم يجهز")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        log_file.close()
        with open(BACKEND_DIR / "_test_phase2.log", "r", encoding="utf-8", errors="replace") as f:
            print(f.read()[:2000])
        return False

    print("✅ السيرفر جاهز")
    success = False
    try:
        success = await run_tests()
    except Exception as e:
        print(f"❌ {e}")
        import traceback
        traceback.print_exc()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        log_file.close()
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
