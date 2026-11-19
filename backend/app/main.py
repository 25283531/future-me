"""未来我 (Future Me) backend — FastAPI + SQLite.

Anonymous device auth; no payment in phase 1 (everything unlocked).
All keys come from env vars only. See .env.example.
"""
import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import database
from .auth import get_current_device, issue_token
from .catalog import VOICES, daily_sentence, public_voice
from .config import settings
from .llm import (
    LLMError,
    LLMNotConfigured,
    LLMProviderError,
    generate_letter_text,
    list_llm_providers,
)
from .tts import TTSUnavailable, synthesize

CATEGORIES = ["事业升职/换工作", "财富收入", "脱单恋爱", "健康身材", "学习考证", "家庭亲子"]
ALLOWED_DAYS = [30, 90, 365]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    settings.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="未来我 Future Me API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas ----------

class DeviceAuthIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)


class WishIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    category: str
    days: int


class LetterGenerateIn(BaseModel):
    wish_id: int
    voice_id: str | None = None
    provider: str | None = None  # LLM provider id; defaults to LLM_PROVIDER


class TTSIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    voice_id: str


# ---------- helpers ----------

def _load_json_file(name: str) -> list[dict]:
    path = settings.DATA_DIR / name
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


# ---------- health / auth ----------

@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "providers_configured": settings.configured_providers,
    }


@app.post("/api/v1/auth/device")
def auth_device(body: DeviceAuthIn):
    device = database.get_or_create_device(body.device_id.strip())
    return {"token": issue_token(device["device_id"]), "device_id": device["device_id"]}


# ---------- wishes ----------

@app.post("/api/v1/wishes", status_code=status.HTTP_201_CREATED)
def create_wish(body: WishIn, device_id: str = Depends(get_current_device)):
    if body.category not in CATEGORIES:
        raise HTTPException(
            status_code=400, detail=f"category must be one of {CATEGORIES}"
        )
    if body.days not in ALLOWED_DAYS:
        raise HTTPException(
            status_code=400, detail=f"days must be one of {ALLOWED_DAYS}"
        )
    return database.create_wish(device_id, body.text.strip(), body.category, body.days)


@app.get("/api/v1/wishes")
def list_wishes(device_id: str = Depends(get_current_device)):
    return database.list_wishes(device_id)


@app.get("/api/v1/wishes/{wish_id}")
def get_wish(wish_id: int, device_id: str = Depends(get_current_device)):
    wish = database.get_wish(device_id, wish_id)
    if not wish:
        raise HTTPException(status_code=404, detail="wish not found")
    return wish


# ---------- letters ----------

@app.post("/api/v1/letters/generate", status_code=status.HTTP_201_CREATED)
def generate_letter(body: LetterGenerateIn, device_id: str = Depends(get_current_device)):
    wish = database.get_wish(device_id, body.wish_id)
    if not wish:
        raise HTTPException(status_code=404, detail="wish not found")
    if body.voice_id and body.voice_id not in {v["id"] for v in VOICES}:
        raise HTTPException(status_code=400, detail=f"unknown voice_id: {body.voice_id}")
    try:
        text = generate_letter_text(wish["text"], wish["days"], provider=body.provider)
    except LLMProviderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    target = date.today() + timedelta(days=wish["days"])
    letter = database.create_letter(
        device_id, wish["id"], body.voice_id, text, target.isoformat()
    )
    letter["ai_generated"] = True  # app must label letters as AI-generated
    return letter


@app.get("/api/v1/letters")
def list_letters(device_id: str = Depends(get_current_device)):
    return database.list_letters(device_id)


@app.get("/api/v1/letters/{letter_id}")
def get_letter(letter_id: int, device_id: str = Depends(get_current_device)):
    letter = database.get_letter(device_id, letter_id)
    if not letter:
        raise HTTPException(status_code=404, detail="letter not found")
    return letter


# ---------- LLM providers ----------

@app.get("/api/v1/llm/providers")
def list_providers(device_id: str = Depends(get_current_device)):
    return list_llm_providers()


# ---------- voices / TTS ----------

@app.get("/api/v1/voices")
def list_voices(device_id: str = Depends(get_current_device)):
    return [public_voice(v) for v in VOICES]


@app.post("/api/v1/tts/synthesize")
def tts_synthesize(body: TTSIn, request: Request, device_id: str = Depends(get_current_device)):
    try:
        path, provider, cached = synthesize(body.text, body.voice_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TTSUnavailable as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "audio_url": str(request.url_for("serve_audio", filename=path.name)),
        "provider": provider,
        "cached": cached,
        "voice_id": body.voice_id,
    }


@app.get("/audio/{filename}", name="serve_audio")
def serve_audio(filename: str):
    path = settings.AUDIO_DIR / Path(filename).name
    if not path.exists() or path.suffix.lower() != ".mp3":
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(path, media_type="audio/mpeg", filename=filename)


# ---------- daily sentence / check-in ----------

@app.get("/api/v1/daily-sentence")
def get_daily_sentence(device_id: str = Depends(get_current_device)):
    return daily_sentence()


@app.post("/api/v1/checkin")
def checkin(device_id: str = Depends(get_current_device)):
    database.checkin_today(device_id)
    return database.checkin_status(device_id)


@app.get("/api/v1/checkin/status")
def checkin_status(device_id: str = Depends(get_current_device)):
    return database.checkin_status(device_id)


# ---------- activities / messages (fetch-on-open) ----------

@app.get("/api/v1/activities")
def list_activities(device_id: str = Depends(get_current_device)):
    return [a for a in _load_json_file("activities.json") if a.get("active", True)]


@app.get("/api/v1/messages")
def list_messages(device_id: str = Depends(get_current_device)):
    msgs = _load_json_file("messages.json")
    msgs.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return msgs


# ---------- membership (phase 1: everything free) ----------

@app.get("/api/v1/membership/status")
def membership_status(device_id: str = Depends(get_current_device)):
    device = database.get_or_create_device(device_id)
    created = date.fromisoformat(device["created_at"])
    days_used = (date.today() - created).days
    return {
        "plan": "free_trial",
        "trial_days_left": max(0, settings.TRIAL_DAYS - days_used),
        "price_monthly_cny": settings.PRICE_MONTHLY_CNY,
        "paywalled": False,
    }
