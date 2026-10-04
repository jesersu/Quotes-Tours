from decimal import Decimal

import pytest

from quotes.domain.catalog import CatalogItem, PricingUnit, QuoteLine
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy, price_quote
from quotes.domain.travelers import Travelers

D = Decimal


def pen(amount: str | int) -> Money:
    return Money(D(amount), Currency.PEN)


def ticket() -> LocalPaymentInfo:
    return LocalPaymentInfo(
        "Valley entrance ticket",
        (
            LocalPrice(VisitorCategory.LATIN_AMERICAN_ADULT, pen(31)),
            LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(77)),
            LocalPrice(VisitorCategory.CHILD_6_15, pen(13)),
        ),
    )


def main_lines() -> list[QuoteLine]:
    item = CatalogItem("van", "Van", pen(300), PricingUnit.PER_GROUP)
    return [QuoteLine(item, 1)]


def test_price_lookup_by_category():
    assert ticket().price_for(VisitorCategory.FOREIGN_ADULT) == pen(77)


def test_missing_category_lookup_rejected():
    info = LocalPaymentInfo("Ticket", (LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(77)),))
    with pytest.raises(InvalidPricingInput):
        info.price_for(VisitorCategory.CHILD_6_15)


def test_blank_label_rejected():
    with pytest.raises(InvalidPricingInput):
        LocalPaymentInfo(" ", (LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(1)),))


def test_requires_at_least_one_price():
    with pytest.raises(InvalidPricingInput):
        LocalPaymentInfo("Ticket", ())


def test_duplicate_categories_rejected():
    prices = (
        LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(1)),
        LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(2)),
    )
    with pytest.raises(InvalidPricingInput):
        LocalPaymentInfo("Ticket", prices)


def test_price_must_be_non_negative_pen():
    with pytest.raises(InvalidPricingInput):
        LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(-1))
    with pytest.raises(InvalidPricingInput):
        LocalPrice(VisitorCategory.FOREIGN_ADULT, Money(D(1), Currency.USD))


def test_paid_locally_items_are_returned_but_excluded_from_totals():
    policy = PricingPolicy(margin_rate=D("0.15"))
    travelers = Travelers(2)

    without = price_quote(main_lines(), travelers, policy)
    with_info = price_quote(main_lines(), travelers, policy, paid_locally=[ticket()])

    assert with_info.paid_locally == (ticket(),)
    assert without.paid_locally == ()
    for field in ("subtotal_pen", "margin_pen", "sale_pen", "final_pen", "final_usd"):
        assert getattr(with_info, field) == getattr(without, field)
