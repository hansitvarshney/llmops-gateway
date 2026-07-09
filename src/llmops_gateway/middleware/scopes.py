"""Route -> required-scope mapping consumed by AuthMiddleware."""

SCOPE_CHAT_WRITE = "chat:write"
SCOPE_EMBEDDINGS_WRITE = "embeddings:write"
SCOPE_ADMIN_READ = "admin:read"
SCOPE_ADMIN_WRITE = "admin:write"

# Longest-prefix wins when multiple patterns could match.
ROUTE_SCOPES: list[tuple[str, str, frozenset[str]]] = [
    ("/v1/chat/completions", "POST", frozenset({SCOPE_CHAT_WRITE})),
    ("/v1/embeddings", "POST", frozenset({SCOPE_EMBEDDINGS_WRITE})),
    ("/v1/admin", "GET", frozenset({SCOPE_ADMIN_READ, SCOPE_ADMIN_WRITE})),
    ("/v1/admin", "POST", frozenset({SCOPE_ADMIN_WRITE})),
    ("/v1/admin", "PUT", frozenset({SCOPE_ADMIN_WRITE})),
    ("/v1/admin", "PATCH", frozenset({SCOPE_ADMIN_WRITE})),
    ("/v1/admin", "DELETE", frozenset({SCOPE_ADMIN_WRITE})),
]


def required_scopes_for_request(path: str, method: str) -> frozenset[str] | None:
    """Return the scopes any one of which satisfies the route, or None if unscoped."""
    method = method.upper()
    for prefix, route_method, scopes in ROUTE_SCOPES:
        if method == route_method and (path == prefix or path.startswith(f"{prefix}/")):
            return scopes
    return None


def principal_has_any_scope(scopes: frozenset[str], required: frozenset[str]) -> bool:
    if "*" in scopes:
        return True
    return bool(scopes & required)
