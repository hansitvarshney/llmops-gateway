"""In-process representation of a single execution span within a request.

Mirrors the `request_spans` table and the OTel span model closely enough
that exporting to either is a straightforward field mapping.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class TraceSpan:
    trace_id: str
    span_id: str
    span_name: str
    started_at: datetime
    parent_span_id: str | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() * 1000
