from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelIdentifier:
    """Fully-qualified reference to a model on a specific upstream provider.

    Kept distinct from a raw string so routing/pricing/cache-key logic never
    has to re-parse "provider:model" strings ad hoc.
    """

    provider: str  # e.g. "openai", "anthropic"
    model: str  # e.g. "gpt-4o", "claude-3-5-sonnet-20241022"

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"

    @classmethod
    def parse(cls, value: str) -> "ModelIdentifier":
        provider, _, model = value.partition(":")
        if not model:
            raise ValueError(f"Expected 'provider:model', got {value!r}")
        return cls(provider=provider, model=model)
