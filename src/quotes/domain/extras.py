"""Optional extras: priced separately and never added to the main quote total."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from quotes.domain.catalog import QuoteLine
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.pricing import PriceBreakdown, PricingPolicy, price_quote
from quotes.domain.travelers import Travelers


@dataclass(frozen=True)
class OptionalExtraPrice:
    label: str
    breakdown: PriceBreakdown


def price_optional_extras(
    extras: Sequence[tuple[str, Sequence[QuoteLine]]],
    travelers: Travelers,
    policy: PricingPolicy,
) -> tuple[OptionalExtraPrice, ...]:
    """Price each labelled extra with the same policy as the main quote."""
    labels = [label.strip() for label, _ in extras]
    if any(not label for label in labels):
        raise InvalidPricingInput("Extra labels must not be empty")
    if len(set(labels)) != len(labels):
        raise InvalidPricingInput("Extra labels must be unique")
    return tuple(
        OptionalExtraPrice(label, price_quote(lines, travelers, policy))
        for label, (_, lines) in zip(labels, extras, strict=True)
    )
