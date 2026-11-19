"""Smoke tests — run with: .venv/bin/pytest tests/ -q

Covers the key flows end to end against a TestClient with an isolated
temp DATA_DIR. The TTS test does one real Edge TTS synthesis (needs
network); everything else is offline. No paid API is called: no LLM provider
key is set, so letter generation must return 503.
"""
import os
import tempfile

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
