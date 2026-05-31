from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT_ENV), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_debug: bool = True

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_cors_origins: str = "http://localhost:3000"

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # Postgres
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "mmap"
    postgres_password: str = "mmap_dev_password"
    postgres_db: str = "mmap"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333

    # Neo4j
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_dev_password"

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin_dev"
    minio_bucket: str = "mmap-uploads"
    minio_secure: bool = False

    # AI providers
    openrouter_api_key: str = ""
    openrouter_vision_model: str = "qwen/qwen2.5-vl-72b-instruct:free"
    openrouter_reasoning_model: str = "deepseek/deepseek-r1:free"

    groq_api_key: str = ""
    groq_whisper_model: str = "whisper-large-v3-turbo"
    groq_reasoning_model: str = "openai/gpt-oss-20b"
    # Extraction needs strict JSON output over noisy PDF/OCR text. The default
    # reasoning model (gpt-oss-20b) is unreliable under Groq's json_object
    # response_format on that input; llama-3.3-70b handles it cleanly.
    groq_extraction_model: str = "llama-3.3-70b-versatile"

    # Knowledge-graph expansion knobs.
    # `graph_max_hops` controls how far we walk from each seed entity (1, 2 or
    # 3). `graph_max_facts_per_seed` caps the total fact count returned per
    # seed regardless of depth — closer hops are preferred when capping.
    graph_max_hops: int = 2
    graph_max_facts_per_seed: int = 12

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
