"""未来我 (Future Me) backend — FastAPI + SQLite.

Anonymous device auth; no payment in phase 1 (everything unlocked).
All API keys and admin-editable config live in the SQLite settings table
and are edited in the web admin console (/admin) — nothing secret comes
from env vars. User content (wishes / letters / daily sentences /
memories) is encrypted at rest (see crypto.py); the admin console only
ever sees aggregate numbers, never user text.
"""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import admin, database
from .auth import get_current_device, issue_token
from .catalog import VOICES, public_voice
from .config import settings
from .context import build_user_context
from .daily import get_daily_sentence_for_device
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


app = FastAPI(title="未来我 Future Me API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
def root():
    """Root URL has no API of its own — send browsers to the admin console."""
    return RedirectResponse("/admin", status_code=302)


@app.get("/admin", include_in_schema=False)
def admin_page():
    """Web admin console (single static page + vanilla JS)."""
    path = Path(__file__).resolve().parent / "admin.html"
    return FileResponse(path, media_type="text/html")


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


# ---------- health / auth ----------

@app.get("/api/v1/health")
def health():
    providers: list[str] = []
    if database.get_setting("dashscope.api_key"):
        providers.append("qwen")
    if database.get_setting("zhipu.api_key"):
        providers.append("zhipu")
    if database.get_setting("tencent.secret_id") and database.get_setting("tencent.secret_key"):
        providers.append("tencent")
    providers.append("edge")  # free fallback, no key needed
    return {
        "status": "ok",
        "version": app.version,
        "providers_configured": providers,
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
        text = generate_letter_text(
            wish["text"],
            wish["days"],
            provider=body.provider,
            context=build_user_context(device_id),
        )
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
    # Personalized: one AI sentence per device per day, from the future
    # self, tied to the user's own wish + context; same-day cached.
    return get_daily_sentence_for_device(device_id)


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
    return [
        {
            "id": a["id"],
            "title": a["title"],
            "body": a["body"],
            "image_url": a["image_url"],
            "start_at": a["start_at"],
            "end_at": a["end_at"],
            "active": bool(a["active"]),
        }
        for a in database.list_activities()
    ]


@app.get("/api/v1/messages")
def list_messages(device_id: str = Depends(get_current_device)):
    return [
        {"id": m["id"], "title": m["title"], "body": m["body"], "created_at": m["created_at"]}
        for m in database.list_messages()
    ]


# ---------- membership (phase 1: everything free) ----------

@app.get("/api/v1/membership/status")
def membership_status(device_id: str = Depends(get_current_device)):
    device = database.get_or_create_device(device_id)
    created = date.fromisoformat(device["created_at"])
    days_used = (date.today() - created).days
    try:
        trial_days = int(database.get_setting("membership.trial_days", "7"))
    except ValueError:
        trial_days = 7
    try:
        price = float(database.get_setting("membership.price_monthly_cny", "9.9"))
    except ValueError:
        price = 9.9
    return {
        "plan": "free_trial",
        "trial_days_left": max(0, trial_days - days_used),
        "price_monthly_cny": price,
        "paywalled": database.get_setting("membership.paywalled", "0") == "1",
    }
