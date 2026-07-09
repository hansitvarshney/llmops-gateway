"""Liveness/readiness endpoints, exempt from auth (see exempt_paths.py)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request) -> JSONResponse:
    health_service = request.app.state.health_service
    report = await health_service.check_readiness()
    content = {
        "status": report.status,
        "dependencies": [
            {"name": dep.name, "status": dep.status, "detail": dep.detail}
            for dep in report.dependencies
        ],
    }
    status_code = 200 if report.is_ready else 503
    return JSONResponse(status_code=status_code, content=content)
