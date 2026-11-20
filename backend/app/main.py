"""未来我 (Future Me) backend — FastAPI + SQLite.

Anonymous device auth + optional email accounts (see accounts.py); no
payment in phase 1 (everything unlocked). All API keys and
admin-editable config live in the SQLite settings table and are edited
in the web admin console (/admin) — nothing secret comes from env vars.
User content (wishes / letters / daily sentences / memories) is
encrypted at rest (see crypto.py); the admin console only ever sees
aggregate numbers, never user text.
"""
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import accounts, admin, database, evolution, mail, privacy
from .auth import (
    AuthContext,
    get_current_auth,
    get_current_device,
    issue_token,
    require_account,
)
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


def client_ip(request: Request) -> str:
    """Real client IP: first X-Forwarded-For hop when behind a proxy
    (the public domain), else the direct peer address."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


# ---------- email accounts (registration is optional; anonymous use works) ----------

class RegisterIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    device_id: str = Field(..., min_length=1, max_length=128)
    captcha_challenge_id: str = Field(..., min_length=1, max_length=64)
    captcha_answer: str = Field(..., min_length=1, max_length=16)


class LoginIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    device_id: str = Field(..., min_length=1, max_length=128)


class CodeIn(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class EmailIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ResetPasswordIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class DeleteAccountIn(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


@app.get("/api/v1/auth/captcha")
def auth_captcha():
    """Image captcha for registration (SVG, no third-party service)."""
    challenge_id, svg = accounts.create_captcha()
    return {"challenge_id": challenge_id, "svg": svg}


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def auth_register(body: RegisterIn, request: Request):
    if not accounts.register_allowed(client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="注册太频繁，请稍后再试",
        )
    email = body.email.strip().lower()
    if not accounts.valid_email(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    if not accounts.valid_password(body.password):
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    if not accounts.validate_captcha(body.captcha_challenge_id, body.captcha_answer):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请重新获取")
    if database.get_user_by_email(email) is not None:
        raise HTTPException(status_code=400, detail="该邮箱已注册，请直接登录")
    user = database.create_user(email, accounts.hash_password(body.password))
    device_id = body.device_id.strip()
    database.get_or_create_device(device_id)
    database.link_device_to_user(device_id, user["id"])
    # Verification email: best effort. Without SMTP the account is still
    # created and usable unverified; verification waits for SMTP config.
    email_sent = False
    if mail.smtp_configured():
        code = accounts.issue_verification_code(user["id"])
        email_sent = mail.send_verification_email(email, code)
    return {
        "token": issue_token(device_id, user_id=user["id"]),
        "user": accounts.public_user(user),
        "email_sent": email_sent,
        "email_verified": False,
    }


@app.post("/api/v1/auth/login")
def auth_login(body: LoginIn, request: Request):
    email = body.email.strip().lower()
    if not accounts.login_allowed(client_ip(request), email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试太频繁，请稍后再试",
        )
    user = database.get_user_by_email(email)
    if user is None or not accounts.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    device_id = body.device_id.strip()
    database.get_or_create_device(device_id)
    database.link_device_to_user(device_id, user["id"])
    database.update_user(user["id"], {"last_login_at": database._now_iso()})
    return {
        "token": issue_token(device_id, user_id=user["id"]),
        "user": accounts.public_user(user),
        "email_verified": bool(user["email_verified"]),
    }


@app.get("/api/v1/auth/me")
def auth_me(auth: AuthContext = Depends(get_current_auth)):
    account = None
    if auth.user_id is not None:
        user = database.get_user(auth.user_id)
        if user is not None:
            account = accounts.public_user(user)
    return {"device_id": auth.device_id, "account": account}


@app.post("/api/v1/auth/verify-email")
def auth_verify_email(body: CodeIn, auth: AuthContext = Depends(require_account)):
    user = database.get_user(auth.user_id)
    if user is None or not accounts.verify_email_code(user, body.code.strip()):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    database.update_user(auth.user_id, {"email_verified": 1})
    return {"ok": True, "user": accounts.public_user(database.get_user(auth.user_id))}


@app.post("/api/v1/auth/resend-verification")
def auth_resend_verification(auth: AuthContext = Depends(require_account)):
    user = database.get_user(auth.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="account login required")
    if user["email_verified"]:
        return {"ok": True, "already_verified": True, "email_sent": False}
    if not accounts.verify_send_allowed(user["email"]):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="发送太频繁，请稍后再试",
        )
    if not mail.smtp_configured():
        return {
            "ok": True,
            "email_sent": False,
            "detail": "邮件服务未配置，暂无法发送验证邮件",
        }
    code = accounts.issue_verification_code(user["id"])
    sent = mail.send_verification_email(user["email"], code)
    return {"ok": True, "email_sent": sent}


@app.post("/api/v1/auth/forgot-password")
def auth_forgot_password(body: EmailIn, request: Request):
    """Always returns the same generic response — it never reveals
    whether an email exists, is verified, or has SMTP configured."""
    email = body.email.strip().lower()
    if accounts.verify_send_allowed(email):
        user = database.get_user_by_email(email)
        if user is not None and user["email_verified"] and mail.smtp_configured():
            code = accounts.issue_reset_code(user["id"])
            mail.send_reset_email(email, code)
    return {
        "ok": True,
        "message": "如果该邮箱已注册且已验证，重置密码的邮件已发送，请查收（10 分钟内有效）。",
    }


@app.post("/api/v1/auth/reset-password")
def auth_reset_password(body: ResetPasswordIn):
    email = body.email.strip().lower()
    user = database.get_user_by_email(email)
    # Same error for unknown email / unverified email / wrong code:
    # recovery must not reveal whether an account exists.
    if user is None or not user["email_verified"]:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    if not accounts.valid_password(body.new_password):
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if not accounts.verify_reset_code(user, body.code.strip()):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    database.update_user(user["id"], {"password_hash": accounts.hash_password(body.new_password)})
    return {"ok": True}


@app.post("/api/v1/auth/change-password")
def auth_change_password(body: ChangePasswordIn, auth: AuthContext = Depends(require_account)):
    user = database.get_user(auth.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="account login required")
    if not user["email_verified"]:
        raise HTTPException(status_code=403, detail="请先验证邮箱")
    if not accounts.valid_password(body.new_password):
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    if not accounts.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    database.update_user(
        auth.user_id, {"password_hash": accounts.hash_password(body.new_password)}
    )
    return {"ok": True}


@app.post("/api/v1/auth/delete-account")
def auth_delete_account(body: DeleteAccountIn, auth: AuthContext = Depends(require_account)):
    """Delete the account AND all server-side data of its linked devices
    (wishes, letters, check-ins, memories, persona, daily messages).
    The device can re-register anonymously afterwards."""
    user = database.get_user(auth.user_id)
    if user is None or not accounts.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="密码不正确")
    for device_id in database.get_devices_for_user(auth.user_id):
        database.delete_device_data(device_id)
    database.delete_user(auth.user_id)
    return {"ok": True}


# ---------- privacy policy ----------

@app.get("/privacy", include_in_schema=False)
def privacy_page():
    """Human-readable policy page (browsers)."""
    return HTMLResponse(privacy.privacy_html())


@app.get("/api/v1/privacy")
def privacy_json(device_id: str = Depends(get_current_device)):
    """Policy as JSON for the app (with a bundled offline copy as fallback)."""
    return {
        "version": privacy.PRIVACY_VERSION,
        "updated_at": privacy.PRIVACY_UPDATED,
        "text": privacy.PRIVACY_TEXT,
    }


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
    wish = database.create_wish(device_id, body.text.strip(), body.category, body.days)
    evolution.after_interaction(device_id, event="wish")
    return wish


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
    evolution.after_interaction(device_id, event="letter")
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
    status = database.checkin_status(device_id)
    evolution.after_interaction(
        device_id, event="checkin", streak=status["streak_days"]
    )
    return status


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
def membership_status(auth: AuthContext = Depends(get_current_auth)):
    # Per-account once logged in (trial counts from account creation);
    # anonymous devices keep the old per-device trial.
    if auth.user_id is not None:
        user = database.get_user(auth.user_id)
        created = (
            date.fromisoformat(user["created_at"][:10])
            if user is not None
            else date.fromisoformat(
                database.get_or_create_device(auth.device_id)["created_at"]
            )
        )
        account = True
        email_verified = bool(user["email_verified"]) if user is not None else False
    else:
        device = database.get_or_create_device(auth.device_id)
        created = date.fromisoformat(device["created_at"])
        account = False
        email_verified = False
    days_used = (date.today() - created).days
    try:
        trial_days = int(database.get_setting("membership.trial_days", "7"))
    except ValueError:
        trial_days = 7
    try:
        price = float(database.get_setting("membership.price_monthly_cny", "9.9"))
    except ValueError:
        price = 9.9
    paywalled = database.get_setting("membership.paywalled", "0") == "1"
    days_left = max(0, trial_days - days_used)
    status = "trial" if days_left > 0 else ("expired" if paywalled else "free")
    return {
        "plan": "free_trial",
        "status": status,
        "trial_days_left": days_left,
        "price_monthly_cny": price,
        "paywalled": paywalled,
        "account": account,
        "email_verified": email_verified,
    }
