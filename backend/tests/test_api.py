"""Smoke tests — run with: .venv/bin/pytest tests/ -q

Covers the key flows end to end against a TestClient with an isolated
temp DATA_DIR. The TTS test does one real Edge TTS synthesis (needs
network); everything else is offline. No paid API is called: no LLM provider
key is set, so letter generation must return 503.
"""
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="futureme-test-")
os.environ["JWT_SECRET"] = "test-secret"
for k in ("DASHSCOPE_API_KEY", "ZHISHU_API_KEY", "HUNYUAN_API_KEY",
          "SILICONFLOW_API_KEY", "GENERIC_LLM_API_KEY", "GENERIC_LLM_BASE_URL",
          "GENERIC_LLM_MODEL", "TENCENT_SECRET_ID", "TENCENT_SECRET_KEY"):
    os.environ.pop(k, None)

from app.main import app  # noqa: E402
from app import database  # noqa: E402

database.init_db()  # TestClient without a context manager skips lifespan
client = TestClient(app)


@pytest.fixture(scope="module")
def token() -> str:
    r = client.post("/api/v1/auth/device", json={"device_id": "smoke-device-001"})
    assert r.status_code == 200, r.text
    assert r.json()["token"]
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "edge" in body["providers_configured"]


def test_auth_required():
    r = client.get("/api/v1/wishes")
    assert r.status_code == 401


