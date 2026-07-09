"""Production settings validation tests."""

import pytest

from llmops_gateway.config.settings import Environment, Settings
from llmops_gateway.config.validation import validate_settings


def test_production_rejects_default_pepper() -> None:
    settings = Settings(environment=Environment.PRODUCTION)
    with pytest.raises(RuntimeError, match="AUTH_API_KEY_PEPPER"):
        validate_settings(settings)


def test_local_allows_default_pepper() -> None:
    validate_settings(Settings(environment=Environment.LOCAL))
