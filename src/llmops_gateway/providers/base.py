"""Shared retry/backoff/circuit-breaker resilience layer for LLMProvider adapters.

Concrete adapters (OpenAIProvider, AnthropicProvider) only implement the
`_complete_impl`/`_stream_impl` hooks against the raw provider API; this base
class wraps both with:
  - exponential backoff + jitter, honoring an explicit `Retry-After` on
    HTTP 429 rather than blindly recomputing a delay
  - a per-provider circuit breaker (opens after `circuit_failure_threshold`
    consecutive failures and fails fast for `circuit_cooldown_seconds`,
    then allows a single half-open probe before fully closing again)

This is same-provider resilience only. Cross-provider fallback (trying the
*next* provider in the chain once this one's retry budget is exhausted, or
its circuit is open) is RoutingService's job — see routing_service.py.
"""

import asyncio
import random
import time
from collections.abc import AsyncIterator
from enum import StrEnum

import structlog

from llmops_gateway.domain.entities.chat_request import ChatRequest
from llmops_gateway.domain.entities.chat_response import ChatResponse, TokenUsage
from llmops_gateway.domain.interfaces.llm_provider import LLMProvider

logger = structlog.get_logger(__name__)


class ProviderError(Exception):
    """Base class for upstream provider failures.

    `retryable` controls whether BaseLLMProvider's retry loop will attempt
    this same provider again (e.g. a 5xx or timeout) versus surfacing
    immediately so RoutingService can move to the next provider without
    wasting the retry budget on a request that can never succeed (e.g. a
    400 Bad Request or 401 Unauthorized).
    """

    def __init__(
        self, message: str, *, retryable: bool = True, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ProviderRateLimitedError(ProviderError):
    """Raised on HTTP 429; carries retry_after_seconds when the upstream
    supplied a `Retry-After` header, so backoff honors it exactly rather
    than guessing."""

    def __init__(self, retry_after_seconds: float | None = None) -> None:
        super().__init__(
            "Upstream provider rate limited the request", retryable=True, status_code=429
        )
        self.retry_after_seconds = retry_after_seconds


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str = "Upstream provider request timed out") -> None:
        super().__init__(message, retryable=True)


class ProviderConnectionError(ProviderError):
    def __init__(self, message: str = "Failed to connect to upstream provider") -> None:
        super().__init__(message, retryable=True)


class ProviderResponseError(ProviderError):
    """A non-2xx, non-429 HTTP response. 5xx is treated as transient
    (retryable); other 4xx codes (bad request, auth, not found, ...) are
    not, since retrying them can never succeed."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message, retryable=status_code >= 500, status_code=status_code)


class ProviderUnavailableError(ProviderError):
    """Raised immediately (no HTTP call attempted) when the circuit breaker
    is open for this provider."""

    def __init__(self, provider_name: str) -> None:
        super().__init__(
            f"Circuit breaker open for provider '{provider_name}'", retryable=False
        )


DEFAULT_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_BACKOFF_MAX_SECONDS = 20.0
DEFAULT_BACKOFF_JITTER_SECONDS = 0.5


def compute_backoff_delay(
    attempt: int,
    *,
    retry_after_seconds: float | None = None,
    base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    jitter_seconds: float = DEFAULT_BACKOFF_JITTER_SECONDS,
) -> float:
    """Exponential backoff with jitter; honors an explicit Retry-After when
    the upstream provider supplies one (HTTP 429), per the plan's
    "provider 429 storms" mitigation."""
    if retry_after_seconds is not None:
        return max(0.0, retry_after_seconds)
    delay = min(max_seconds, base_seconds * (2**attempt))
    return delay + random.uniform(0, jitter_seconds)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-provider circuit breaker guarding against hammering a dead upstream.

    Opens after `failure_threshold` consecutive failures and fails fast
    (raising ProviderUnavailableError, no network call attempted) for
    `cooldown_seconds`. After the cooldown elapses, a single half-open probe
    is allowed through: success closes the circuit and resets the failure
    count, failure reopens it with a fresh cooldown window. This avoids the
    "circuit breaker flapping" failure mode by only ever probing once per
    cooldown window rather than admitting a burst of traffic.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    def _effective_state(self) -> CircuitState:
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def state(self) -> CircuitState:
        return self._effective_state()

    async def allow_request(self) -> bool:
        async with self._lock:
            return self._effective_state() is not CircuitState.OPEN

    async def record_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            if self._effective_state() is CircuitState.HALF_OPEN:
                # The probe failed — reopen immediately with a fresh cooldown
                # rather than requiring `failure_threshold` more failures.
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                return
            if self._consecutive_failures >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()


class BaseLLMProvider(LLMProvider):
    name: str

    def __init__(
        self,
        max_retries: int = 3,
        request_timeout_seconds: float = 60.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 30.0,
    ) -> None:
        self._max_retries = max_retries
        self._request_timeout_seconds = request_timeout_seconds
        self._circuit = CircuitBreaker(circuit_failure_threshold, circuit_cooldown_seconds)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        if not await self._circuit.allow_request():
            raise ProviderUnavailableError(self.name)

        attempt = 0
        while True:
            try:
                response = await self._complete_impl(request)
            except ProviderError as exc:
                await self._circuit.record_failure()
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                delay = compute_backoff_delay(
                    attempt, retry_after_seconds=getattr(exc, "retry_after_seconds", None)
                )
                logger.warning(
                    "provider_retry",
                    provider=self.name,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    error=str(exc),
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue
            else:
                await self._circuit.record_success()
                return response

    async def stream(self, request: ChatRequest) -> AsyncIterator[str]:
        if not await self._circuit.allow_request():
            raise ProviderUnavailableError(self.name)

        attempt = 0
        while True:
            yielded_any = False
            try:
                async for chunk in self._stream_impl(request):
                    yielded_any = True
                    yield chunk
                await self._circuit.record_success()
                return
            except ProviderError as exc:
                await self._circuit.record_failure()
                # Once any token has reached the caller, retrying would
                # duplicate output — the error must propagate instead of
                # silently restarting the stream from scratch.
                if yielded_any or not exc.retryable or attempt >= self._max_retries:
                    raise
                delay = compute_backoff_delay(
                    attempt, retry_after_seconds=getattr(exc, "retry_after_seconds", None)
                )
                logger.warning(
                    "provider_stream_retry",
                    provider=self.name,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    error=str(exc),
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue

    async def _complete_impl(self, request: ChatRequest) -> ChatResponse:
        raise NotImplementedError

    def _stream_impl(self, request: ChatRequest) -> AsyncIterator[str]:
        raise NotImplementedError

    async def count_tokens(self, request: ChatRequest, completion_text: str) -> TokenUsage:
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release pooled connections. Overridden by adapters that own an
        httpx.AsyncClient; called from ProviderRegistry.aclose_all() during
        application shutdown."""
        return None