def test_wish_flow(token):
    r = client.post(
        "/api/v1/wishes",
        json={"text": "90天后通过教师资格证考试", "category": "学习考证", "days": 90},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    wish = r.json()
    assert wish["category"] == "学习考证" and wish["days"] == 90

    r = client.get("/api/v1/wishes", headers=_auth(token))
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.get(f"/api/v1/wishes/{wish['id']}", headers=_auth(token))
    assert r.status_code == 200 and r.json()["text"].startswith("90天后")

    # invalid category / days rejected
    r = client.post(
        "/api/v1/wishes",
        json={"text": "x", "category": "玄学", "days": 90},
        headers=_auth(token),
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/wishes",
        json={"text": "x", "category": "健康身材", "days": 7},
        headers=_auth(token),
    )
    assert r.status_code == 400


def test_daily_sentence(token):
    r = client.get("/api/v1/daily-sentence", headers=_auth(token))
    assert r.status_code == 200
    assert len(r.json()["sentence"]) > 5


def test_checkin(token):
    r = client.post("/api/v1/checkin", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["checked_in_today"] is True
    assert r.json()["streak_days"] >= 1
    assert r.json()["total_days"] >= 1

    r = client.get("/api/v1/checkin/status", headers=_auth(token))
    assert r.status_code == 200 and r.json()["checked_in_today"] is True


def test_voices(token):
    r = client.get("/api/v1/voices", headers=_auth(token))
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) >= 30
    providers = {v["provider"] for v in voices}
    assert {"qwen", "zhipu", "tencent", "edge"} <= providers
    assert any(v["tier"] == "free" for v in voices)
    assert any(v["id"] == "edge-xiaoxiao" for v in voices)


def test_letter_generate_without_key_returns_503(token):
    r = client.post(
        "/api/v1/wishes",
        json={"text": "90天后跑完半程马拉松", "category": "健康身材", "days": 90},
        headers=_auth(token),
    )
    wish_id = r.json()["id"]
    r = client.post(
        "/api/v1/letters/generate",
        json={"wish_id": wish_id},
        headers=_auth(token),
    )
    assert r.status_code == 503, r.text
    assert "no LLM provider" in r.json()["detail"]


def test_llm_providers(token):
    r = client.get("/api/v1/llm/providers", headers=_auth(token))
    assert r.status_code == 200, r.text
    providers = r.json()
    assert {p["id"] for p in providers} == {
        "qwen", "hunyuan", "siliconflow", "zhipu", "generic",
    }
    # no keys set in this test env: none configured, defaults still shown
    assert all(p["configured"] is False for p in providers)
    assert {p["id"]: p["model"] for p in providers} == {
        "qwen": "qwen-plus",
        "hunyuan": "hunyuan-turbos-latest",
        "siliconflow": "Qwen/Qwen3-8B",
        "zhipu": "glm-4-flash",
        "generic": "",
    }


def test_letter_generate_invalid_provider_returns_400(token):
    r = client.post(
        "/api/v1/wishes",
        json={"text": "90天后学会游泳", "category": "健康身材", "days": 90},
        headers=_auth(token),
    )
    wish_id = r.json()["id"]
    # unknown provider id
    r = client.post(
        "/api/v1/letters/generate",
        json={"wish_id": wish_id, "provider": "doubao"},
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text
    assert "unknown LLM provider" in r.json()["detail"]
    # known provider id, but no key configured
    r = client.post(
        "/api/v1/letters/generate",
        json={"wish_id": wish_id, "provider": "zhipu"},
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text
    assert "not configured" in r.json()["detail"]


def test_tts_edge_fallback_and_audio_serving(token):
    r = client.post(
        "/api/v1/tts/synthesize",
        json={"text": "你好，这是未来我的一封信。", "voice_id": "edge-xiaoxiao"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "edge"
    assert body["audio_url"].endswith(".mp3")

    r = client.get(body["audio_url"], headers=_auth(token))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
    assert len(r.content) > 1000

    # second call hits the cache
    r2 = client.post(
        "/api/v1/tts/synthesize",
        json={"text": "你好，这是未来我的一封信。", "voice_id": "edge-xiaoxiao"},
        headers=_auth(token),
    )
    assert r2.status_code == 200 and r2.json()["cached"] is True


def test_membership_and_messages(token):
    r = client.get("/api/v1/membership/status", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free_trial"
    assert body["paywalled"] is False
    assert body["price_monthly_cny"] == 9.9
    assert body["trial_days_left"] == 7

    r = client.get("/api/v1/messages", headers=_auth(token))
    assert r.status_code == 200 and isinstance(r.json(), list)

    r = client.get("/api/v1/activities", headers=_auth(token))
    assert r.status_code == 200 and isinstance(r.json(), list)


# ---------- admin console, settings, privacy, encryption ----------

ADMIN_PASSWORD = "test-admin-123"


def _new_device_token(device_id: str) -> str:
    r = client.post("/api/v1/auth/device", json={"device_id": device_id})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_port_default_6999():
    from app.config import settings

    assert settings.PORT == 6999


def test_admin_auth_flow():
    fresh = TestClient(app)
    r = fresh.get("/api/v1/admin/status")
    assert r.status_code == 200
    assert r.json()["password_set"] is False
    assert r.json()["authenticated"] is False

    # unauthenticated admin call rejected
    r = fresh.get("/api/v1/admin/dashboard")
    assert r.status_code == 401

    # first setup sets the password and logs in (cookie)
    r = fresh.post("/api/v1/admin/setup", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # second setup is refused
    r = fresh.post("/api/v1/admin/setup", json={"password": "another-one"})
    assert r.status_code == 400

    # authed call works with the setup cookie
    r = fresh.get("/api/v1/admin/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"devices", "wishes", "letters", "checkins", "dau_today", "topics", "violations"}

    # wrong password rejected; right password logs in on a fresh client
    anon = TestClient(app)
    r = anon.post("/api/v1/admin/login", json={"password": "wrong-password"})
    assert r.status_code == 401
    r = anon.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    r = anon.get("/api/v1/admin/dashboard")
    assert r.status_code == 200

    # logout clears the session
    r = anon.post("/api/v1/admin/logout")
    assert r.status_code == 200
    r = anon.get("/api/v1/admin/dashboard")
    assert r.status_code == 401


def test_admin_settings_crud_and_masking():
    # client has the setup cookie from test_admin_auth_flow's fresh client?
    # No — use a fresh login here.
    c = TestClient(app)
    c.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})

    r = c.get("/api/v1/admin/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm.default_provider"] == "qwen"
    assert body["membership.trial_days"] == "7"
    assert body["daily.enabled"] == "1"
    # no secret value is exposed
    assert body["dashscope.api_key"] == ""

    # set a secret: stored raw, returned masked
    r = c.post("/api/v1/admin/settings", json={"settings": {"dashscope.api_key": "sk-test-123"}})
    assert r.status_code == 200, r.text
    assert r.json()["dashscope.api_key"] == "********"
    assert database.get_setting("dashscope.api_key") == "sk-test-123"

    # posting the mask keeps the existing secret
    r = c.post("/api/v1/admin/settings", json={"settings": {"dashscope.api_key": "********"}})
    assert r.status_code == 200
    assert database.get_setting("dashscope.api_key") == "sk-test-123"

    # empty string clears it
    r = c.post("/api/v1/admin/settings", json={"settings": {"dashscope.api_key": ""}})
    assert r.status_code == 200
    assert database.get_setting("dashscope.api_key") == ""

    # unknown key rejected
    r = c.post("/api/v1/admin/settings", json={"settings": {"no.such.key": "x"}})
    assert r.status_code == 400

    # invalid provider rejected
    r = c.post("/api/v1/admin/settings", json={"settings": {"llm.default_provider": "doubao"}})
    assert r.status_code == 400


def test_membership_config_effect():
    c = TestClient(app)
    c.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})
    tok = _new_device_token("member-config-device")

    r = c.post(
        "/api/v1/admin/settings",
        json={"settings": {
            "membership.trial_days": "14",
            "membership.price_monthly_cny": "19.9",
            "membership.paywalled": "1",
        }},
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/v1/membership/status", headers=_auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["trial_days_left"] == 14
    assert body["price_monthly_cny"] == 19.9
    assert body["paywalled"] is True

    # restore defaults (later tests rely on them)
    c.post(
        "/api/v1/admin/settings",
        json={"settings": {
            "membership.trial_days": "7",
            "membership.price_monthly_cny": "9.9",
            "membership.paywalled": "0",
        }},
    )
    r = client.get("/api/v1/membership/status", headers=_auth(tok))
    assert r.json()["trial_days_left"] == 7
    assert r.json()["paywalled"] is False


def test_admin_message_crud(token):
    c = TestClient(app)
    c.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})

    r = c.post("/api/v1/admin/messages", json={
        "title": "测试推送", "body": "这是一条测试消息", "audience": "all", "active": True,
    })
    assert r.status_code == 201, r.text
    msg_id = r.json()["id"]

    # public endpoint (what the app pulls on open) shows it
    r = client.get("/api/v1/messages", headers=_auth(token))
    assert any(m["id"] == msg_id and m["title"] == "测试推送" for m in r.json())

    r = c.put(f"/api/v1/admin/messages/{msg_id}", json={
        "title": "测试推送·改", "body": "改过的内容", "audience": "new", "active": False,
    })
    assert r.status_code == 200 and r.json()["title"] == "测试推送·改"

    r = c.delete(f"/api/v1/admin/messages/{msg_id}")
    assert r.status_code == 200
    r = client.get("/api/v1/messages", headers=_auth(token))
    assert not any(m["id"] == msg_id for m in r.json())


def test_admin_activity_crud(token):
    c = TestClient(app)
    c.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})

    r = c.post("/api/v1/admin/activities", json={
        "title": "测试活动", "body": "活动内容", "active": True,
    })
    assert r.status_code == 201, r.text
    act_id = r.json()["id"]

    r = client.get("/api/v1/activities", headers=_auth(token))
    assert any(a["id"] == act_id for a in r.json())

    r = c.put(f"/api/v1/admin/activities/{act_id}", json={
        "title": "测试活动·改", "body": "改过", "active": True,
    })
    assert r.status_code == 200 and r.json()["title"] == "测试活动·改"

    r = c.delete(f"/api/v1/admin/activities/{act_id}")
    assert r.status_code == 200
    r = client.get("/api/v1/activities", headers=_auth(token))
    assert not any(a["id"] == act_id for a in r.json())


def test_daily_sentence_personalized_and_cached():
    tok = _new_device_token("daily-device-001")
    r = client.post(
        "/api/v1/wishes",
        json={"text": "90天后升职成为小组长", "category": "事业升职/换工作", "days": 90},
        headers=_auth(tok),
    )
    assert r.status_code == 201, r.text

    with patch("app.daily.generate_daily_sentence", return_value="你做到了，站在新的起点上。") as mock_gen:
        r = client.get("/api/v1/daily-sentence", headers=_auth(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sentence"] == "你做到了，站在新的起点上。"
        assert body["text"] == body["sentence"]  # App DTO reads `text`
        assert body["personalized"] is True
        assert body["cached"] is False
        assert mock_gen.call_count == 1

        # same day: cached, LLM NOT called again
        r = client.get("/api/v1/daily-sentence", headers=_auth(tok))
        assert r.status_code == 200
        assert r.json()["sentence"] == "你做到了，站在新的起点上。"
        assert r.json()["cached"] is True
        assert mock_gen.call_count == 1


def test_daily_sentence_fallback_without_llm():
    tok = _new_device_token("daily-device-002")
    r = client.post(
        "/api/v1/wishes",
        json={"text": "90天后跑完人生第一个半马", "category": "健康身材", "days": 90},
        headers=_auth(tok),
    )
    assert r.status_code == 201, r.text
    # no LLM key configured in the test DB -> generic fallback
    r = client.get("/api/v1/daily-sentence", headers=_auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["personalized"] is False
    assert body["fallback"] == "generic"
    assert len(body["sentence"]) > 5


def test_memory_recorded_and_context_assembled():
    tok = _new_device_token("memory-device-001")
    marker = "MEMORY-MARKER-9f2c-愿望"
    r = client.post(
        "/api/v1/wishes",
        json={"text": marker + "：90天后成为小组长", "category": "事业升职/换工作", "days": 90},
        headers=_auth(tok),
    )
    assert r.status_code == 201, r.text
    device_id = database.get_or_create_device("memory-device-001")["device_id"]

    # wish -> milestone memory (decrypted in memory)
    mems = database.list_memories(device_id)
    assert any(m["kind"] == "milestone" and marker in m["text"] for m in mems)

    # 7-day checkin streak -> progress memory
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    for i in range(1, 7):
        d = (date.today() - timedelta(days=i)).isoformat()
        conn.execute("INSERT INTO checkins (device_id, checkin_date) VALUES (?, ?)", (device_id, d))
    conn.commit()
    conn.close()
    r = client.post("/api/v1/checkin", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["streak_days"] == 7
    mems = database.list_memories(device_id)
    assert any(m["kind"] == "progress" and "7" in m["text"] for m in mems)

    # context assembly sees the decrypted wish + memory
    from app.context import build_user_context

    ctx = build_user_context(device_id)
    assert marker in ctx
    assert "连续 7 天" in ctx


def test_encryption_at_rest_roundtrip_and_migration():
    tok = _new_device_token("encrypt-device-001")
    marker = "ENCRYPT-MARKER-5b7e-愿望"
    r = client.post(
        "/api/v1/wishes",
        json={"text": marker + "：90天后升职", "category": "事业升职/换工作", "days": 90},
        headers=_auth(tok),
    )
    assert r.status_code == 201, r.text
    wish_id = r.json()["id"]
    device_id = database.get_or_create_device("encrypt-device-001")["device_id"]
    database.create_letter(device_id, wish_id, None, "LETTER-MARKER-1a4d-信件内容", "2026-12-19")
    database.create_memory(device_id, "note", "MEMORY-MARKER-3c8f-记忆内容", importance=2)
    database.create_daily_message(device_id, wish_id, date.today().isoformat(), "DAILY-MARKER-6e21-每日一句")

    # raw DB rows are ciphertext: no plaintext marker anywhere
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    for table in ("wishes", "letters", "memories", "daily_messages"):
        rows = conn.execute(f"SELECT text FROM {table}").fetchall()
        for (raw,) in rows:
            assert "MARKER" not in raw, f"plaintext leaked in {table}"
    conn.close()

    # read/write roundtrip still returns the original plaintext
    r = client.get(f"/api/v1/wishes/{wish_id}", headers=_auth(tok))
    assert r.status_code == 200 and marker in r.json()["text"]
    mems = database.list_memories(device_id)
    assert any("MEMORY-MARKER-3c8f" in m["text"] for m in mems)

    # key file exists with mode 0600
    key_path = Path(database.settings.DATA_DIR) / ".encryption.key"
    assert key_path.exists()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    # legacy plaintext migration: insert a raw plaintext row, re-init, it gets encrypted
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    conn.execute(
        "INSERT INTO wishes (device_id, text, category, days, created_at)"
        " VALUES (?, ?, ?, ?, datetime('now'))",
        (device_id, "LEGACY-PLAIN-8d02-旧明文", "财富收入", 30),
    )
    conn.commit()
    conn.close()
    database.init_db()
    conn = sqlite3.connect(str(database.settings.DB_PATH))
    raw = conn.execute(
        "SELECT text FROM wishes WHERE device_id = ? AND category = '财富收入'",
        (device_id,),
    ).fetchone()
    conn.close()
    assert raw is not None and "LEGACY-PLAIN" not in raw[0], "migration did not encrypt legacy row"
    legacy = [w for w in database.list_wishes(device_id) if w["category"] == "财富收入"]
    assert legacy and "LEGACY-PLAIN-8d02" in legacy[0]["text"]


def test_admin_never_returns_user_text():
    c = TestClient(app)
    c.post("/api/v1/admin/login", json={"password": ADMIN_PASSWORD})
    tok = _new_device_token("privacy-device-001")
    wish_marker = "PRIVACY-WISH-77aa-愿望原文"
    letter_marker = "PRIVACY-LETTER-88bb-信件原文"
    memory_marker = "PRIVACY-MEMORY-99cc-记忆原文"
    daily_marker = "PRIVACY-DAILY-00dd-每日一句原文"
    r = client.post(
        "/api/v1/wishes",
        json={"text": wish_marker, "category": "脱单恋爱", "days": 30},
        headers=_auth(tok),
    )
    wish_id = r.json()["id"]
    device_id = database.get_or_create_device("privacy-device-001")["device_id"]
    database.create_letter(device_id, wish_id, None, letter_marker, "2026-12-19")
    database.create_memory(device_id, "note", memory_marker, importance=1)
    database.create_daily_message(device_id, wish_id, date.today().isoformat(), daily_marker)

    markers = [wish_marker, letter_marker, memory_marker, daily_marker]
    for path in ("/api/v1/admin/dashboard", "/api/v1/admin/settings",
                 "/api/v1/admin/messages", "/api/v1/admin/activities"):
        r = c.get(path)
        assert r.status_code == 200, path
        blob = json.dumps(r.json(), ensure_ascii=False)
        for m in markers:
            assert m not in blob, f"user text leaked in {path}: {m}"

    # aggregates still work: the new wish is counted, not shown
    dash = c.get("/api/v1/admin/dashboard").json()
    assert dash["wishes"] >= 1
    assert any(t["category"] == "脱单恋爱" and t["wishes"] >= 1 for t in dash["topics"])


def test_decrypt_export_tool():
    db_path = database.settings.DB_PATH
    key_path = Path(database.settings.DATA_DIR) / ".encryption.key"
    out_dir = Path(tempfile.mkdtemp(prefix="futureme-export-"))
    out_path = out_dir / "export.json"
    r = subprocess.run(
        [sys.executable, "scripts/decrypt_export.py",
         "--db", str(db_path), "--key", str(key_path),
         "--out", str(out_path), "--operator", "test-runner"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(out_path.read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False)
    # the tool can decrypt what the DB stores encrypted
    assert "ENCRYPT-MARKER-5b7e" in blob
    assert "PRIVACY-WISH-77aa" in blob

    # audit log: one entry, operator + types, no content
    audit_path = out_path.with_suffix(".audit.log")
    assert audit_path.exists()
    audit = audit_path.read_text(encoding="utf-8")
    assert "test-runner" in audit
    assert "wishes" in audit
    assert "ENCRYPT-MARKER" not in audit
    assert "PRIVACY-WISH" not in audit
