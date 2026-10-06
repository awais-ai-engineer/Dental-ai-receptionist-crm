from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Aves AI Receptionist API"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://aves:aves@localhost:5432/aves"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    cors_origins: list[str] = ["http://localhost:3000"]
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_provider: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimension: int = Field(default=1536, gt=0)
    knowledge_chunk_size: int = Field(default=1200, ge=200, le=10000)
    knowledge_chunk_overlap: int = Field(default=180, ge=0, le=2000)
    rag_max_distance: float = Field(default=0.45, ge=0, le=2)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    n8n_webhook_url: str = ""
    n8n_webhook_secret: str = ""
    n8n_webhook_enabled: bool = False
    n8n_webhook_timeout_seconds: float = Field(default=10, gt=0, le=120)
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    telephony_provider: str = ""
    telephony_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
