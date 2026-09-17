"""The daily digest entry shown on the Home page.

Split out of the single ``schemas.py``; import from
``shared.schemas``, which still re-exports everything.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel


# -- Digest entry schemas --

class DigestEntryResponse(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID | None
    period: str
    summary: str
    highlights: list[str] | None
    stats: dict | None
    total_observations: int
    generated_at: datetime

    model_config = {"from_attributes": True}
