"""Configuration — env vars only, never hardcode keys."""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    # Server
    HOST: str = _env("HOST", "0.0.0.0")
    PORT: int = int(_env("PORT", "8000"))
    # Data directory (mounted as a Docker volume on the router)
    DATA_DIR: Path = Path(_env("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
    AUDIO_DIR: Path = DATA_DIR / "audio"
    DB_PATH: Path = DATA_DIR / "futureme.db"

    # Auth signing secret for device tokens (set a long random value in prod)
    JWT_SECRET: str = _env("JWT_SECRET", "dev-secret-change-me")

    # LLM providers for letter generation (OpenAI-compatible /chat/completions).
    # Default provider; override per request with POST /letters/generate {"provider": ...}.
    # At least one provider key must be set, otherwise letter generation is 503.
    LLM_PROVIDER: str = _env("LLM_PROVIDER", "qwen")

    # qwen （千问）: same DashScope key as Qwen3-TTS.
    # NOTE: QWEN_MODEL is the TTS model (qwen3-tts-flash); the chat model
    # uses the separate QWEN_LLM_MODEL below.
    QWEN_LLM_MODEL: str = _env("QWEN_LLM_MODEL", "qwen-plus")
    # hunyuan （腾讯混元）: API key from the Hunyuan console.
    HUNYUAN_API_KEY: str = _env("HUNYUAN_API_KEY", "")
    HUNYUAN_MODEL: str = _env("HUNYUAN_MODEL", "hunyuan-turbos-latest")
    # siliconflow （硅基流动）: API key from siliconflow.cn.
    SILICONFLOW_API_KEY: str = _env("SILICONFLOW_API_KEY", "")
    SILICONFLOW_MODEL: str = _env("SILICONFLOW_MODEL", "Qwen/Qwen3-8B")
    # zhipu （智谱 GLM): same bigmodel.cn key as GLM-TTS.
    ZHISHU_MODEL: str = _env("ZHISHU_MODEL", "glm-4-flash")
    # generic: any OpenAI-compatible endpoint (base URL + key + model all required).
    GENERIC_LLM_BASE_URL: str = _env("GENERIC_LLM_BASE_URL", "")
    GENERIC_LLM_API_KEY: str = _env("GENERIC_LLM_API_KEY", "")
    GENERIC_LLM_MODEL: str = _env("GENERIC_LLM_MODEL", "")

    # TTS providers
    DASHSCOPE_API_KEY: str = _env("DASHSCOPE_API_KEY", "")  # Qwen3-TTS (primary)
    QWEN_MODEL: str = _env("QWEN_MODEL", "qwen3-tts-flash")
    ZHISHU_API_KEY: str = _env("ZHISHU_API_KEY", "")  # GLM-TTS
    TENCENT_SECRET_ID: str = _env("TENCENT_SECRET_ID", "")
    TENCENT_SECRET_KEY: str = _env("TENCENT_SECRET_KEY", "")
    TENCENT_REGION: str = _env("TENCENT_REGION", "ap-guangzhou")

    # Membership (phase 1: free)
    TRIAL_DAYS: int = int(_env("TRIAL_DAYS", "7"))
    PRICE_MONTHLY_CNY: float = float(_env("PRICE_MONTHLY_CNY", "9.9"))

    @property
    def configured_providers(self) -> list[str]:
        out: list[str] = []
        if self.DASHSCOPE_API_KEY:
            out.append("qwen")
        if self.ZHISHU_API_KEY:
            out.append("zhipu")
        if self.TENCENT_SECRET_ID and self.TENCENT_SECRET_KEY:
            out.append("tencent")
        out.append("edge")  # free fallback, no key needed
        return out


settings = Settings()
