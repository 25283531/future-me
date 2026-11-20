"""Email accounts + registration anti-bot (stdlib only, no third party).

- Passwords and one-time codes are stored as scrypt hashes only.
- Registration anti-bot: server-side rate limits (SQLite, survive
  restarts) + a lightweight image captcha rendered as SVG (pure stdlib,
  no PIL, no external keys).
- An UNVERIFIED user can log in and use the app normally. Password
  change and password recovery REQUIRE a verified email.
- Forgot-password never reveals whether an email exists: the endpoint
  always returns the same generic response.
"""
import hashlib
import hmac
import random
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import database

# ---- password hashing (hashlib.scrypt, no extra deps) ----
# Shared with the admin console (admin.py imports these).

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = bytes.fromhex(parts[4])
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32
        )
        return hmac.compare_digest(dk.hex(), parts[5])
    except (ValueError, TypeError):
        return False


# ---- validation ----

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str) -> bool:
    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email))


def valid_password(password: str) -> bool:
    return 8 <= len(password) <= 128


def public_user(user: dict) -> dict:
    """What the API may return about an account: no hashes, no codes."""
    return {
        "id": user["id"],
        "email": user["email"],
        "email_verified": bool(user["email_verified"]),
        "created_at": user["created_at"],
    }


# ---- one-time codes (6 digits, 10 minutes, single-use, max 5 tries) ----

CODE_TTL = timedelta(minutes=10)
CODE_MAX_ATTEMPTS = 5


def _new_code() -> str:
    return f"{secrets.randbelow(900000) + 100000:06d}"


def issue_verification_code(user_id: int) -> str:
    """Create a fresh email-verification code; returns the plain code
    (the caller sends it by email; it is never returned by any API)."""
    code = _new_code()
    expires = (datetime.now(timezone.utc) + CODE_TTL).isoformat()
    database.update_user(user_id, {
        "verification_code_hash": hash_password(code),
        "verification_code_expires_at": expires,
        "verification_attempts": 0,
    })
    return code


def issue_reset_code(user_id: int) -> str:
    """Create a fresh password-reset code; same rules as verification."""
    code = _new_code()
    expires = (datetime.now(timezone.utc) + CODE_TTL).isoformat()
    database.update_user(user_id, {
        "reset_code_hash": hash_password(code),
        "reset_code_expires_at": expires,
        "reset_attempts": 0,
    })
    return code


def _verify_code(user: dict, kind: str, code: str) -> bool:
    """kind: 'verification' or 'reset'. Wrong codes count up; at 5
    wrong attempts, or on expiry, the code is invalidated."""
    hash_key = f"{kind}_code_hash"
    exp_key = f"{kind}_code_expires_at"
    att_key = f"{kind}_attempts"
    stored = user.get(hash_key)
    if not stored:
        return False
    if (user.get(att_key) or 0) >= CODE_MAX_ATTEMPTS:
        database.update_user(user["id"], {hash_key: None, exp_key: None})
        return False
    try:
        expires = datetime.fromisoformat(user[exp_key])
    except (TypeError, ValueError):
        database.update_user(user["id"], {hash_key: None, exp_key: None})
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        database.update_user(user["id"], {hash_key: None, exp_key: None})
        return False
    if verify_password(code.strip(), stored):
        database.update_user(user["id"], {
            hash_key: None, exp_key: None, att_key: 0,
        })
        return True
    attempts = (user.get(att_key) or 0) + 1
    fields = {att_key: attempts}
    if attempts >= CODE_MAX_ATTEMPTS:
        fields[hash_key] = None
        fields[exp_key] = None
    database.update_user(user["id"], fields)
    return False


def verify_email_code(user: dict, code: str) -> bool:
    return _verify_code(user, "verification", code)


def verify_reset_code(user: dict, code: str) -> bool:
    return _verify_code(user, "reset", code)


# ---- image captcha (SVG, pure stdlib) ----
# 4 characters from an unambiguous alphabet, drawn with per-character
# rotation/offset plus noise lines and dots. The code is stored as a
# sha256 hash of "challenge_id:code", single-use, 10-minute expiry.

CAPTCHA_TTL = timedelta(minutes=10)
_CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CAPTCHA_COLORS = ["#B34700", "#1F4E79", "#375623", "#7030A0", "#C00000", "#2E75B6"]


def _captcha_code_hash(challenge_id: str, code: str) -> str:
    return hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest()


def create_captcha() -> tuple[str, str]:
    """Return (challenge_id, svg). The app shows the SVG and the user
    types the 4 characters at registration."""
    rng = random.Random(secrets.randbits(64))
    code = "".join(rng.choice(_CAPTCHA_CHARS) for _ in range(4))
    challenge_id = secrets.token_urlsafe(16)
    database.create_captcha_challenge(
        challenge_id, _captcha_code_hash(challenge_id, code)
    )
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="60"'
        ' viewBox="0 0 160 60">',
        '<rect width="160" height="60" fill="#FFF7E8"/>',
    ]
    for _ in range(4):  # noise lines
        x1, y1 = rng.randint(0, 160), rng.randint(0, 60)
        x2, y2 = rng.randint(0, 160), rng.randint(0, 60)
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
            f' stroke="#E8D9C0" stroke-width="1"/>'
        )
    for _ in range(28):  # noise dots
        parts.append(
            f'<circle cx="{rng.randint(0, 160)}" cy="{rng.randint(0, 60)}" r="1"'
            f' fill="#D9C7A7"/>'
        )
    for i, ch in enumerate(code):
        x = 18 + i * 36 + rng.randint(-4, 4)
        y = 40 + rng.randint(-5, 5)
        rot = rng.randint(-18, 18)
        color = rng.choice(_CAPTCHA_COLORS)
        parts.append(
            f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="32"'
            f' font-weight="bold" fill="{color}"'
            f' transform="rotate({rot} {x} {y})">{ch}</text>'
        )
    parts.append("</svg>")
    return challenge_id, "".join(parts)


def validate_captcha(challenge_id: str, answer: str) -> bool:
    """One attempt per challenge: the row is consumed whether the answer
    is right or wrong, so a challenge cannot be brute-forced."""
    if not challenge_id or not answer:
        return False
    row = database.consume_captcha_challenge(challenge_id)
    if row is None or row["used"]:
        return False
    try:
        created = datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > CAPTCHA_TTL:
        return False
    expected = _captcha_code_hash(challenge_id, answer.strip().upper())
    return hmac.compare_digest(expected, row["code_hash"])


# ---- rate limits (fixed windows; see database.rate_limit_hit) ----

REGISTER_PER_IP_PER_HOUR = 5
LOGIN_PER_IP_PER_HOUR = 10
LOGIN_PER_EMAIL_PER_HOUR = 10
VERIFY_PER_EMAIL_PER_HOUR = 3


def register_allowed(ip: str) -> bool:
    return database.rate_limit_hit(f"register:ip:{ip}", REGISTER_PER_IP_PER_HOUR, 3600)


def login_allowed(ip: str, email: str) -> bool:
    if not database.rate_limit_hit(f"login:ip:{ip}", LOGIN_PER_IP_PER_HOUR, 3600):
        return False
    return database.rate_limit_hit(
        f"login:email:{email}", LOGIN_PER_EMAIL_PER_HOUR, 3600
    )


def verify_send_allowed(email: str) -> bool:
    return database.rate_limit_hit(
        f"verify:email:{email}", VERIFY_PER_EMAIL_PER_HOUR, 3600
    )
