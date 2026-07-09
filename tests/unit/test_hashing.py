"""Sanity-check unit test proving the scaffold's test setup works end to end."""

from llmops_gateway.caching.hashing import exact_cache_key, normalize_prompt, params_hash
from llmops_gateway.domain.entities.chat_request import ChatMessage, ChatRequest


def test_normalize_prompt_collapses_whitespace() -> None:
    assert normalize_prompt("  hello   world  \n") == "hello world"


def test_exact_cache_key_is_deterministic() -> None:
    request = ChatRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="hi")])
    assert exact_cache_key(request) == exact_cache_key(request)


def test_exact_cache_key_differs_on_params() -> None:
    base = ChatRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="hi")])
    hotter = ChatRequest(
        model="gpt-4o", messages=[ChatMessage(role="user", content="hi")], temperature=0.9
    )
    assert exact_cache_key(base) != exact_cache_key(hotter)


def test_params_hash_ignores_prompt_text() -> None:
    a = ChatRequest(model="gpt-4o", messages=[ChatMessage(role="user", content="hi")])
    b = ChatRequest(
        model="gpt-4o", messages=[ChatMessage(role="user", content="a very different prompt")]
    )
    assert params_hash(a) == params_hash(b)
