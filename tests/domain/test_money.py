from decimal import Decimal

import pytest

from quotes.domain.errors import CurrencyMismatchError, DomainError, InvalidPricingInput
from quotes.domain.money import Currency, Money


def pen(amount: str | int) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def test_accepts_int_and_str_and_normalizes_to_decimal():
    assert Money(10, Currency.PEN).amount == Decimal("10")
    assert Money("10.50", Currency.USD).amount == Decimal("10.50")


def test_rejects_float_amount():
    with pytest.raises(InvalidPricingInput):
        Money(10.5, Currency.PEN)  # type: ignore[arg-type]


def test_rejects_bool_amount():
    with pytest.raises(InvalidPricingInput):
        Money(True, Currency.PEN)  # type: ignore[arg-type]


def test_rejects_unparseable_string():
    with pytest.raises(InvalidPricingInput):
        Money("abc", Currency.PEN)


def test_add_same_currency():
    assert pen("10.25") + pen("4.75") == pen("15.00")


def test_add_mixed_currency_raises():
    with pytest.raises(CurrencyMismatchError):
        pen(1) + Money(Decimal(1), Currency.USD)


def test_currency_mismatch_is_a_domain_error():
    assert issubclass(CurrencyMismatchError, DomainError)
    assert issubclass(InvalidPricingInput, DomainError)


def test_multiply_by_int_and_decimal():
    assert pen("40") * 3 == pen("120")
    assert pen("40") * Decimal("0.25") == pen("10")


def test_rmul_supports_quantity_first():
    assert 3 * pen("40") == pen("120")


def test_multiply_rejects_float():
    with pytest.raises(InvalidPricingInput):
        pen(1) * 1.5  # type: ignore[operator]


def test_total_sums_money():
    assert Money.total([pen(1), pen(2), pen(3)], Currency.PEN) == pen(6)


def test_total_of_empty_is_zero_in_given_currency():
    assert Money.total([], Currency.USD) == Money(Decimal(0), Currency.USD)


def test_total_mixed_currency_raises():
    with pytest.raises(CurrencyMismatchError):
        Money.total([pen(1), Money(Decimal(1), Currency.USD)], Currency.PEN)


def test_quantized_rounds_half_up_to_two_decimals():
    assert pen("1.005").quantized().amount == Decimal("1.01")
    assert pen("1.004").quantized().amount == Decimal("1.00")
    assert pen("2.675").quantized().amount == Decimal("2.68")


def test_is_negative():
    assert Money(Decimal("-0.01"), Currency.PEN).is_negative
    assert not pen(0).is_negative
