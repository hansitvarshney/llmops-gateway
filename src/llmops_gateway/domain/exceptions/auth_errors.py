"""Auth-related exceptions translated by middleware/error_handling.py."""


class AuthenticationError(Exception):
    """Missing, malformed, revoked, or unknown API key."""

    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(message)
        self.message = message


class AuthorizationError(Exception):
    """Authenticated but not permitted (inactive tenant, etc.)."""

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message)
        self.message = message


class InsufficientScopeError(AuthorizationError):
    """Authenticated principal lacks the scope required by the route."""

    def __init__(self, required_scope: str) -> None:
        super().__init__(f"Missing required scope: {required_scope}")
        self.required_scope = required_scope
