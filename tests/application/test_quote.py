from decimal import Decimal

import pytest

from quotes.application.catalog import (
    Catalog,
    CatalogEntry,
    CatalogItemNotFound,
    LocalPaymentEntry,
    LocalPaymentNotFound,
)
from quotes.application.quote import (
    Quote,
    QuotedExtra,
    QuotedLine,
    QuoteRequest,
    RequestedExtra,
    RequestedItem,
    build_quote,
)
from quotes.domain.catalog import CatalogItem, PricingUnit, QuoteLine
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.extras import price_optional_extras
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy, price_quote
from quotes.domain.travelers import Travelers

POLICY = PricingPolicy(margin_rate=Decimal("0.25"))


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def entry(item_id: str, unit: PricingUnit, price: str, child: str | None = None) -> CatalogEntry:
    item = CatalogItem(
        item_id, f"Item {item_id}", pen(price), unit, pen(child) if child is not None else None
    )
    return CatalogEntry(
        item=item,
        category="tour",
        name_es=f"Item {item_id} es",
        name_en=f"Item {item_id} en",
    )


def local_entry(item_id: str = "ticket") -> LocalPaymentEntry:
    info = LocalPaymentInfo(
        "Sample ticket", (LocalPrice(VisitorCategory.FOREIGN_ADULT, pen("2.50")),)
    )
    return LocalPaymentEntry(item_id, info, "Boleto es", "Ticket en")


def make_catalog() -> Catalog:
    return Catalog(
        [
            entry("van", PricingUnit.PER_GROUP, "10.00"),
            entry("hotel", PricingUnit.PER_DAY, "3.00"),
            entry("tour", PricingUnit.PER_PERSON, "2.00", child="1.00"),
            entry("meal", PricingUnit.PER_UNIT, "0.50"),
        ],
        [local_entry("ticket"), local_entry("other-ticket")],
    )


def request(**overrides) -> QuoteRequest:
    fields = {
        "days": 2,
        "travelers": Travelers(2),
        "items": (RequestedItem("van"),),
    }
    fields.update(overrides)
    return QuoteRequest(**fields)


def line_of(catalog: Catalog, item_id: str, quantity: int, child_quantity: int = 0) -> QuoteLine:
    return QuoteLine(catalog.get_item(item_id).item, quantity, child_quantity)


# --- build_quote ---


def test_mixed_request_breakdown_equals_price_quote_on_hand_built_lines():
    catalog = make_catalog()
    travelers = Travelers(2, (4, 8, 12))
    req = request(
        days=3,
        travelers=travelers,
        items=(
            RequestedItem("van"),
            RequestedItem("hotel"),
            RequestedItem("tour"),
            RequestedItem("meal", quantity=5),
        ),
    )

    quote = build_quote(req, catalog, POLICY)

    expected_lines = [
        line_of(catalog, "van", 1),
        line_of(catalog, "hotel", 3),
        line_of(catalog, "tour", 2, 2),
        line_of(catalog, "meal", 5),
    ]
    assert [q.line for q in quote.lines] == expected_lines
    assert quote.breakdown == price_quote(expected_lines, travelers, POLICY)
    assert quote.request is req


def test_quoted_lines_pair_catalog_entries_with_priced_lines():
    catalog = make_catalog()

    quote = build_quote(
        request(items=(RequestedItem("van"), RequestedItem("hotel"))), catalog, POLICY
    )

    assert [q.entry for q in quote.lines] == [catalog.get_item("van"), catalog.get_item("hotel")]
    assert all(isinstance(q, QuotedLine) for q in quote.lines)


def test_item_days_override_the_request_days():
    catalog = make_catalog()
    req = request(days=5, items=(RequestedItem("hotel", days=2), RequestedItem("hotel")))

    quote = build_quote(req, catalog, POLICY)

    assert [q.line.quantity for q in quote.lines] == [2, 5]


def test_children_flow_through_to_quantities():
    catalog = make_catalog()
    # 3 and 5 are free, 6 and 15 pay the child price, 16 pays the adult price.
    travelers = Travelers(2, (3, 5, 6, 15, 16))

    quote = build_quote(
        request(travelers=travelers, items=(RequestedItem("tour"),)), catalog, POLICY
    )

    (quoted,) = quote.lines
    assert quoted.line.quantity == 3
    assert quoted.line.child_quantity == 2


