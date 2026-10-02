"""Pricing policy and quote price calculation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from quotes.domain.catalog import QuoteLine
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Currency, Money, to_decimal


@dataclass(frozen=True)
class PricingPolicy:
    margin_rate: Decimal
    fx_rate: Decimal  # PEN per 1 USD
    usd_rounding_step: Decimal = Decimal("50")

    def __post_init__(self) -> None:
        object.__setattr__(self, "margin_rate", to_decimal(self.margin_rate))
        object.__setattr__(self, "fx_rate", to_decimal(self.fx_rate))
        object.__setattr__(self, "usd_rounding_step", to_decimal(self.usd_rounding_step))
        if self.margin_rate < 0:
            raise InvalidPricingInput("Margin rate must not be negative")
        if self.fx_rate <= 0:
            raise InvalidPricingInput("FX rate must be positive")
        if self.usd_rounding_step <= 0:
            raise InvalidPricingInput("USD rounding step must be positive")


@dataclass(frozen=True)
class PriceBreakdown:
    lines: tuple[QuoteLine, ...]
    subtotal_pen: Money
    margin_pen: Money
    sale_pen: Money
    sale_usd_exact: Money
    final_usd: Money
    final_pen: Money
    per_person_usd: Money
    per_person_pen: Money


def price_quote(
    lines: Sequence[QuoteLine], travelers: int, policy: PricingPolicy
) -> PriceBreakdown:
    """Price a set of lines: margin, USD conversion rounded up to a step, per-person totals."""
    if not lines:
        raise InvalidPricingInput("A quote needs at least one line")
    if isinstance(travelers, bool) or not isinstance(travelers, int) or travelers < 1:
        raise InvalidPricingInput("Travelers must be an integer of at least 1")

    subtotal = Money.total((line.cost for line in lines), Currency.PEN)
    margin = subtotal * policy.margin_rate
    sale_pen = subtotal + margin
    sale_usd_exact = Money(sale_pen.amount / policy.fx_rate, Currency.USD)
    final_usd = Money(_round_up(sale_usd_exact.amount, policy.usd_rounding_step), Currency.USD)
    final_pen = Money(final_usd.amount * policy.fx_rate, Currency.PEN).quantized()

    return PriceBreakdown(
        lines=tuple(lines),
        subtotal_pen=subtotal,
        margin_pen=margin,
        sale_pen=sale_pen,
        sale_usd_exact=sale_usd_exact,
        final_usd=final_usd,
        final_pen=final_pen,
        per_person_usd=Money(final_usd.amount / travelers, Currency.USD).quantized(),
        per_person_pen=Money(final_pen.amount / travelers, Currency.PEN).quantized(),
    )


def _round_up(amount: Decimal, step: Decimal) -> Decimal:
    return (amount / step).to_integral_value(rounding=ROUND_CEILING) * step
