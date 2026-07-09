"""Startup validation for production deployments."""

from llmops_gateway.config.settings import Environment, Settings

DEFAULT_INSECURE_PEPPER = "dev-insecure-pepper-change-me"


def validate_settings(settings: Settings) -> None:
    """Fail fast when production is misconfigured."""
    if settings.environment != Environment.PRODUCTION:
        return

    if settings.auth_api_key_pepper == DEFAULT_INSECURE_PEPPER:
        raise RuntimeError(
            "AUTH_API_KEY_PEPPER must be changed from the default value in production"
        )
