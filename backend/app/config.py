"""Configuration — env vars only for NON-SECRET server settings.

All API keys and admin-editable config (LLM/TTS keys, provider models,
membership, admin password) live in the SQLite `settings` table and are
edited in the web admin console (/admin). Nothing secret is read from env
anymore — except JWT_SECRET, which is kept only as a legacy override for
deployments that already set it (new installs auto-generate the signing
secret into the settings table; see database.get_or_create_jwt_secret).
"""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    # Server (env only — these are not secrets)
    HOST: str = _env("HOST", "0.0.0.0")
    PORT: int = int(_env("PORT", "6999"))
    # Data directory (mounted as a Docker volume on the router)
    DATA_DIR: Path = Path(_env("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data")))
    AUDIO_DIR: Path = DATA_DIR / "audio"
    DB_PATH: Path = DATA_DIR / "futureme.db"


settings = Settings()
