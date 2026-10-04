"""Information-only items that the tourist pays locally (e.g. a valley entrance ticket).

They carry reference prices for display and are never part of subtotal, margin or totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Currency, Money


class VisitorCategory(StrEnum):
    LATIN_AMERICAN_ADULT = "latin_american_adult"
    FOREIGN_ADULT = "foreign_adult"
    CHILD_6_15 = "child_6_15"


@dataclass(frozen=True)
class LocalPrice:
    category: VisitorCategory
    price: Money  # reference price in PEN

    def __post_init__(self) -> None:
        if self.price.currency != Currency.PEN or self.price.is_negative:
            raise InvalidPricingInput("Local reference price must be a non-negative PEN amount")


@dataclass(frozen=True)
class LocalPaymentInfo:
    label: str
    prices: tuple[LocalPrice, ...]

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise InvalidPricingInput("Local payment label must not be empty")
        object.__setattr__(self, "prices", tuple(self.prices))
        if not self.prices:
            raise InvalidPricingInput("Local payment info needs at least one price")
        categories = [p.category for p in self.prices]
        if len(set(categories)) != len(categories):
            raise InvalidPricingInput("Local payment categories must be unique")

    def price_for(self, category: VisitorCategory) -> Money:
        for entry in self.prices:
            if entry.category == category:
                return entry.price
        raise InvalidPricingInput(f"No local price for category: {category}")
