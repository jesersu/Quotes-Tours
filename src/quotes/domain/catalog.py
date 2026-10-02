"""Catalog items and quote lines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Money


class PricingUnit(StrEnum):
    PER_GROUP = "per_group"
    PER_DAY = "per_day"
    PER_PERSON = "per_person"
    PER_UNIT = "per_unit"


@dataclass(frozen=True)
class CatalogItem:
    id: str
    name: str
    unit_price: Money
    unit: PricingUnit

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise InvalidPricingInput("Catalog item id and name must not be empty")
        if self.unit_price.is_negative:
            raise InvalidPricingInput(f"Unit price must not be negative: {self.id}")


@dataclass(frozen=True)
class QuoteLine:
    item: CatalogItem
    quantity: int

    def __post_init__(self) -> None:
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise InvalidPricingInput("Quantity must be an integer")
        if self.quantity < 1:
            raise InvalidPricingInput("Quantity must be at least 1")

    @property
    def cost(self) -> Money:
        return self.item.unit_price * self.quantity


def quantity_for(unit: PricingUnit, days: int, travelers: int, explicit: int | None = None) -> int:
    """Line quantity implied by the pricing unit and the trip context."""
    if days < 1 or travelers < 1:
        raise InvalidPricingInput("Days and travelers must be at least 1")
    match unit:
        case PricingUnit.PER_GROUP:
            return 1
        case PricingUnit.PER_DAY:
            return days
        case PricingUnit.PER_PERSON:
            return travelers
        case PricingUnit.PER_UNIT:
            if explicit is None:
                raise InvalidPricingInput("PER_UNIT items require an explicit quantity")
            return explicit
