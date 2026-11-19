"""TTS provider abstraction with fallback chain.

Chain (in order): Qwen3-TTS (DashScope, primary) -> Zhipu GLM-TTS ->
Tencent TTS (premium) -> Edge TTS (free fallback, unofficial endpoint).
A provider is skipped when its key is not configured. If the requested
voice belongs to a specific provider, that provider is tried first, then
the admin-chosen default TTS provider, then the rest of the chain.

Keys come from the settings table (admin console /admin), never from env.
DashScope is shared with 千问 LLM; the Zhipu key is shared with GLM LLM.

Audio is cached on disk keyed by sha256(text + voice_id) so the same
letter + voice is only ever synthesized once.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import database
from .catalog import VOICE_MAP
from .config import settings

MAX_TEXT_CHARS = 1000


class TTSUnavailable(Exception):
    pass


def cache_path(text: str, voice_id: str) -> Path:
    digest = hashlib.sha256(f"{voice_id}|{text}".encode()).hexdigest()
    return settings.AUDIO_DIR / f"{digest}.mp3"


# ---- providers ----

def _qwen_synthesize(text: str, voice: str) -> bytes:
    """DashScope multimodal generation, model qwen3-tts-flash.
    Response: output.audio is a URL (download it) or base64 audio."""
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    headers = {
        "Authorization": f"Bearer {database.get_setting('dashscope.api_key')}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0, trust_env=False) as client:
        resp = client.post(
            url,
            headers=headers,
            json={
                "model": "qwen3-tts-flash",
                "input": {"text": text, "voice": voice},
                "parameters": {"format": "mp3"},
            },
        )
    if resp.status_code != 200:
        raise TTSUnavailable(f"Qwen TTS HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        audio = resp.json()["output"]["audio"]
    except (KeyError, ValueError) as e:
        raise TTSUnavailable(f"Qwen TTS unexpected response: {resp.text[:200]}") from e
    if isinstance(audio, str) and audio.startswith("http"):
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            dl = client.get(audio)
        if dl.status_code != 200:
            raise TTSUnavailable(f"Qwen TTS audio download HTTP {dl.status_code}")
        return dl.content
    return base64.b64decode(audio)


def _zhipu_synthesize(text: str, voice: str) -> bytes:
    """Zhipu GLM-TTS: POST /api/paas/v4/audio/speech, binary audio back."""
    url = "https://open.bigmodel.cn/api/paas/v4/audio/speech"
    headers = {
        "Authorization": f"Bearer {database.get_setting('zhipu.api_key')}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0, trust_env=False) as client:
        resp = client.post(
            url,
            headers=headers,
            json={
                "model": "glm-tts",
                "input": text,
                "voice": voice,
                "response_format": "mp3",
            },
        )
    if resp.status_code != 200:
        raise TTSUnavailable(f"Zhipu TTS HTTP {resp.status_code}: {resp.text[:200]}")
    if not resp.content:
        raise TTSUnavailable("Zhipu TTS returned empty audio")
    return resp.content


def _tencent_sign(secret_key: str, date_stamp: str, service: str, string_to_sign: str) -> str:
    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_date = _hmac(("TC3" + secret_key).encode(), date_stamp)
    k_service = _hmac(k_date, service)
    k_signing = _hmac(k_service, "tc3_request")
    return hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()


def _tencent_synthesize(text: str, voice_type: str) -> bytes:
    """Tencent Cloud TTS (TC3-HMAC-SHA256 signed). Returns base64 audio."""
    service, host = "tts", "tts.tencentcloudapi.com"
    action, version = "TextToVoice", "2019-08-23"
    region = database.get_setting("tencent.region", "ap-guangzhou")
    payload = {
        "Text": text,
        "SessionId": hashlib.md5(f"{text}{time.time()}".encode()).hexdigest(),
        "VoiceType": int(voice_type),
        "Codec": "mp3",
        "Speed": 0,
        "Volume": 0,
        "PrimaryLanguage": 1,
    }
    body = json.dumps(payload)
    now = datetime.now(timezone.utc)
    timestamp = int(now.timestamp())
    date_stamp = now.strftime("%Y-%m-%d")
    canonical_headers = f"content-type:application/json\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    canonical_request = (
        f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n"
        f"{hashlib.sha256(body.encode()).hexdigest()}"
    )
    credential_scope = f"{date_stamp}/{service}/tc3_request"
    string_to_sign = (
        f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    signature = _tencent_sign(
        database.get_setting("tencent.secret_key"), date_stamp, service, string_to_sign
    )
    authorization = (
        f"TC3-HMAC-SHA256 Credential={database.get_setting('tencent.secret_id')}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version,
        "X-TC-Region": region,
    }
    with httpx.Client(timeout=60.0, trust_env=False) as client:
        resp = client.post(f"https://{host}/", headers=headers, content=body)
    if resp.status_code != 200:
        raise TTSUnavailable(f"Tencent TTS HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json().get("Response", {})
    if "Error" in data:
        raise TTSUnavailable(f"Tencent TTS error: {data['Error']}")
    audio_b64 = data.get("Audio")
    if not audio_b64:
        raise TTSUnavailable("Tencent TTS returned no audio")
    return base64.b64decode(audio_b64)


async def _edge_synthesize_async(text: str, voice: str) -> bytes:
    try:
        import edge_tts
    except ImportError as e:
        raise TTSUnavailable("edge-tts library is not installed") from e
    chunks: list[bytes] = []
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    if not chunks:
        raise TTSUnavailable("Edge TTS returned no audio")
    return b"".join(chunks)


def _edge_synthesize(text: str, voice: str) -> bytes:
    return asyncio.run(_edge_synthesize_async(text, voice))


# ---- chain ----

# provider -> (needs_key, synthesize_fn)
_PROVIDERS = {
    "qwen": (lambda: bool(database.get_setting("dashscope.api_key")), _qwen_synthesize),
    "zhipu": (lambda: bool(database.get_setting("zhipu.api_key")), _zhipu_synthesize),
    "tencent": (
        lambda: bool(
            database.get_setting("tencent.secret_id")
            and database.get_setting("tencent.secret_key")
        ),
        _tencent_synthesize,
    ),
    "edge": (lambda: True, _edge_synthesize),
}

CHAIN_ORDER = ["qwen", "zhipu", "tencent", "edge"]


def chain_order() -> list[str]:
    """Fallback order: voice's provider is moved first by the caller; the
    admin-chosen default TTS provider comes next, then the rest."""
    default = database.get_setting("tts.default_provider", "qwen")
    order = list(CHAIN_ORDER)
    if default in order:
        order.remove(default)
        order.insert(0, default)
    return order


def synthesize(text: str, voice_id: str) -> tuple[Path, str, bool]:
    """Synthesize (or reuse cache). Returns (path, provider_used, cached).

    Raises ValueError for unknown voice / too-long text, TTSUnavailable
    when every configured provider fails.
    """
    voice = VOICE_MAP.get(voice_id)
    if voice is None:
        raise ValueError(f"unknown voice_id: {voice_id}")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text too long ({len(text)} chars, max {MAX_TEXT_CHARS})")

    path = cache_path(text, voice_id)
    if path.exists() and path.stat().st_size > 0:
        return path, "cache", True

    settings.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    order = chain_order()
    preferred = voice["provider"]
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)

    errors: list[str] = []
    for provider in order:
        has_key, fn = _PROVIDERS[provider]
        if not has_key():
            errors.append(f"{provider}: not configured")
            continue
        try:
            audio = fn(text, voice["provider_voice"])
        except Exception as e:  # noqa: BLE001 - fall through the chain
            errors.append(f"{provider}: {e}")
            continue
        if not audio:
            errors.append(f"{provider}: empty audio")
            continue
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
        return path, provider, False

    raise TTSUnavailable("all TTS providers failed: " + "; ".join(errors))
