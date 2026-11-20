"""Device + account auth.

Token format (v2): base64url(device_id) + "." + random_hex + "." +
user_id-or-empty + "." + hmac_sha256(secret, device_id + "." + nonce +
"." + user_id). Anonymous devices get an empty user_id field. Legacy
v1 tokens (3 parts, no user_id field) are still accepted and treated
as anonymous — already-issued device tokens keep working.

The signing secret lives in the settings table (auto-generated on first
boot); a JWT_SECRET env var, when set, overrides it for backwards
compatibility with existing deployments.
"""
import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import database

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    return database.get_or_create_jwt_secret()


def _b64e(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _b64d(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


@dataclass
class AuthContext:
    device_id: str
    user_id: int | None = None

    @property
    def logged_in(self) -> bool:
        return self.user_id is not None


def issue_token(device_id: str, user_id: int | None = None) -> str:
    nonce = secrets.token_hex(16)
    user_part = "" if user_id is None else str(user_id)
    payload = f"{device_id}.{nonce}.{user_part}"
    sig = hmac.new(
        _secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{_b64e(device_id)}.{nonce}.{user_part}.{sig}"


def verify_token_full(token: str) -> AuthContext:
    """Verify a token (v1 or v2) and return the device + optional user.
    v1 signed "device.nonce"; v2 signs "device.nonce.user_id" — each
    version is verified against its own payload."""
    try:
        parts = token.split(".")
        if len(parts) == 3:  # legacy v1: no user_id field
            b64_id, nonce, sig = parts
            device_id = _b64d(b64_id)
            payload = f"{device_id}.{nonce}"
            user_part = ""
        elif len(parts) == 4:
            b64_id, nonce, user_part, sig = parts
            device_id = _b64d(b64_id)
            payload = f"{device_id}.{nonce}.{user_part}"
        else:
            raise ValueError("bad token parts")
    except (ValueError, Exception):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    expected = hmac.new(
        _secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    if not database.device_exists(device_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown device")
    user_id = None
    if user_part:
        try:
            user_id = int(user_part)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
        if database.get_user(user_id) is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown account")
    return AuthContext(device_id=device_id, user_id=user_id)


def verify_token(token: str) -> str:
    """Return the device_id if the token is valid, else raise 401."""
    return verify_token_full(token).device_id


def _bearer_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return creds.credentials


def get_current_device(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    return verify_token(creds.credentials)


def get_current_auth(token: str = Depends(_bearer_token)) -> AuthContext:
    """Device + optional account, for endpoints that behave differently
    for logged-in users (membership, /auth/me)."""
    return verify_token_full(token)


def require_account(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    """Endpoints that only make sense for a logged-in account
    (change password, verify email, delete account)."""
    if auth.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account login required",
        )
    return auth
