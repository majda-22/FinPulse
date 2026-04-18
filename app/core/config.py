"""
config.py — central settings for FinPulse.
All environment variables are read once here.
Every other module imports from this file, never from os.environ directly.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PostgreSQL ────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "finpulse"
    postgres_user: str = "finpulse"
    postgres_password: str = "finpulse_secret"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def async_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Object storage ────────────────────────────────────────────────────
    storage_backend: str = "local"          # "local" | "r2" | "s3"
    local_storage_root: str = "./data/raw"

    # R2 / S3 (only needed when storage_backend != "local")
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "finpulse-filings"

    # ── EDGAR ─────────────────────────────────────────────────────────────
    edgar_user_agent: str = "FinPulse research@finpulse.ai"
    edgar_rate_limit: float = 8.0
    fred_api_key: str = ""
    fred_api_base: str = "https://api.stlouisfed.org/fred"

    # ── App ───────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    batch_size: int = 32
    embedding_provider: str = "mistral"
    mistral_api_key: str = ""
    mistral_embedding_model: str = "mistral-embed"
    mistral_api_base: str = "https://api.mistral.ai"
    embedding_request_timeout_sec: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance. Import and call this everywhere."""
    return Settings()
