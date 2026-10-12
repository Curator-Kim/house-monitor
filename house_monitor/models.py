from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Observation:
    source: str
    source_id: str
    name: str
    url: str
    region_id: str
    kind: str = "reference_unit"
    value: Optional[float] = None
    value_high: Optional[float] = None
    unit: str = "元/平方米"
    raw_price: str = ""
    address: str = ""
    property_type: str = "住宅"
    sale_status: str = "在售"
    period: str = ""
    granularity: str = "snapshot"
    source_updated: Optional[str] = None
    missing_reason: Optional[str] = None
    official_id: Optional[str] = None
    presell: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)


@dataclass
class SourceResult:
    source: str
    region_id: str
    status: str = "ok"
    message: str = ""
    records: list = field(default_factory=list)
    discovered: int = 0
    eligible: int = 0
    pages: int = 0
    complete: bool = False
    warnings: list = field(default_factory=list)
