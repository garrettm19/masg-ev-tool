import json
from pydantic import BaseModel, field_validator
from typing import Optional


class Market(BaseModel):
    id: str
    question: str
    outcomes: Optional[list[str]] = None
    outcomePrices: Optional[list[str]] = None  # string floats e.g. "0.73"

    @field_validator("outcomes", "outcomePrices", mode="before")
    @classmethod
    def parse_json_string(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return None
        return v
    category: Optional[str] = None
    liquidity: Optional[float] = None
    volume24hr: Optional[float] = None
    endDate: Optional[str] = None
    active: Optional[bool] = None
    closed: Optional[bool] = None
    featured: Optional[bool] = None
    imageOptimized: Optional[str] = None
    slug: Optional[str] = None
    event_slug: Optional[str] = None   # parent event slug
    event_name: Optional[str] = None   # parent event title from Gamma API
