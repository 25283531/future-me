"""Web admin console backend (/api/v1/admin/*).

Auth: no env-var password. First visit sets a password (scrypt hash stored
in the settings table); afterwards a login form issues a random session
token stored in the DB and sent as an HttpOnly cookie. All admin endpoints
require a valid session.

PRIVACY RED LINE: the admin console only ever sees AGGREGATE numbers —
totals, per-category wish counts, per-type violation counts. It never
returns any single user's content (no wish/letter/memory/daily-sentence
text, no device list, no export). Memory contents exist only for the
server to assemble LLM context in memory.
"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import database, mail
from .accounts import hash_password, verify_password
from .llm import PROVIDER_NAMES

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN_COOKIE = "fm_admin_session"


def _password_set() -> bool:
    return bool(database.get_setting("admin.password_hash", ""))


def _new_session(response: Response) -> None:
    token, max_age = database.create_admin_session()
    response.set_cookie(
        ADMIN_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", path="/",
    )


def require_admin(request: Request) -> str:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token or not database.admin_session_valid(token):
        raise HTTPException(status_code=401, detail="admin login required")
    return token


def _is_admin(request: Request) -> bool:
    token = request.cookies.get(ADMIN_COOKIE)
    return bool(token) and database.admin_session_valid(token)


# ---- auth endpoints ----

class PasswordIn(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


@router.get("/status")
def admin_status(request: Request):
    return {"password_set": _password_set(), "authenticated": _is_admin(request)}


@router.post("/setup")
def admin_setup(body: PasswordIn, response: Response):
    if _password_set():
        raise HTTPException(status_code=400, detail="admin password already set")
    database.set_setting("admin.password_hash", hash_password(body.password))
    _new_session(response)
    return {"ok": True}


@router.post("/login")
def admin_login(body: PasswordIn, response: Response):
    stored = database.get_setting("admin.password_hash", "")
    if not stored or not verify_password(body.password, stored):
        raise HTTPException(status_code=401, detail="wrong password")
    _new_session(response)
    return {"ok": True}


@router.post("/logout")
def admin_logout(request: Request, response: Response):
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        database.delete_admin_session(token)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


# ---- dashboard: aggregates only ----

@router.get("/dashboard")
def admin_dashboard(request: Request):
    require_admin(request)
    return database.dashboard_stats()


# ---- settings ----

# Keys the admin console may read/write. Secrets are masked on read and the
# mask sentinel means "keep the existing value" on write.
SETTABLE_KEYS = set(database.DEFAULT_SETTINGS) - {"admin.password_hash", "auth.jwt_secret"}
TTS_PROVIDERS = {"qwen", "zhipu", "tencent", "edge"}


def _masked_settings() -> dict[str, str]:
    all_settings = database.get_all_settings()
    out: dict[str, str] = {}
    for key in sorted(SETTABLE_KEYS):
        val = all_settings.get(key, "")
        if key in database.SECRET_SETTINGS:
            out[key] = database.SETTING_MASK if val else ""
        else:
            out[key] = val
    return out


def _validate_settings(values: dict) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, raw in values.items():
        if key not in SETTABLE_KEYS:
            raise HTTPException(status_code=400, detail=f"unknown setting: {key}")
        if key in database.SECRET_SETTINGS:
            if raw is None:
                continue
            val = str(raw)
            if val == database.SETTING_MASK:
                continue  # keep existing secret
            cleaned[key] = val.strip()
            continue
        if key == "llm.default_provider":
            val = str(raw).strip()
            if val not in PROVIDER_NAMES:
                raise HTTPException(status_code=400, detail=f"unknown LLM provider: {val}")
            cleaned[key] = val
        elif key == "tts.default_provider":
            val = str(raw).strip()
            if val not in TTS_PROVIDERS:
                raise HTTPException(status_code=400, detail=f"unknown TTS provider: {val}")
            cleaned[key] = val
        elif key in ("membership.paywalled", "daily.enabled",
                     "memory.evolution_enabled", "memory.reflection_enabled") or key.endswith(".enabled"):
            cleaned[key] = "1" if raw in (True, 1, "1", "true", "on") else "0"
        elif key == "memory.consolidation_interval_days":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="consolidation interval must be an integer")
            if not 1 <= n <= 7:
                raise HTTPException(status_code=400, detail="consolidation interval must be 1-7 days")
            cleaned[key] = str(n)
        elif key == "membership.trial_days":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="trial_days must be an integer")
            if not 0 <= n <= 365:
                raise HTTPException(status_code=400, detail="trial_days must be 0-365")
            cleaned[key] = str(n)
        elif key == "membership.price_monthly_cny":
            try:
                n = float(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="price must be a number")
            if n < 0:
                raise HTTPException(status_code=400, detail="price must be >= 0")
            cleaned[key] = str(n)
        elif key == "daily.max_chars":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="max_chars must be an integer")
            if not 10 <= n <= 200:
                raise HTTPException(status_code=400, detail="max_chars must be 10-200")
            cleaned[key] = str(n)
        elif key == "daily.fallback_mode":
            val = str(raw).strip()
            if val not in ("generic", "previous"):
                raise HTTPException(status_code=400, detail="fallback_mode must be generic or previous")
            cleaned[key] = val
        elif key == "smtp.port":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="smtp port must be an integer")
            if not 1 <= n <= 65535:
                raise HTTPException(status_code=400, detail="smtp port must be 1-65535")
            cleaned[key] = str(n)
        elif key == "smtp.security":
            val = str(raw).strip().lower()
            if val not in ("tls", "ssl", "none"):
                raise HTTPException(status_code=400, detail="smtp security must be tls, ssl or none")
            cleaned[key] = val
        else:
            cleaned[key] = str(raw).strip() if raw is not None else ""
    return cleaned


class SettingsIn(BaseModel):
    settings: dict = Field(default_factory=dict)


@router.get("/settings")
def get_settings(request: Request):
    require_admin(request)
    return _masked_settings()


@router.post("/settings")
def set_settings(body: SettingsIn, request: Request):
    require_admin(request)
    cleaned = _validate_settings(body.settings)
    if cleaned:
        database.set_settings(cleaned)
    return _masked_settings()


# ---- messages (push / marketing; admin-authored, shown to all users) ----

class MessageIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=2000)
    audience: str = "all"
    active: bool = True


@router.get("/messages")
def admin_list_messages(request: Request):
    require_admin(request)
    return database.list_messages(include_inactive=True)


@router.post("/messages", status_code=201)
def admin_create_message(body: MessageIn, request: Request):
    require_admin(request)
    return database.create_message(body.title.strip(), body.body.strip(), body.audience.strip() or "all")


@router.put("/messages/{msg_id}")
def admin_update_message(msg_id: str, body: MessageIn, request: Request):
    require_admin(request)
    updated = database.update_message(
        msg_id,
        {"title": body.title.strip(), "body": body.body.strip(),
         "audience": body.audience.strip() or "all", "active": 1 if body.active else 0},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="message not found")
    return updated


@router.delete("/messages/{msg_id}")
def admin_delete_message(msg_id: str, request: Request):
    require_admin(request)
    if not database.delete_message(msg_id):
        raise HTTPException(status_code=404, detail="message not found")
    return {"ok": True}


# ---- activities ----

class ActivityIn(BaseModel):
    id: str | None = None
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=2000)
    image_url: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    active: bool = True


@router.get("/activities")
def admin_list_activities(request: Request):
    require_admin(request)
    return database.list_activities(include_inactive=True)


@router.post("/activities", status_code=201)
def admin_create_activity(body: ActivityIn, request: Request):
    require_admin(request)
    return database.create_activity(
        {
            "id": (body.id or "").strip() or None,
            "title": body.title.strip(),
            "body": body.body.strip(),
            "image_url": (body.image_url or "").strip() or None,
            "start_at": (body.start_at or "").strip() or None,
            "end_at": (body.end_at or "").strip() or None,
            "active": body.active,
        }
    )


@router.put("/activities/{act_id}")
def admin_update_activity(act_id: str, body: ActivityIn, request: Request):
    require_admin(request)
    updated = database.update_activity(
        act_id,
        {
            "title": body.title.strip(),
            "body": body.body.strip(),
            "image_url": (body.image_url or "").strip() or None,
            "start_at": (body.start_at or "").strip() or None,
            "end_at": (body.end_at or "").strip() or None,
            "active": 1 if body.active else 0,
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="activity not found")
    return updated


@router.delete("/activities/{act_id}")
def admin_delete_activity(act_id: str, request: Request):
    require_admin(request)
    if not database.delete_activity(act_id):
        raise HTTPException(status_code=404, detail="activity not found")
    return {"ok": True}


# ---- SMTP (verification / password-reset emails) ----

@router.get("/smtp/status")
def admin_smtp_status(request: Request):
    require_admin(request)
    return mail.smtp_status()


class SmtpTestIn(BaseModel):
    to: str = Field(..., min_length=3, max_length=254)


@router.post("/smtp/test")
def admin_smtp_test(body: SmtpTestIn, request: Request):
    """Send a test email. Fails clearly when SMTP is not configured —
    the admin console must show that state instead of pretending mail
    works."""
    require_admin(request)
    from .accounts import valid_email

    if not valid_email(body.to.strip()):
        raise HTTPException(status_code=400, detail="invalid email address")
    ok, detail = mail.send_test_email(body.to.strip())
    if not ok:
        raise HTTPException(status_code=502, detail=detail)
    return {"ok": True, "detail": detail}
