"""Unit tests for API-key hashing and generation."""

from llmops_gateway.security.api_keys import (
    generate_api_key,
    hash_api_key,
    is_valid_api_key_format,
    verify_api_key,
)

PEPPER = "test-pepper"


def test_hash_api_key_is_deterministic() -> None:
    raw = "llmops_test_key_abc"
    assert hash_api_key(raw, pepper=PEPPER) == hash_api_key(raw, pepper=PEPPER)


def test_verify_api_key_accepts_matching_hash() -> None:
    raw = "llmops_test_key_abc"
    digest = hash_api_key(raw, pepper=PEPPER)
    assert verify_api_key(raw, digest, pepper=PEPPER) is True


def test_verify_api_key_rejects_wrong_key() -> None:
    digest = hash_api_key("llmops_real_key", pepper=PEPPER)
    assert verify_api_key("llmops_wrong_key", digest, pepper=PEPPER) is False


def test_generate_api_key_returns_prefixed_plaintext_and_hash() -> None:
    raw, digest = generate_api_key(pepper=PEPPER)
    assert raw.startswith("llmops_")
    assert verify_api_key(raw, digest, pepper=PEPPER) is True


def test_is_valid_api_key_format() -> None:
    assert is_valid_api_key_format("llmops_abc") is True
    assert is_valid_api_key_format("not-a-key") is False
    assert is_valid_api_key_format("llmops_") is False
