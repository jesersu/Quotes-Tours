"""Pricing policy and quote price calculation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from quotes.domain.catalog import QuoteLine
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.local_payment import LocalPaymentInfo
from quotes.domain.money import Currency, Money, to_decimal
from quotes.domain.travelers import Travelers


@dataclass(frozen=True)
class PricingPolicy:
    margin_rate: Decimal
    fx_rate: Decimal = Decimal("3.5")  # PEN per 1 USD
    usd_rounding_step: Decimal | None = None  # None: no commercial rounding

    def __post_init__(self) -> None:
        object.__setattr__(self, "margin_rate", to_decimal(self.margin_rate))
        object.__setattr__(self, "fx_rate", to_decimal(self.fx_rate))
        if self.usd_rounding_step is not None:
            object.__setattr__(self, "usd_rounding_step", to_decimal(self.usd_rounding_step))
        if self.margin_rate < 0:
            raise InvalidPricingInput("Margin rate must not be negative")
        if self.fx_rate <= 0:
            raise InvalidPricingInput("FX rate must be positive")
        if self.usd_rounding_step is not None and self.usd_rounding_step <= 0:
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
    paid_locally: tuple[LocalPaymentInfo, ...] = ()  # information only, outside every total


def price_quote(
    lines: Sequence[QuoteLine],
    travelers: Travelers,
    policy: PricingPolicy,
    paid_locally: Sequence[LocalPaymentInfo] = (),
) -> PriceBreakdown:
    """Price lines: margin, final PEN, USD reference (optionally rounded up), per-person totals."""
    if not lines:
        raise InvalidPricingInput("A quote needs at least one line")

    subtotal = Money.total((line.cost for line in lines), Currency.PEN)
    margin = subtotal * policy.margin_rate
    sale_pen = subtotal + margin
    sale_usd_exact = Money(sale_pen.amount / policy.fx_rate, Currency.USD)
    if policy.usd_rounding_step is None:
        # The final price is the PEN sale price; USD is only a converted reference.
        final_usd = sale_usd_exact.quantized()
        final_pen = sale_pen.quantized()
    else:
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
        per_person_usd=Money(final_usd.amount / travelers.total, Currency.USD).quantized(),
        per_person_pen=Money(final_pen.amount / travelers.total, Currency.PEN).quantized(),
        paid_locally=tuple(paid_locally),
    )


def _round_up(amount: Decimal, step: Decimal) -> Decimal:
    return (amount / step).to_integral_value(rounding=ROUND_CEILING) * step
