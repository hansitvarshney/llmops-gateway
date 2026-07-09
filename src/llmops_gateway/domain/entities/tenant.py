from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True)
class Tenant:
    id: str
    name: str
    slug: str
    budget_monthly_usd: Decimal | None
    is_active: bool = True