def test_extra_is_priced_separately_and_stays_out_of_the_main_total():
    catalog = make_catalog()
    travelers = Travelers(2)
    main = request(travelers=travelers, items=(RequestedItem("van"),))
    with_extra = request(
        travelers=travelers,
        items=(RequestedItem("van"),),
        extras=(
            RequestedExtra("Boat ride", (RequestedItem("tour"), RequestedItem("meal", quantity=2))),
        ),
    )

    baseline = build_quote(main, catalog, POLICY)
    quote = build_quote(with_extra, catalog, POLICY)

    assert quote.breakdown == baseline.breakdown
    (extra,) = quote.extras
    assert isinstance(extra, QuotedExtra)
    assert extra.label == "Boat ride"
    extra_lines = [line_of(catalog, "tour", 2), line_of(catalog, "meal", 2)]
    assert [q.line for q in extra.lines] == extra_lines
    assert (
        extra.breakdown
        == price_optional_extras([("Boat ride", extra_lines)], travelers, POLICY)[0].breakdown
    )
    assert extra.breakdown.sale_pen != quote.breakdown.sale_pen


def test_extras_are_not_rounded_even_when_the_policy_rounds_usd():
    catalog = make_catalog()
    policy = PricingPolicy(margin_rate=Decimal("0.25"), usd_rounding_step=Decimal("5"))
    extra = RequestedExtra("Boat ride", (RequestedItem("van"),))

    quote = build_quote(request(extras=(extra,)), catalog, policy)

    line = line_of(catalog, "van", 1)
    expected = price_optional_extras([("Boat ride", [line])], Travelers(2), policy)[0].breakdown
    assert quote.extras[0].breakdown == expected


def test_paid_locally_is_present_and_outside_the_totals():
    catalog = make_catalog()
    baseline = build_quote(request(), catalog, POLICY)

    quote = build_quote(request(paid_locally=("ticket", "other-ticket")), catalog, POLICY)

    assert quote.paid_locally == (
        catalog.local_payment("ticket"),
        catalog.local_payment("other-ticket"),
    )
    assert quote.breakdown.paid_locally == tuple(e.info for e in quote.paid_locally)
    assert quote.breakdown.subtotal_pen == baseline.breakdown.subtotal_pen
    assert quote.breakdown.final_pen == baseline.breakdown.final_pen
    assert quote.breakdown.final_usd == baseline.breakdown.final_usd


def test_result_is_a_quote_with_no_extras_or_local_payments_by_default():
    quote = build_quote(request(), make_catalog(), POLICY)

    assert isinstance(quote, Quote)
    assert quote.extras == ()
    assert quote.paid_locally == ()


def test_unknown_item_id_propagates_the_catalog_error():
    with pytest.raises(CatalogItemNotFound):
        build_quote(request(items=(RequestedItem("missing"),)), make_catalog(), POLICY)


def test_unknown_item_id_inside_an_extra_propagates_the_catalog_error():
    extra = RequestedExtra("Boat ride", (RequestedItem("missing"),))

    with pytest.raises(CatalogItemNotFound):
        build_quote(request(extras=(extra,)), make_catalog(), POLICY)


def test_unknown_local_payment_id_propagates_the_catalog_error():
    with pytest.raises(LocalPaymentNotFound):
        build_quote(request(paid_locally=("missing",)), make_catalog(), POLICY)


def test_per_unit_item_without_quantity_is_rejected_by_the_domain():
    with pytest.raises(InvalidPricingInput):
        build_quote(request(items=(RequestedItem("meal"),)), make_catalog(), POLICY)


def test_duplicate_extra_labels_are_rejected_by_the_domain():
    extras = (
        RequestedExtra("Boat ride", (RequestedItem("van"),)),
        RequestedExtra("Boat ride", (RequestedItem("hotel"),)),
    )

    with pytest.raises(InvalidPricingInput, match="unique"):
        build_quote(request(extras=extras), make_catalog(), POLICY)


# --- request validation ---


@pytest.mark.parametrize("item_id", ["", "  ", None, 3])
def test_requested_item_rejects_invalid_id(item_id):
    with pytest.raises(InvalidPricingInput):
        RequestedItem(item_id)


@pytest.mark.parametrize("days", [0, -1, 1.5, True, "2"])
def test_requested_item_rejects_invalid_days(days):
    with pytest.raises(InvalidPricingInput):
        RequestedItem("van", days=days)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2"])
