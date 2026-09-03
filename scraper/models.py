from dataclasses import dataclass
from uuid import UUID

@dataclass(slots=True)
class RawPanel:
    title: str
    price_text: str
    power_text: str
    efficiency_text: str
    bifaciality_text: str
    source_url: str
    is_available: bool
    scrape_run_id: UUID