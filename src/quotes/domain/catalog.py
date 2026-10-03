"""Catalog items and quote lines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Money
from quotes.domain.travelers import Travelers


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
    child_unit_price: Money | None = None  # PER_PERSON only: price for children aged 6-15

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise InvalidPricingInput("Catalog item id and name must not be empty")
        if self.unit_price.is_negative:
            raise InvalidPricingInput(f"Unit price must not be negative: {self.id}")
        child = self.child_unit_price
        if child is not None:
            if child.is_negative:
                raise InvalidPricingInput(f"Child unit price must not be negative: {self.id}")
            if child.currency != self.unit_price.currency:
                raise InvalidPricingInput(f"Child price currency must match unit price: {self.id}")


@dataclass(frozen=True)
class QuoteLine:
    """``quantity`` units at the unit price plus ``child_quantity`` at the child price."""

    item: CatalogItem
    quantity: int
    child_quantity: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise InvalidPricingInput("Quantity must be an integer")
        if self.quantity < 1:
            raise InvalidPricingInput("Quantity must be at least 1")
        if isinstance(self.child_quantity, bool) or not isinstance(self.child_quantity, int):
            raise InvalidPricingInput("Child quantity must be an integer")
        if self.child_quantity < 0:
            raise InvalidPricingInput("Child quantity must not be negative")

    @property
    def cost(self) -> Money:
        child_price = self.item.child_unit_price or self.item.unit_price
        return self.item.unit_price * self.quantity + child_price * self.child_quantity


def build_line(
    item: CatalogItem, days: int, travelers: Travelers, explicit: int | None = None
) -> QuoteLine:
    """Build the line implied by the item's pricing unit and the trip context.

    Only PER_PERSON items depend on headcount: full-fare travelers pay the unit price and
    children aged 6-15 pay the child price. Children under 6 never add cost.
    """
    if days < 1:
        raise InvalidPricingInput("Days must be at least 1")
    match item.unit:
        case PricingUnit.PER_GROUP:
            return QuoteLine(item, 1)
        case PricingUnit.PER_DAY:
            return QuoteLine(item, days)
        case PricingUnit.PER_PERSON:
            return QuoteLine(item, travelers.full_fare_count, travelers.reduced_fare_children)
        case PricingUnit.PER_UNIT:
            if explicit is None:
                raise InvalidPricingInput("PER_UNIT items require an explicit quantity")
            return QuoteLine(item, explicit)
