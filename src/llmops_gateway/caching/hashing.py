"""Canonical prompt normalization + hashing for the Layer-1 exact cache.

Kept dependency-free (no Redis/Qdrant imports) so it can be unit tested in
isolation and reused by cache write-back jobs.
"""

import hashlib

from llmops_gateway.domain.entities.chat_request import ChatRequest


def normalize_prompt(text: str) -> str:
    """Whitespace/case normalization so trivially-different prompts
    (trailing space, double newline) still hit the exact cache."""
    return " ".join(text.strip().split())


def exact_cache_key(request: ChatRequest) -> str:
    """Deterministic key combining the normalized prompt and every parameter
    that affects the output, so a cache hit is only ever served for a truly
    equivalent request."""
    fingerprint = f"{normalize_prompt(request.canonical_prompt())}|{request.params_fingerprint()}"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"cache:exact:{digest}"


def params_hash(request: ChatRequest) -> str:
    """Hash of just the parameters (no prompt text) — used as a Qdrant
    payload filter so semantic search never matches across incompatible
    temperature/max_tokens/model configurations."""
    digest = hashlib.sha256(request.params_fingerprint().encode("utf-8")).hexdigest()
    return digest[:16]
