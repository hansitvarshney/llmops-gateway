"""Settings normalization for upstream provider API keys."""

from llmops_gateway.config.settings import Settings


def test_openai_api_key_strips_quotes_and_whitespace() -> None:
    settings = Settings(openai_api_key='  "sk-test-key"  ')
    assert settings.openai_api_key == "sk-test-key"


def test_blank_openai_api_key_becomes_none() -> None:
    settings = Settings(openai_api_key="   ")
    assert settings.openai_api_key is None
