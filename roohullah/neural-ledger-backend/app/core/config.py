from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    APP_NAME: str = "Neural Ledger"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"   # development | staging | production

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/neural_ledger"

    # ── JWT ──────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-to-a-long-random-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── AES-256 (per-org encryption) ─────────────────────
    # Master key used to derive per-org keys; store in AWS KMS in prod
    MASTER_ENCRYPTION_KEY: str = "change-me-32-byte-hex-secret-key!!"

    # ── CORS ─────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
