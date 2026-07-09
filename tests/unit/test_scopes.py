"""Scope resolution helpers."""

from llmops_gateway.middleware.scopes import (
    principal_has_any_scope,
    required_scopes_for_request,
)


def test_chat_route_requires_chat_write_scope() -> None:
    scopes = required_scopes_for_request("/v1/chat/completions", "POST")
    assert scopes is not None
    assert "chat:write" in scopes


def test_health_route_has_no_scope_requirement() -> None:
    assert required_scopes_for_request("/health", "GET") is None


def test_wildcard_scope_grants_any_required_scope() -> None:
    required = frozenset({"chat:write"})
    assert principal_has_any_scope(frozenset({"*"}), required) is True


def test_partial_scope_match_is_sufficient() -> None:
    required = frozenset({"admin:read", "admin:write"})
    assert principal_has_any_scope(frozenset({"admin:read"}), required) is True
    assert principal_has_any_scope(frozenset({"chat:write"}), required) is False
