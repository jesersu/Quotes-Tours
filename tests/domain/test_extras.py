from decimal import Decimal

import pytest

from quotes.domain.catalog import CatalogItem, PricingUnit, QuoteLine
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.extras import OptionalExtraPrice, price_optional_extras
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy, price_quote

D = Decimal
POLICY = PricingPolicy(margin_rate=D("0.25"), fx_rate=D("3.5"), usd_rounding_step=D("50"))


def line(price: int, quantity: int = 1) -> QuoteLine:
    item = CatalogItem("x", "Item", Money(D(price), Currency.PEN), PricingUnit.PER_PERSON)
    return QuoteLine(item, quantity)


def test_each_extra_is_priced_with_the_same_policy():
    extras = [("Hot springs", [line(30, 2)]), ("Cable car", [line(100, 2), line(20, 2)])]

    result = price_optional_extras(extras, travelers=2, policy=POLICY)

    assert [r.label for r in result] == ["Hot springs", "Cable car"]
    assert all(isinstance(r, OptionalExtraPrice) for r in result)
    assert result[0].breakdown == price_quote([line(30, 2)], 2, POLICY)
    # Cable car: 100x2 + 20x2 = 240; +25% = 300 PEN; /3.5 = 85.71 USD -> 100 USD
    assert result[1].breakdown.subtotal_pen == Money(D(240), Currency.PEN)
    assert result[1].breakdown.sale_pen == Money(D(300), Currency.PEN)
    assert result[1].breakdown.final_usd == Money(D(100), Currency.USD)
    assert result[1].breakdown.per_person_usd == Money(D("50.00"), Currency.USD)


def test_no_extras_returns_empty_tuple():
    assert price_optional_extras([], travelers=2, policy=POLICY) == ()


def test_extra_without_lines_rejected():
    with pytest.raises(InvalidPricingInput):
        price_optional_extras([("Empty", [])], travelers=2, policy=POLICY)


def test_blank_label_rejected():
    with pytest.raises(InvalidPricingInput):
        price_optional_extras([(" ", [line(10)])], travelers=2, policy=POLICY)


def test_duplicate_labels_rejected():
    extras = [("Spa", [line(10)]), ("Spa", [line(20)])]
    with pytest.raises(InvalidPricingInput):
        price_optional_extras(extras, travelers=2, policy=POLICY)


def test_invalid_travelers_rejected():
    with pytest.raises(InvalidPricingInput):
        price_optional_extras([("Spa", [line(10)])], travelers=0, policy=POLICY)
