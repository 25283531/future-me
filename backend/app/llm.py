"""Multi-provider LLM client for future-letter generation.

All providers speak OpenAI-compatible /chat/completions — one unified
client, no vendor SDKs. Server-side only; the Android app never sees keys.

Providers:
  qwen         阿里云千问 (DashScope compatible mode)
  hunyuan      腾讯混元
  siliconflow  硅基流动
  zhipu        智谱 GLM
  generic      any OpenAI-compatible endpoint (fully env-configured)

The system prompt encodes the product rules; the output filter in
content_filter.py enforces them again before anything is stored.
"""
import httpx

from .config import settings

SYSTEM_PROMPT = """你是一位来自未来的“我”，正在给过去的自己写一封信。你的任务是写一封“未来信”。

硬性规则（必须全部遵守）：
1. 用第一人称“我”写信，用过去时，就好像愿望已经实现了，正在回顾那段经历。
2. 全文 150-200 个汉字（不含标点以外的空白），不要超出这个范围。
3. 必须提到愿望的具体内容，并且提到目标天数（{days} 天）。
4. 语气温暖、真诚、积极，写具体的行动和感受，不要写空话。
5. 绝对禁止出现以下内容：玄学、塔罗、占星、星座、显化、改运、转运、宇宙能量、注定、必成、财运、发财、包过、保过、算命、风水；禁止承诺任何结果，例如保证通过考试、保证赚钱、保证治愈疾病。
6. 不要写医疗建议、理财建议，也不要保证考试、升职、收入等结果。
7. 不要出现“AI 生成”“我是 AI”等字样，只写信本身。

愿望：{wish_text}
目标天数：{days} 天
"""

CORRECTION_PROMPT = """你上一封信违反了以下规则：{problems}。
请重写一封完全遵守规则的信：第一人称过去时，150-200 个汉字，提到愿望内容和 {days} 天，不含任何禁止内容。
愿望：{wish_text}
"""

# Provider id -> display name. Order is the order shown by /llm/providers.
PROVIDER_NAMES: dict[str, str] = {
    "qwen": "千问",
    "hunyuan": "腾讯混元",
    "siliconflow": "硅基流动",
    "zhipu": "智谱 GLM",
    "generic": "通用接口",
}

# Fixed base URLs for the named providers (OpenAI-compatible endpoints).
# `generic` takes its base URL from GENERIC_LLM_BASE_URL instead.
PROVIDER_BASE_URLS: dict[str, str] = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}


class LLMNotConfigured(Exception):
    """No usable provider key is configured (maps to HTTP 503)."""


class LLMError(Exception):
    """Provider call failed or the output never passed the filter (HTTP 502)."""


class LLMProviderError(ValueError):
    """Requested provider id is unknown or not configured (maps to HTTP 400)."""


def _provider_config(provider_id: str) -> dict:
    """Return {base_url, api_key, model} for a provider id.

    Raises LLMProviderError for an unknown id. Missing credentials are
    reported by the caller (400 for an explicit request, 503 otherwise).
    """
    if provider_id not in PROVIDER_NAMES:
        raise LLMProviderError(
            f"unknown LLM provider: {provider_id} "
            f"(available: {', '.join(PROVIDER_NAMES)})"
        )
    if provider_id == "qwen":
        # Same DashScope key as Qwen3-TTS. NOTE: settings.QWEN_MODEL is the
        # TTS model (qwen3-tts-flash); the chat model is QWEN_LLM_MODEL.
        return {
            "base_url": PROVIDER_BASE_URLS["qwen"],
            "api_key": settings.DASHSCOPE_API_KEY,
            "model": settings.QWEN_LLM_MODEL,
        }
    if provider_id == "hunyuan":
        return {
            "base_url": PROVIDER_BASE_URLS["hunyuan"],
            "api_key": settings.HUNYUAN_API_KEY,
            "model": settings.HUNYUAN_MODEL,
        }
    if provider_id == "siliconflow":
        return {
            "base_url": PROVIDER_BASE_URLS["siliconflow"],
            "api_key": settings.SILICONFLOW_API_KEY,
            "model": settings.SILICONFLOW_MODEL,
        }
    if provider_id == "zhipu":
        # Same bigmodel.cn key as GLM-TTS.
        return {
            "base_url": PROVIDER_BASE_URLS["zhipu"],
            "api_key": settings.ZHISHU_API_KEY,
            "model": settings.ZHISHU_MODEL,
        }
    # generic: any OpenAI-compatible endpoint, fully env-configured.
    return {
        "base_url": settings.GENERIC_LLM_BASE_URL,
        "api_key": settings.GENERIC_LLM_API_KEY,
        "model": settings.GENERIC_LLM_MODEL,
    }


