from decimal import Decimal

import pytest

from quotes.domain.catalog import CatalogItem, PricingUnit, QuoteLine, build_line
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Currency, Money
from quotes.domain.travelers import Travelers


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


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def priced(unit: PricingUnit, price: str = "10", child: str | None = None) -> CatalogItem:
    return CatalogItem(
        "x", "Item", pen(price), unit, child_unit_price=pen(child) if child else None
    )


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (PricingUnit.PER_GROUP, 1),
        (PricingUnit.PER_DAY, 3),
        (PricingUnit.PER_PERSON, 4),
        (PricingUnit.PER_UNIT, 2),
    ],
)
def test_build_line_quantity_for_unit(unit, expected):
    line = build_line(priced(unit), days=3, travelers=Travelers(4), explicit=2)
    assert line.quantity == expected
    assert line.child_quantity == 0


def test_per_unit_requires_explicit_quantity():
    with pytest.raises(InvalidPricingInput):
        build_line(priced(PricingUnit.PER_UNIT), days=3, travelers=Travelers(4))


@pytest.mark.parametrize("days", [0, -1])
def test_build_line_rejects_non_positive_days(days):
    with pytest.raises(InvalidPricingInput):
        build_line(priced(PricingUnit.PER_GROUP), days=days, travelers=Travelers(2))


def test_children_under_six_are_free_on_per_person_items():
    line = build_line(priced(PricingUnit.PER_PERSON, "13"), 1, Travelers(2, (3, 5)))
    assert line.cost == pen("26")


def test_child_six_to_fifteen_pays_child_price_on_per_person_item():
    item = priced(PricingUnit.PER_PERSON, "13", child="7")
    line = build_line(item, 1, Travelers(2, (6, 15)))
    assert (line.quantity, line.child_quantity) == (2, 2)
    assert line.cost == pen("40")  # 2 x 13 + 2 x 7


def test_child_without_child_price_pays_adult_price():
    line = build_line(priced(PricingUnit.PER_PERSON, "13"), 1, Travelers(1, (9,)))
    assert line.cost == pen("26")


def test_sixteen_and_seventeen_pay_adult_price_even_with_child_price():
    item = priced(PricingUnit.PER_PERSON, "13", child="7")
    line = build_line(item, 1, Travelers(1, (16, 17)))
    assert (line.quantity, line.child_quantity) == (3, 0)
    assert line.cost == pen("39")


@pytest.mark.parametrize("unit", [PricingUnit.PER_GROUP, PricingUnit.PER_DAY])
def test_group_and_day_items_ignore_children(unit):
    item = priced(unit, "13", child="7")
    with_children = build_line(item, 2, Travelers(2, (3, 9, 12)))
    adults_only = build_line(item, 2, Travelers(2))
    assert with_children.cost == adults_only.cost


def test_child_unit_price_must_not_be_negative_or_in_another_currency():
    with pytest.raises(InvalidPricingInput):
        priced(PricingUnit.PER_PERSON, "13", child="-1")
    with pytest.raises(InvalidPricingInput):
        CatalogItem("x", "Item", pen("13"), PricingUnit.PER_PERSON, Money(Decimal(1), Currency.USD))


def test_negative_child_quantity_rejected():
    with pytest.raises(InvalidPricingInput):
        QuoteLine(item(), 1, child_quantity=-1)
