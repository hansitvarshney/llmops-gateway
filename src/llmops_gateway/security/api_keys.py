"""Secure API-key generation and hashing.

Raw keys are never stored — only a peppered SHA-256 digest is persisted.
Lookup is O(1) by hash, and verification uses constant-time comparison.
"""

import hashlib
import secrets

API_KEY_PREFIX = "llmops_"


def hash_api_key(raw_key: str, *, pepper: str) -> str:
    """Return the hex digest stored in `api_keys.key_hash`."""
    payload = f"{pepper}{raw_key}".encode()
    return hashlib.sha256(payload).hexdigest()


def verify_api_key(raw_key: str, stored_hash: str, *, pepper: str) -> bool:
    computed = hash_api_key(raw_key, pepper=pepper)
    return secrets.compare_digest(computed, stored_hash)


def generate_api_key(*, pepper: str) -> tuple[str, str]:
    """Return `(plaintext_key, key_hash)` for a newly minted credential."""
    raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return raw_key, hash_api_key(raw_key, pepper=pepper)


def is_valid_api_key_format(raw_key: str) -> bool:
    return raw_key.startswith(API_KEY_PREFIX) and len(raw_key) > len(API_KEY_PREFIX)
