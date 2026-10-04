"""Money value object. Amounts are ``Decimal``; floats are rejected."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from quotes.domain.errors import CurrencyMismatchError, InvalidPricingInput

CENT = Decimal("0.01")


class Currency(StrEnum):
    PEN = "PEN"
    USD = "USD"


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Convert an exact numeric input to ``Decimal``; reject floats and bools."""
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise InvalidPricingInput(f"Expected Decimal, int or str, got {type(value).__name__}")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidPricingInput(f"Invalid decimal value: {value!r}") from exc
    if not result.is_finite():
        raise InvalidPricingInput(f"Value must be finite: {value!r}")
    return result


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __mul__(self, quantity: Decimal | int) -> Money:
        return Money(self.amount * to_decimal(quantity), self.currency)

    __rmul__ = __mul__

    def quantized(self) -> Money:
        """Round to 2 decimals, half up."""
        return Money(self.amount.quantize(CENT, rounding=ROUND_HALF_UP), self.currency)

    @staticmethod
    def total(items: Iterable[Money], currency: Currency) -> Money:
        result = Money(Decimal(0), currency)
        for item in items:
            result = result + item
        return result

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot combine {self.currency} with {other.currency}")
