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
    # Managed Postgres: postgresql+asyncpg://...?ssl=require
    database_url: str = ""

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""
    redis_secure: bool = False

    # Qdrant — set qdrant_url + qdrant_api_key for cloud
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_url: str = ""
    qdrant_api_key: str = ""

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
    openrouter_video_model: str = "nvidia/nemotron-nano-12b-v2-vl:free"

    # Adaptive frame sampling for video ingest. Frame count is bounded by
    # `video_frame_budget`; frames are downscaled to `video_target_width`
    # and JPEG-encoded at `video_jpeg_quality` before being sent. 30 frames
    # is the chosen prod tradeoff — a touch more coverage at the 60-120s
    # tier than the prototype's 24 without meaningfully dilating latency.
    video_frame_budget: int = 30
    video_target_width: int = 720
    video_jpeg_quality: int = 85
    # Hard duration cap enforced after the upload reaches the worker
    # (cv2 lives in the worker image, not the API). Guards against Groq
    # Whisper's 25 MB upload ceiling and against arq/HF Space timeouts.
    # The 100 MiB upload cap is a coarser upstream filter.
    video_max_duration_sec: int = 300
    # OpenRouter `include_reasoning` flag — surfaces CoT in the response at
    # the cost of extra output tokens. Off by default; the worker only uses
    # `message.content`.
    video_include_reasoning: bool = False

    groq_api_key: str = ""
    groq_whisper_model: str = "whisper-large-v3-turbo"
    groq_reasoning_model: str = "openai/gpt-oss-20b"
    # gpt-oss-20b is unreliable under json_object response_format on noisy
    # OCR text; llama-3.3-70b handles structured output cleanly.
    groq_extraction_model: str = "llama-3.3-70b-versatile"

    # Transactional email (Resend). When unset, /register skips the email
    # but still creates the user — useful for local dev without a key.
    resend_api_key: str = ""
    resend_from_email: str = "onboarding@resend.dev"

    # Per-IP rate limiting on /auth/*. Tests flip this off via env to keep
    # the unit suite hermetic.
    rate_limit_enabled: bool = True
    # Per-account login lockout — count failed logins, lock after N in window.
    auth_lockout_threshold: int = 5
    auth_lockout_window_sec: int = 900  # 15 minutes

    # Knowledge-graph expansion. `graph_max_hops` is clamped to 1..3.
    # `graph_max_facts_per_seed` caps facts per seed regardless of depth —
    # closer hops are preferred when capping.
    graph_max_hops: int = 2
    graph_max_facts_per_seed: int = 12

    # Verification scores each answer against its context. Disable to skip
    # the extra LLM call.
    verification_enabled: bool = True
    verification_threshold_verified: float = 0.85
    verification_threshold_partial: float = 0.5

    # Intent router classifies the query and branches the workflow. When
    # disabled, every turn takes the "chat" path.
    router_enabled: bool = True
    # Used by the summarize branch to bound the context that's fed back.
    router_max_summary_docs: int = 5

    # Distributed tracing. When disabled, spans become no-ops with zero cost.
    otel_enabled: bool = True
    otel_service_name: str = "mmap-backend"
    otel_endpoint: str = "http://jaeger:4317"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def postgres_dsn(self) -> str:
        if self.database_url:
            return self.database_url
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