def test_requested_item_rejects_invalid_quantity(quantity):
    with pytest.raises(InvalidPricingInput):
        RequestedItem("van", quantity=quantity)


@pytest.mark.parametrize("label", ["", "  ", None])
def test_requested_extra_rejects_blank_label(label):
    with pytest.raises(InvalidPricingInput):
        RequestedExtra(label, (RequestedItem("van"),))


def test_requested_extra_requires_items():
    with pytest.raises(InvalidPricingInput):
        RequestedExtra("Boat ride", ())


@pytest.mark.parametrize("days", [0, -1, 1.5, True, "2"])
def test_request_rejects_invalid_days(days):
    with pytest.raises(InvalidPricingInput):
        request(days=days)


def test_request_requires_items():
    with pytest.raises(InvalidPricingInput):
        request(items=())


def test_request_rejects_non_travelers():
    with pytest.raises(InvalidPricingInput):
        request(travelers=2)


def test_request_rejects_duplicate_paid_locally_ids():
    with pytest.raises(InvalidPricingInput, match="ticket"):
        request(paid_locally=("ticket", "ticket"))


@pytest.mark.parametrize("ids", [("",), ("  ",)])
def test_request_rejects_blank_paid_locally_id(ids):
    with pytest.raises(InvalidPricingInput):
        request(paid_locally=ids)


def test_request_rejects_wrong_element_types():
    with pytest.raises(InvalidPricingInput):
        request(items=("van",))
    with pytest.raises(InvalidPricingInput):
        request(extras=("Boat ride",))


def test_lists_are_normalized_to_tuples():
    extra = RequestedExtra("Boat ride", [RequestedItem("van")])
    req = QuoteRequest(
        days=2,
        travelers=Travelers(2),
        items=[RequestedItem("van")],
        extras=[extra],
        paid_locally=["ticket"],
    )

    assert extra.items == (RequestedItem("van"),)
    assert req.items == (RequestedItem("van"),)
    assert req.extras == (extra,)
    assert req.paid_locally == ("ticket",)


def two_extras_request() -> QuoteRequest:
    return request(
        extras=(
            RequestedExtra("Upgrade", (RequestedItem("hotel"),)),
            RequestedExtra("Dinner", (RequestedItem("meal", quantity=4),)),
        )
    )


def assert_each_extra_keeps_its_own_lines_and_breakdown(quote: Quote) -> None:
    by_label = {extra.label: extra for extra in quote.extras}
    assert set(by_label) == {"Upgrade", "Dinner"}
    for label, item_id in (("Upgrade", "hotel"), ("Dinner", "meal")):
        extra = by_label[label]
        assert [quoted.entry.id for quoted in extra.lines] == [item_id]
        (expected,) = price_optional_extras(
            [(label, [quoted.line for quoted in extra.lines])], Travelers(2), POLICY
        )
        assert extra.breakdown == expected.breakdown
    assert by_label["Upgrade"].breakdown != by_label["Dinner"].breakdown


def test_each_extra_keeps_its_own_lines_and_breakdown():
    quote = build_quote(two_extras_request(), make_catalog(), POLICY)

    assert [extra.label for extra in quote.extras] == ["Upgrade", "Dinner"]
    assert_each_extra_keeps_its_own_lines_and_breakdown(quote)


def test_extras_are_matched_by_label_not_by_position(monkeypatch):
    def reversed_pricing(extras, travelers, policy):
        return tuple(reversed(price_optional_extras(extras, travelers, policy)))

    monkeypatch.setattr("quotes.application.quote.price_optional_extras", reversed_pricing)

    quote = build_quote(two_extras_request(), make_catalog(), POLICY)

    assert [extra.label for extra in quote.extras] == ["Upgrade", "Dinner"]
    assert_each_extra_keeps_its_own_lines_and_breakdown(quote)


@pytest.mark.parametrize("field", ["items", "extras", "paid_locally"])
@pytest.mark.parametrize("value", [None, 5, "ticket", b"ticket"])
def test_request_rejects_collections_that_are_not_lists(field, value):
    with pytest.raises(InvalidPricingInput):
        request(**{field: value})


@pytest.mark.parametrize("items", [None, 5, "van", b"van"])
def test_requested_extra_rejects_items_that_are_not_a_list(items):
    with pytest.raises(InvalidPricingInput):
        RequestedExtra("Upgrade", items)