def list_llm_providers() -> list[dict]:
    """Provider table for GET /api/v1/llm/providers."""
    out: list[dict] = []
    for pid, name in PROVIDER_NAMES.items():
        cfg = _provider_config(pid)
        configured = bool(cfg["api_key"]) and bool(cfg["base_url"]) and bool(cfg["model"])
        out.append(
            {"id": pid, "name": name, "configured": configured, "model": cfg["model"]}
        )
    return out


def generate_letter_text(
    wish_text: str, days: int, provider: str | None = None, max_attempts: int = 2
) -> str:
    """Generate a letter, validating each attempt. Raises LLMError on failure.

    `provider` overrides the default LLM_PROVIDER for this call. An explicit
    request for an unknown or unconfigured provider raises LLMProviderError
    (HTTP 400); if no provider is usable at all, LLMNotConfigured (HTTP 503).
    """
    from .content_filter import validate_letter

    explicit = provider is not None
    provider_id = provider or settings.LLM_PROVIDER
    cfg = _provider_config(provider_id)  # raises LLMProviderError if unknown
    missing = [
        field
        for field, val in (
            ("api_key", cfg["api_key"]),
            ("base_url", cfg["base_url"]),
            ("model", cfg["model"]),
        )
        if not val
    ]
    if missing:
        if explicit:
            raise LLMProviderError(
                f"LLM provider '{provider_id}' is not configured "
                f"(missing: {', '.join(missing)}); set its key in the server env"
            )
        configured = [p["id"] for p in list_llm_providers() if p["configured"]]
        if not configured:
            raise LLMNotConfigured(
                "no LLM provider is configured on the server; set at least one "
                "provider API key (see .env.example); letter generation is unavailable"
            )
        raise LLMNotConfigured(
            f"default LLM provider '{provider_id}' is not configured "
            f"(missing: {', '.join(missing)}); configured providers: "
            f"{', '.join(configured)} — set LLM_PROVIDER or the provider key"
        )

    url = f"{cfg['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(wish_text=wish_text, days=days)},
        {
            "role": "user",
            "content": f"请给我写一封未来信。我的愿望是：{wish_text}，目标是 {days} 天后实现它。",
        },
    ]
    problems: list[str] = []
    for attempt in range(max_attempts):
        if attempt > 0:
            messages.append(
                {
                    "role": "user",
                    "content": CORRECTION_PROMPT.format(
                        problems="；".join(problems), wish_text=wish_text, days=days
                    ),
                }
            )
        try:
            # trust_env=False: httpx chokes on bracketed IPv6 entries (e.g.
            # "[::1]") in NO_PROXY ("Invalid port: ':1]'"), and the router
            # deployment has no egress proxy anyway — direct is correct.
            with httpx.Client(timeout=60.0, trust_env=False) as client:
                resp = client.post(
                    url,
                    headers=headers,
                    json={
                        "model": cfg["model"],
                        "messages": messages,
                        "temperature": 0.8,
                        "max_tokens": 500,
                    },
                )
        except httpx.HTTPError as e:
            raise LLMError(f"{provider_id} request failed: {e}") from e
        if resp.status_code != 200:
            raise LLMError(
                f"{provider_id} API returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            text = resp.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"unexpected {provider_id} response: {resp.text[:300]}") from e

        ok, problems = validate_letter(text, wish_text, days)
        if ok:
            return text
        messages.append({"role": "assistant", "content": text})
    raise LLMError(
        "generated letter did not pass the content filter after "
        f"{max_attempts} attempts: {'; '.join(problems)}"
    )
