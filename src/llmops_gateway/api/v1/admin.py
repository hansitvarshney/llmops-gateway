"""Admin endpoints: tenant/API-key management and pricing table CRUD."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from llmops_gateway.api.deps import get_authenticated_principal, get_db_session
from llmops_gateway.domain.entities.auth_context import AuthenticatedPrincipal
from llmops_gateway.persistence.repositories.api_key_repository import ApiKeyRepository
from llmops_gateway.persistence.repositories.pricing_repository import PricingRepository
from llmops_gateway.persistence.repositories.tenant_repository import TenantRepository
from llmops_gateway.security.api_keys import generate_api_key
from llmops_gateway.services.auth_service import AuthService

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["*"])


class CreateApiKeyResponse(BaseModel):
    api_key_id: str
    raw_key: str
    scopes: list[str]


class ApiKeySummary(BaseModel):
    id: str
    name: str
    scopes: list[str]
    revoked_at: datetime | None
    created_at: datetime


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)


class TenantSummary(BaseModel):
    id: str
    name: str
    slug: str
    status: str


class PricingSummary(BaseModel):
    id: str
    provider: str
    model_name: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal
    currency: str
    effective_from: datetime
    effective_to: datetime | None


class CreatePricingRequest(BaseModel):
    provider: str
    model_name: str
    input_price_per_1k: Decimal = Field(gt=0)
    output_price_per_1k: Decimal = Field(gt=0)
    currency: str = "USD"
    effective_from: datetime | None = None


@router.post("/api-keys", response_model=CreateApiKeyResponse)
async def create_api_key(
    request: Request,
    payload: CreateApiKeyRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> CreateApiKeyResponse:
    from llmops_gateway.config.settings import get_settings

    pepper = get_settings().auth_api_key_pepper
    raw_key, key_hash = generate_api_key(pepper=pepper)
    auth_service: AuthService = request.app.state.auth_service
    api_key_id = await auth_service.create_api_key(
        tenant_id=uuid.UUID(principal.tenant_id),
        key_hash=key_hash,
        name=payload.name,
        scopes=payload.scopes,
    )
    return CreateApiKeyResponse(
        api_key_id=str(api_key_id),
        raw_key=raw_key,
        scopes=payload.scopes,
    )


@router.get("/api-keys", response_model=list[ApiKeySummary])
async def list_api_keys(
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApiKeySummary]:
    repo = ApiKeyRepository(session)
    keys = await repo.list_by_tenant(uuid.UUID(principal.tenant_id))
    return [
        ApiKeySummary(
            id=str(key.id),
            name=key.name,
            scopes=list(key.scopes or []),
            revoked_at=key.revoked_at,
            created_at=key.created_at,
        )
        for key in keys
    ]


@router.delete("/api-keys/{api_key_id}", status_code=204)
async def revoke_api_key(
    api_key_id: uuid.UUID,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
) -> None:
    auth_service: AuthService = request.app.state.auth_service
    async with request.app.state.db.session() as session:
        record = await ApiKeyRepository(session).get_by_id(api_key_id)
        if record is None or str(record.tenant_id) != principal.tenant_id:
            raise HTTPException(status_code=404, detail="API key not found")
    revoked = await auth_service.revoke_api_key(api_key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found or already revoked")


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(session: AsyncSession = Depends(get_db_session)) -> list[TenantSummary]:
    tenants = await TenantRepository(session).list_all()
    return [
        TenantSummary(id=str(t.id), name=t.name, slug=t.slug, status=t.status) for t in tenants
    ]


@router.post("/tenants", response_model=TenantSummary, status_code=201)
async def create_tenant(
    payload: CreateTenantRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TenantSummary:
    tenant = await TenantRepository(session).create(
        name=payload.name,
        slug=payload.slug,
    )
    return TenantSummary(
        id=str(tenant.id), name=tenant.name, slug=tenant.slug, status=tenant.status
    )


@router.get("/pricing", response_model=list[PricingSummary])
async def list_pricing(session: AsyncSession = Depends(get_db_session)) -> list[PricingSummary]:
    rows = await PricingRepository(session).list_active()
    return [
        PricingSummary(
            id=str(row.id),
            provider=row.provider,
            model_name=row.model_name,
            input_price_per_1k=row.input_price_per_1k,
            output_price_per_1k=row.output_price_per_1k,
            currency=row.currency,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
        )
        for row in rows
    ]


@router.post("/pricing", response_model=PricingSummary, status_code=201)
async def create_pricing(
    payload: CreatePricingRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PricingSummary:
    effective_from = payload.effective_from or datetime.now(UTC)
    row = await PricingRepository(session).create(
        provider=payload.provider,
        model_name=payload.model_name,
        input_price_per_1k=payload.input_price_per_1k,
        output_price_per_1k=payload.output_price_per_1k,
        currency=payload.currency,
        effective_from=effective_from,
    )
    return PricingSummary(
        id=str(row.id),
        provider=row.provider,
        model_name=row.model_name,
        input_price_per_1k=row.input_price_per_1k,
        output_price_per_1k=row.output_price_per_1k,
        currency=row.currency,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
    )


class AdapterRouteSummary(BaseModel):
    id: str
    tenant_id: str
    model_alias: str
    base_model: str
    adapter_id: str
    stage: str
    enabled: bool
    canary_percent: int = 0
    created_at: datetime


class UpsertAdapterRouteRequest(BaseModel):
    model_alias: str = Field(min_length=1, max_length=128)
    base_model: str = Field(min_length=1, max_length=128)
    adapter_id: str = Field(min_length=1, max_length=255)
    stage: str = Field(default="Production", max_length=32)
    enabled: bool = True
    canary_percent: int = Field(default=0, ge=0, le=100)
    tenant_id: str | None = Field(
        default=None,
        description="Defaults to the authenticated principal's tenant.",
    )


@router.get("/adapter-routes", response_model=list[AdapterRouteSummary])
async def list_adapter_routes(
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: AsyncSession = Depends(get_db_session),
) -> list[AdapterRouteSummary]:
    from llmops_gateway.persistence.repositories.adapter_route_repository import (
        AdapterRouteRepository,
    )

    rows = await AdapterRouteRepository(session).list_for_tenant(uuid.UUID(principal.tenant_id))
    return [
        AdapterRouteSummary(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            model_alias=row.model_alias,
            base_model=row.base_model,
            adapter_id=row.adapter_id,
            stage=row.stage,
            enabled=row.enabled,
            canary_percent=int(row.canary_percent or 0),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.put("/adapter-routes", response_model=AdapterRouteSummary)
async def upsert_adapter_route(
    payload: UpsertAdapterRouteRequest,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: AsyncSession = Depends(get_db_session),
) -> AdapterRouteSummary:
    from llmops_gateway.persistence.repositories.adapter_route_repository import (
        AdapterRouteRepository,
    )

    tenant_id = uuid.UUID(payload.tenant_id or principal.tenant_id)
    # Non-wildcard keys can only mutate their own tenant.
    if "*" not in principal.scopes and str(tenant_id) != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot mutate another tenant's routes")

    row = await AdapterRouteRepository(session).upsert(
        tenant_id=tenant_id,
        model_alias=payload.model_alias,
        base_model=payload.base_model,
        adapter_id=payload.adapter_id,
        stage=payload.stage,
        enabled=payload.enabled,
        canary_percent=payload.canary_percent,
    )
    return AdapterRouteSummary(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        model_alias=row.model_alias,
        base_model=row.base_model,
        adapter_id=row.adapter_id,
        stage=row.stage,
        enabled=row.enabled,
        canary_percent=int(row.canary_percent or 0),
        created_at=row.created_at,
    )


@router.delete("/adapter-routes/{model_alias}", status_code=204)
async def disable_adapter_route(
    model_alias: str,
    stage: str = "Production",
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    from llmops_gateway.persistence.repositories.adapter_route_repository import (
        AdapterRouteRepository,
    )

    row = await AdapterRouteRepository(session).disable(
        tenant_id=uuid.UUID(principal.tenant_id),
        model_alias=model_alias,
        stage=stage,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Adapter route not found")
