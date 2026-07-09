"""Port for exporting completed traces to an observability backend.

Concrete implementations live in `llmops_gateway.observability` (OTLP,
Langfuse, ...). Kept pluggable so the platform isn't hard-wired to a single
tracing vendor.
"""

from abc import ABC, abstractmethod

from llmops_gateway.domain.entities.trace_span import TraceSpan


class TraceExporter(ABC):
    @abstractmethod
    async def export(self, spans: list[TraceSpan]) -> None:
        """Export a batch of completed spans. Must never raise into the
        caller — failures should be logged and swallowed, since this always
        runs off the critical request path (background worker)."""
        raise NotImplementedError
