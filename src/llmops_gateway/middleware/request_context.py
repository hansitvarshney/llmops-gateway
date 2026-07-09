"""Assigns a trace_id/request_id to every inbound request and binds it into
structlog's contextvars so all log lines for the request are correlated,
without threading a logger/trace_id through every function signature.
"""

import uuid

import structlog
from starlette.requests import Request
from starlette.responses import Response

TRACE_ID_HEADER = "X-Trace-Id"


async def request_context_middleware_dispatch(request: Request, call_next) -> Response:
    trace_id = request.headers.get(TRACE_ID_HEADER) or str(uuid.uuid4())
    request.state.trace_id = trace_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, path=request.url.path)

    response = await call_next(request)
    response.headers[TRACE_ID_HEADER] = trace_id
    return response
