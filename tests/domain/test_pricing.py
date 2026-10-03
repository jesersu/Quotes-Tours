from decimal import Decimal

import pytest

from quotes.domain.catalog import CatalogItem, PricingUnit, QuoteLine
from quotes.domain.errors import CurrencyMismatchError, InvalidPricingInput
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy, price_quote
from quotes.domain.travelers import Travelers

D = Decimal


def pen(amount: str | int) -> Money:
    return Money(D(amount), Currency.PEN)


def line(price: str | int, quantity: int = 1, unit=PricingUnit.PER_GROUP) -> QuoteLine:
    item = CatalogItem("x", "Item", pen(price), unit)
    return QuoteLine(item, quantity)


def policy(margin="0", fx="1", step="50") -> PricingPolicy:
    return PricingPolicy(margin_rate=D(margin), fx_rate=D(fx), usd_rounding_step=D(step))


def test_synthetic_two_day_quote_two_travelers():
    # 2 days, 2 travelers (synthetic prices).
    lines = [
        line(900, 1, PricingUnit.PER_GROUP),  # transport: 900 flat
        line(150, 2, PricingUnit.PER_DAY),  # guide: 150 x 2 days = 300
        line(40, 2, PricingUnit.PER_PERSON),  # lunch: 40 x 2 = 80
        line(60, 2, PricingUnit.PER_PERSON),  # tickets: 60 x 2 = 120
    ]
    result = price_quote(
        lines, travelers=Travelers(2), policy=policy(margin="0.25", fx="3.4", step="50")
    )

    assert result.subtotal_pen == pen(1400)  # 900 + 300 + 80 + 120
    assert result.margin_pen == pen(350)  # 1400 x 0.25
    assert result.sale_pen == pen(1750)  # 1400 + 350
    # 1750 / 3.4 = 514.705882...
    assert result.sale_usd_exact.amount.quantize(D("0.01")) == D("514.71")
    assert result.final_usd == Money(D(550), Currency.USD)  # rounded UP to step 50
    assert result.final_pen == pen("1870.00")  # 550 x 3.4
    assert result.per_person_usd == Money(D("275.00"), Currency.USD)  # 550 / 2
    assert result.per_person_pen == pen("935.00")  # 1870 / 2
    assert result.lines == tuple(lines)


def test_usd_exact_multiple_of_step_stays():
    result = price_quote([line(500)], Travelers(1), policy(fx="1", step="50"))
    assert result.final_usd.amount == D(500)


def test_usd_just_above_multiple_rounds_up():
    result = price_quote([line("500.01")], Travelers(1), policy(fx="1", step="50"))
    assert result.final_usd.amount == D(550)


def test_usd_just_below_multiple_rounds_up_to_it():
    result = price_quote([line("499.99")], Travelers(1), policy(fx="1", step="50"))
    assert result.final_usd.amount == D(500)


def test_custom_step():
    # 512.34 USD rounds up to the next multiple of the step.
    assert price_quote([line("512.34")], Travelers(1), policy(step="100")).final_usd.amount == D(
        600
    )
    assert price_quote([line("512.34")], Travelers(1), policy(step="50")).final_usd.amount == D(550)
    assert price_quote([line("512.34")], Travelers(1), policy(step="10")).final_usd.amount == D(520)


def test_zero_margin():
    result = price_quote([line(100)], Travelers(1), policy(margin="0"))
    assert result.margin_pen == pen(0)
    assert result.sale_pen == pen(100)


def test_per_person_rounds_half_up_to_cents():
    result = price_quote([line(100)], Travelers(3), policy(fx="1", step="50"))
    assert result.final_usd.amount == D(100)
    assert result.per_person_usd == Money(D("33.33"), Currency.USD)
    assert result.per_person_pen == pen("33.33")


def test_empty_lines_rejected():
    with pytest.raises(InvalidPricingInput):
        price_quote([], Travelers(1), policy())


def test_non_pen_line_rejected():
    usd_item = CatalogItem("x", "Item", Money(D(10), Currency.USD), PricingUnit.PER_GROUP)
    with pytest.raises(CurrencyMismatchError):
        price_quote([QuoteLine(usd_item, 1)], Travelers(1), policy())


def test_negative_margin_rejected():
    with pytest.raises(InvalidPricingInput):
        policy(margin="-0.01")


@pytest.mark.parametrize("fx", ["0", "-3.5"])
def test_fx_must_be_positive(fx):
    with pytest.raises(InvalidPricingInput):
        policy(fx=fx)


@pytest.mark.parametrize("step", ["0", "-50"])
def test_step_must_be_positive(step):
    with pytest.raises(InvalidPricingInput):
        policy(step=step)


def test_policy_rejects_float_inputs():
    with pytest.raises(InvalidPricingInput):
        PricingPolicy(margin_rate=0.2, fx_rate=D("3.5"))  # type: ignore[arg-type]


def test_default_step_is_fifty():
    assert PricingPolicy(margin_rate=D("0.3"), fx_rate=D("3.5")).usd_rounding_step == D(50)
