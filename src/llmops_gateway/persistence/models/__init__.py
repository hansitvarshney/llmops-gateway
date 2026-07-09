"""Import every ORM model so Alembic's autogenerate can discover them via
`Base.metadata` in a single place.
"""

from llmops_gateway.persistence.models.api_key import ApiKeyModel
from llmops_gateway.persistence.models.base import Base
from llmops_gateway.persistence.models.cache_entry_meta import CacheEntryMetaModel
from llmops_gateway.persistence.models.model_pricing import ModelPricingModel
from llmops_gateway.persistence.models.provider_health import ProviderHealthModel
from llmops_gateway.persistence.models.request_log import RequestLogModel
from llmops_gateway.persistence.models.tenant import TenantModel
from llmops_gateway.persistence.models.token_usage import TokenUsageModel
from llmops_gateway.persistence.models.trace_span import RequestSpanModel

__all__ = [
    "Base",
    "TenantModel",
    "ApiKeyModel",
    "ModelPricingModel",
    "RequestLogModel",
    "RequestSpanModel",
    "TokenUsageModel",
    "ProviderHealthModel",
    "CacheEntryMetaModel",
]
