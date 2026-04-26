"""
اختبار شامل للمرحلة 1 - يشغل السيرفر فعلياً ويختبر كل endpoint
"""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
import httpx


BACKEND_DIR = Path(__file__).resolve().parent.parent
PORT = 8100
BASE = f"http://127.0.0.1:{PORT}"


async def wait_for_server(timeout=45):
    for i in range(timeout):
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                r = await c.get(f"{BASE}/api/health")
                if r.status_code == 200:
                    return True
        except:
            pass
        await asyncio.sleep(1)
    return False


async def run_tests():
    print("\n" + "="*60)
    print("🧪 اختبار المرحلة 1 - Backend Foundation")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=10.0, base_url=BASE) as client:
        
        # 1. Health check
        print("\n📋 1. Health Check")
        r = await client.get("/api/health")
        assert r.status_code == 200, f"Health failed: {r.status_code}"
        data = r.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0.0"
        print(f"   ✅ /api/health: {data['app']} v{data['version']}")
        
        # 2. Signup
        print("\n📋 2. تسجيل مستخدم جديد")
        signup_data = {
            "email": "test@agentforge.com",
            "password": "test12345678",
            "full_name": "مستخدم تجريبي",
        }
        r = await client.post("/api/auth/signup", json=signup_data)
        assert r.status_code == 201, f"Signup failed: {r.status_code} - {r.text}"
        signup_resp = r.json()
        token = signup_resp["access_token"]
        user = signup_resp["user"]
        assert user["email"] == "test@agentforge.com"
        assert user["plan"] == "free"
        print(f"   ✅ تسجيل: user_id={user['id']}, plan={user['plan']}")
        
        # 3. تسجيل بإيميل مكرر يفشل
        print("\n📋 3. تكرار الإيميل يجب أن يرفض")
        r = await client.post("/api/auth/signup", json=signup_data)
        assert r.status_code == 409, f"Expected 409, got {r.status_code}"
        print(f"   ✅ رفض الإيميل المكرر (409)")
        
        # 4. Login
        print("\n📋 4. تسجيل دخول")
        r = await client.post("/api/auth/login", json={
            "email": "test@agentforge.com",
            "password": "test12345678",
        })
        assert r.status_code == 200, f"Login failed: {r.status_code}"
        login_resp = r.json()
        assert login_resp["access_token"]
        print(f"   ✅ login نجح")
        
        # 5. Login بكلمة مرور خاطئة
        print("\n📋 5. كلمة مرور خاطئة")
        r = await client.post("/api/auth/login", json={
            "email": "test@agentforge.com",
            "password": "wrong",
        })
        assert r.status_code == 401
        print(f"   ✅ رُفض (401)")
        
        # 6. /me بدون token
        print("\n📋 6. /me بدون token")
        r = await client.get("/api/auth/me")
        assert r.status_code == 401
        print(f"   ✅ رُفض (401)")
        
        # 7. /me مع token
        print("\n📋 7. /me مع token صحيح")
        headers = {"Authorization": f"Bearer {token}"}
        r = await client.get("/api/auth/me", headers=headers)
        assert r.status_code == 200
        me = r.json()
        assert me["email"] == "test@agentforge.com"
        print(f"   ✅ /me: {me['email']} (plan: {me['plan']})")
        
        # 8. قائمة الـ agents
        print("\n📋 8. قائمة الـ agents")
        r = await client.get("/api/agents", headers=headers)
        assert r.status_code == 200
        agents = r.json()
        assert len(agents) == 4, f"Expected 4 agents, got {len(agents)}"
        agent_ids = [a["id"] for a in agents]
        assert set(agent_ids) == {"claude", "gpt", "gemini", "deepseek"}
        # كل الـ agents يجب أن تكون غير متاحة (المستخدم لا يملك مفاتيح)
        for a in agents:
            assert a["available"] == False, f"{a['id']} should not be available"
        print(f"   ✅ 4 agents موجودة، كلها unavailable (لا يوجد مفاتيح)")
        
        # 9. إضافة مفتاح API
        print("\n📋 9. إضافة مفتاح API")
        r = await client.post(
            "/api/api-keys",
            headers=headers,
            json={"provider": "anthropic", "key": "sk-ant-test1234567890abcdef"},
        )
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        key_data = r.json()
        assert key_data["provider"] == "anthropic"
        assert "•" in key_data["masked_key"]  # masked
        assert "test1234" not in key_data["masked_key"]  # المفتاح الحقيقي مخفي
        print(f"   ✅ مفتاح أُضيف: {key_data['masked_key']}")
        
        # 10. Claude صار متاحاً
        print("\n📋 10. Claude صار متاحاً بعد إضافة المفتاح")
        r = await client.get("/api/agents", headers=headers)
        agents = r.json()
        claude = next(a for a in agents if a["id"] == "claude")
        assert claude["available"] == True
        assert claude["available_reason"] == "user_key"
        gpt = next(a for a in agents if a["id"] == "gpt")
        assert gpt["available"] == False  # لا مفتاح
        print(f"   ✅ Claude available={claude['available']}, reason={claude['available_reason']}")
        print(f"   ✅ GPT لا يزال غير متاح")
        
        # 11. تحديث المفتاح
        print("\n📋 11. تحديث مفتاح موجود")
        r = await client.post(
            "/api/api-keys",
            headers=headers,
            json={"provider": "anthropic", "key": "sk-ant-NEW1234567890abcdef"},
        )
        assert r.status_code == 200
        # تحقق أن لا يوجد تكرار
        r = await client.get("/api/api-keys", headers=headers)
        keys = r.json()
        assert len([k for k in keys if k["provider"] == "anthropic"]) == 1
        print(f"   ✅ التحديث نجح بدون تكرار")
        
        # 12. حذف مفتاح
        print("\n📋 12. حذف مفتاح")
        r = await client.delete("/api/api-keys/anthropic", headers=headers)
        assert r.status_code == 204
        r = await client.get("/api/api-keys", headers=headers)
        assert len(r.json()) == 0
        print(f"   ✅ المفتاح حُذف")
        
        # 13. Claude صار غير متاح مرة أخرى
        print("\n📋 13. Claude صار غير متاح بعد حذف المفتاح")
        r = await client.get("/api/agents", headers=headers)
        agents = r.json()
        claude = next(a for a in agents if a["id"] == "claude")
        assert claude["available"] == False
        print(f"   ✅ Claude available={claude['available']}")
        
        # 14. حذف مفتاح غير موجود
        print("\n📋 14. حذف مفتاح غير موجود يرجع 404")
        r = await client.delete("/api/api-keys/openai", headers=headers)
        assert r.status_code == 404
        print(f"   ✅ 404 صحيح")
        
        # 15. إضافة مفتاح بـ provider غير صالح
        print("\n📋 15. provider غير صالح يُرفض")
        r = await client.post(
            "/api/api-keys",
            headers=headers,
            json={"provider": "invalid", "key": "test1234567890"},
        )
        assert r.status_code == 422  # validation error
        print(f"   ✅ validation رفض provider خاطئ")
    
    print("\n" + "="*60)
    print("✅ كل اختبارات المرحلة 1 نجحت!")
    print("="*60)
    return True


async def main():
    # تنظيف database قديمة
    db_file = BACKEND_DIR / "agentforge.db"
    if db_file.exists():
        db_file.unlink()
        print("🗑  حذفت database قديمة")
    
    # تشغيل السيرفر
    print(f"🚀 تشغيل السيرفر على المنفذ {PORT}...")
    log_file = open(BACKEND_DIR / "_test_server.log", "w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=BACKEND_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
    )
    
    ready = await wait_for_server(timeout=45)
    if not ready:
        print("❌ السيرفر لم يجهز")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except:
            proc.kill()
        log_file.close()
        try:
            with open(BACKEND_DIR / "_test_server.log", "r", encoding="utf-8") as f:
                print("Server output:", f.read()[-2000:])
        except Exception:
            pass
        return False
    
    print("✅ السيرفر جاهز\n")
    
    success = False
    try:
        success = await run_tests()
    except AssertionError as e:
        print(f"\n❌ فشل اختبار: {e}")
    except Exception as e:
        print(f"\n❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except:
            proc.kill()
        try:
            log_file.close()
        except Exception:
            pass
        print("🛑 السيرفر متوقف")
    
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
