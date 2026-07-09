"""Central application configuration.

All runtime configuration is env-driven via pydantic-settings so the same
image can be promoted across dev/staging/prod purely by changing environment
variables (12-factor). Nothing in this module should read files or perform
I/O at import time.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class EmbeddingProviderKind(StrEnum):
    """Which EmbeddingProvider implementation backs the semantic cache."""

    LOCAL = "local"
    API = "api"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "llmops-gateway"
    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"
    log_json: bool = True

    # --- Postgres ---
    database_url: str = Field(
        default="postgresql+asyncpg://llmops:llmops@localhost:5432/llmops_gateway",
        description="Async SQLAlchemy DSN for the metadata/analytics store.",
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    redis_exact_cache_ttl_seconds: int = 3600
    redis_max_connections: int = 50

    # --- Qdrant ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_search_timeout_ms: int = 80
    semantic_cache_similarity_threshold: float = 0.95
    cache_coalescing_lock_ttl_seconds: float = 10.0
    cache_coalescing_wait_seconds: float = 2.0
    cache_coalescing_poll_interval_seconds: float = 0.05

    # --- Embeddings (pluggable, see domain.interfaces.embedding_provider) ---
    embedding_provider: EmbeddingProviderKind = EmbeddingProviderKind.LOCAL
    embedding_local_model_name: str = "all-MiniLM-L6-v2"
    embedding_api_model_name: str = "text-embedding-3-small"

    # --- Upstream LLM providers ---
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    provider_fallback_chain: list[str] = Field(
        default_factory=lambda: ["openai", "anthropic"],
        description="Ordered provider names tried on failure/429/timeout.",
    )
    provider_max_retries: int = 3
    provider_request_timeout_seconds: float = 60.0
    provider_circuit_failure_threshold: int = 5
    provider_circuit_cooldown_seconds: float = 30.0
    provider_model_fallback_map: dict[str, str] = Field(
        default_factory=lambda: {
            "openai:gpt-4o": "anthropic:claude-3-5-sonnet-20241022",
            "openai:gpt-4o-mini": "anthropic:claude-3-5-haiku-20241022",
            "anthropic:claude-3-5-sonnet-20241022": "openai:gpt-4o",
            "anthropic:claude-3-5-haiku-20241022": "openai:gpt-4o-mini",
        },
        description="Cross-provider equivalent-model map, keyed/valued as 'provider:model'. "
        "Used for automatic fallback routing when a request's native provider is "
        "unavailable (circuit open / retries exhausted) — e.g. gpt-4o falls back to "
        "claude-3-5-sonnet, per the architecture plan.",
    )

    # --- Background jobs (arq, Redis-backed) ---
    arq_redis_url: str | None = None  # falls back to redis_url when unset
    use_arq_workers: bool = True
    run_migrations_on_startup: bool = False  # set true in Docker via entrypoint env

    # --- Observability ---
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "llmops-gateway"
    tracing_enabled: bool = True
    metrics_enabled: bool = True
    cost_pricing_cache_ttl_seconds: float = 300.0

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- Auth / rate limiting ---
    api_key_header_name: str = "X-API-Key"
    auth_api_key_pepper: str = Field(
        default="dev-insecure-pepper-change-me",
        description="Server-side pepper mixed into API-key hashes. MUST be rotated in production.",
    )
    auth_cache_ttl_seconds: float = 300.0
    auth_require_api_key: bool = True
    default_rate_limit_per_minute: int = 60
    rate_limit_enabled: bool = True
    rate_limit_fail_open: bool = False

    @property
    def resolved_arq_redis_url(self) -> str:
        return self.arq_redis_url or self.redis_url


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — safe to call repeatedly from Depends()."""
    return Settings()
