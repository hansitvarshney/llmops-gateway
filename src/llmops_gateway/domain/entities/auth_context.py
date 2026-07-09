"""Authenticated request principal attached by AuthMiddleware."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    tenant_id: str
    api_key_id: str
    tenant_status: str
    scopes: frozenset[str]
    rate_limit_per_minute: int | None = None

    def has_scope(self, required: str) -> bool:
        if "*" in self.scopes:
            return True
        return required in self.scopes
