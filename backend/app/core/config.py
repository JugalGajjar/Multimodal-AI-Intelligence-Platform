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
    # Optional pool of keys used in round-robin when set (comma-separated).
    # When empty, the single `groq_api_key` above is used.
    groq_api_keys: str = ""
    groq_whisper_model: str = "whisper-large-v3-turbo"
    # Default chat-answer model. Users can override per account via Settings
    # (see app.agents.models for the curated list); this is the fallback when
    # `users.chat_model` is null.
    groq_reasoning_model: str = "openai/gpt-oss-120b"
    # Extraction (verification / summarization / entity extraction / intent
    # routing) also uses gpt-oss-120b — was llama-3.3-70b-versatile until Groq
    # deprecated it (2026-08-16 decommission).
    groq_extraction_model: str = "openai/gpt-oss-120b"

    # Tavily web search — powers the chat "Use Web" toggle. Best-effort:
    # transient failures degrade to no web context, but a missing key with
    # the toggle on is a hard 503 at the router.
    tavily_api_key: str = ""
    tavily_timeout_sec: float = 15.0

    # Strict-mode grounding gate: answers scoring below this are replaced
    # with a refusal. Separate from verification_threshold_verified (0.85),
    # which only colors the badge.
    strict_groundedness_threshold: float = 0.80

    # Retrieval pipeline. Vector + BM25 sparse fuse via RRF, then a
    # cross-encoder rerank picks the top_k. rerank_candidate_k is how
    # many candidates flow into the reranker.
    rerank_enabled: bool = True
    # 40 candidates flow into the reranker (was 20). Doubling widens the
    # net so the true best chunk is likelier to reach the reranker even
    # when hybrid RRF ranks it just outside the previous cutoff. Cost is
    # ~20ms extra reranker inference on CPU — cheap given the quality lift.
    rerank_candidate_k: int = 40
    rerank_model: str = "BAAI/bge-reranker-base"
    hybrid_enabled: bool = True
    hybrid_per_branch_k: int = 30
    # After reranking, enforce document diversity so a single verbose doc
    # can't monopolise every citation slot. Falls back gracefully: if the
    # cap leaves us below top_k (e.g. all candidates come from one doc)
    # the extras are backfilled from the remaining reranked chunks.
    retrieval_max_chunks_per_doc: int = 2

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

    # Map-reduce KG extraction: per-chunk two-pass (entities then relations)
    # merged, instead of single-shot on the concatenated doc. Handles
    # arbitrary doc size and keeps single requests small enough to fit
    # under Groq's TPM ceiling. Feature-flagged for fast rollback — flip
    # to False to fall back to the pre-#43 single-shot behavior.
    graph_extraction_map_reduce: bool = True

    # After map-reduce merge, run one targeted LLM call per top-scored
    # cross-chunk entity pair to catch relations that Pass 2 (chunk-local)
    # missed. Independently flaggable — disable if the extra calls hit the
    # Groq quota. #43b.
    graph_extraction_reconcile: bool = True
    graph_extraction_reconcile_top_k: int = 40

    # Semantic entity alignment (#43c) — L3 layer on top of L1/L2. Embeds
    # each entity's name+description via bge-small and merges same-type
    # entities whose cosine similarity clears the threshold, catching
    # abbreviation/expansion pairs (SFT ↔ Supervised Fine-Tuning, GWU ↔
    # George Washington University) that string-fuzzy matching can't.
    graph_semantic_align: bool = True
    graph_semantic_align_threshold: float = 0.85

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

    @property
    def groq_key_pool(self) -> list[str]:
        if self.groq_api_keys:
            return [k.strip() for k in self.groq_api_keys.split(",") if k.strip()]
        return [self.groq_api_key] if self.groq_api_key else []


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
