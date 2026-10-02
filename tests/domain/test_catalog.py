from decimal import Decimal

import pytest

from quotes.domain.catalog import CatalogItem, PricingUnit, QuoteLine, quantity_for
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Currency, Money


def item(price: str = "40", unit: PricingUnit = PricingUnit.PER_PERSON) -> CatalogItem:
    return CatalogItem("lunch", "Buffet lunch", Money(Decimal(price), Currency.PEN), unit)


def test_line_cost_is_unit_price_times_quantity():
    line = QuoteLine(item("40"), 3)
    assert line.cost == Money(Decimal("120"), Currency.PEN)


def test_negative_price_rejected():
    with pytest.raises(InvalidPricingInput):
        item("-1")


def test_zero_price_allowed():
    assert item("0").unit_price.amount == 0


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantity_below_one_rejected(quantity):
    with pytest.raises(InvalidPricingInput):
        QuoteLine(item(), quantity)


def test_non_int_quantity_rejected():
    with pytest.raises(InvalidPricingInput):
        QuoteLine(item(), 1.5)  # type: ignore[arg-type]


def test_empty_id_or_name_rejected():
    with pytest.raises(InvalidPricingInput):
        CatalogItem("", "Name", Money(Decimal(1), Currency.PEN), PricingUnit.PER_GROUP)
    with pytest.raises(InvalidPricingInput):
        CatalogItem("id", " ", Money(Decimal(1), Currency.PEN), PricingUnit.PER_GROUP)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (PricingUnit.PER_GROUP, 1),
        (PricingUnit.PER_DAY, 3),
        (PricingUnit.PER_PERSON, 4),
        (PricingUnit.PER_UNIT, 2),
    ],
)
def test_quantity_for_unit(unit, expected):
    assert quantity_for(unit, days=3, travelers=4, explicit=2) == expected


def test_per_unit_requires_explicit_quantity():
    with pytest.raises(InvalidPricingInput):
        quantity_for(PricingUnit.PER_UNIT, days=3, travelers=4)


@pytest.mark.parametrize(("days", "travelers"), [(0, 2), (2, 0), (-1, 2), (2, -1)])
def test_quantity_for_rejects_non_positive_context(days, travelers):
    with pytest.raises(InvalidPricingInput):
        quantity_for(PricingUnit.PER_GROUP, days=days, travelers=travelers)
