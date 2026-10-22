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
    ItineraryDay,
    Quote,
    QuotedExtra,
    QuotedLine,
    QuotedOption,
    QuoteOption,
    QuoteRequest,
    RequestedExtra,
    RequestedItem,
    build_quote,
    build_quote_options,
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


def test_extra_label_is_trimmed_and_still_matched_to_its_breakdown():
    padded = request(extras=(RequestedExtra("  Upgrade ", (RequestedItem("hotel"),)),))

    quote = build_quote(padded, make_catalog(), POLICY)

    assert padded.extras[0].label == "Upgrade"
    assert [extra.label for extra in quote.extras] == ["Upgrade"]


# --- several options ---


def option(label, items, **overrides) -> QuoteOption:
    return QuoteOption(
        label,
        overrides.pop("subtitle", None),
        request(items=tuple(RequestedItem(i) for i in items), **overrides),
    )


def test_each_option_is_priced_alone_with_the_shared_policy():
    catalog = make_catalog()
    first = option("Option 1", ["van"], paid_locally=("ticket",))
    second = option("Option 2", ["van", "hotel"], paid_locally=("ticket",))

    quoted = build_quote_options((first, second), catalog, POLICY)

    assert all(isinstance(q, QuotedOption) for q in quoted)
    assert [q.label for q in quoted] == ["Option 1", "Option 2"]
    assert quoted[0].quote == build_quote(first.request, catalog, POLICY)
    assert quoted[1].quote == build_quote(second.request, catalog, POLICY)
    assert quoted[0].quote.breakdown.final_pen != quoted[1].quote.breakdown.final_pen
    assert quoted[0].quote.paid_locally == quoted[1].quote.paid_locally


def test_options_keep_their_own_days_and_subtitles():
    catalog = make_catalog()
    short = QuoteOption("Short", "Ends in Puno", request(days=1, items=(RequestedItem("hotel"),)))
    long = QuoteOption("Long", None, request(days=3, items=(RequestedItem("hotel"),)))

    quoted = build_quote_options((short, long), catalog, POLICY)

    assert quoted[0].subtitle == "Ends in Puno"
    assert quoted[1].subtitle is None
    assert quoted[0].quote.breakdown.final_pen.amount < quoted[1].quote.breakdown.final_pen.amount


def test_a_single_unlabeled_option_is_the_plain_quote():
    catalog = make_catalog()
    only = QuoteOption(None, None, request())

    (quoted,) = build_quote_options((only,), catalog, POLICY)

    assert quoted.label is None
    assert quoted.quote == build_quote(only.request, catalog, POLICY)


def test_option_label_and_subtitle_are_trimmed():
    built = QuoteOption("  Option 1 ", "  Puno  ", request())

    assert (built.label, built.subtitle) == ("Option 1", "Puno")


def test_a_blank_subtitle_is_allowed_and_means_none():
    assert QuoteOption("A", "   ", request()).subtitle is None


@pytest.mark.parametrize("label", ["", "   ", 5])
def test_an_option_label_must_be_text_or_none(label):
    with pytest.raises(InvalidPricingInput, match="label"):
        QuoteOption(label, None, request())


def test_an_option_needs_a_quote_request():
    with pytest.raises(InvalidPricingInput, match="request"):
        QuoteOption("A", None, "nope")


def test_no_options_is_rejected():
    with pytest.raises(InvalidPricingInput, match="at least one"):
        build_quote_options((), make_catalog(), POLICY)


def test_several_options_must_all_be_labeled():
    options = (option("A", ["van"]), QuoteOption(None, None, request()))
    with pytest.raises(InvalidPricingInput, match="label"):
        build_quote_options(options, make_catalog(), POLICY)


def test_option_labels_must_be_unique_after_trimming():
    options = (option("A", ["van"]), option(" A ", ["hotel"]))
    with pytest.raises(InvalidPricingInput, match="unique"):
        build_quote_options(options, make_catalog(), POLICY)


def test_options_must_be_quote_options():
    with pytest.raises(InvalidPricingInput, match="options"):
        build_quote_options((request(),), make_catalog(), POLICY)


def test_an_unknown_id_in_any_option_raises_the_catalog_error():
    options = (option("A", ["van"]), option("B", ["ghost"]))
    with pytest.raises(CatalogItemNotFound):
        build_quote_options(options, make_catalog(), POLICY)


# --- items assigned to days ---


def priced_line(request_days, unit_item="hotel", **item_kwargs):
    req = request(days=request_days, items=(RequestedItem(unit_item, **item_kwargs),))
    return build_quote(req, make_catalog(), POLICY).lines[0].line


def test_on_days_count_sets_the_priced_days_when_no_explicit_days():
    assert priced_line(3, on_days=(1, 2)).quantity == 2
    assert priced_line(3, on_days=(1, 2)) == priced_line(3, days=2)


def test_explicit_item_days_win_over_on_days():
    assert priced_line(3, days=1, on_days=(1, 2)).quantity == 1


def test_without_on_days_the_request_days_apply():
    assert priced_line(3).quantity == 3


def test_per_group_items_ignore_days_even_when_placed():
    placed = priced_line(3, on_days=(1, 2), unit_item="van")

    assert placed == priced_line(3, unit_item="van")


def test_on_days_are_stored_sorted_and_travel_with_the_quoted_line():
    item = RequestedItem("hotel", on_days=[2, 1])
    quote = build_quote(request(days=3, items=(item,)), make_catalog(), POLICY)

    assert item.on_days == (1, 2)
    assert quote.lines[0].on_days == (1, 2)


def test_items_default_to_no_placement():
    assert RequestedItem("van").on_days == ()


@pytest.mark.parametrize("on_days", [[0], [-1], [1, 1], "12", [True], [1.5], 3, ["1"]])
def test_requested_item_rejects_invalid_on_days(on_days):
    with pytest.raises(InvalidPricingInput, match="on_days"):
        RequestedItem("van", on_days=on_days)


def test_on_days_beyond_the_request_days_are_rejected():
    with pytest.raises(InvalidPricingInput, match="on_days"):
        request(days=2, items=(RequestedItem("van", on_days=(1, 3)),))


def test_extra_items_cannot_be_placed_on_days():
    with pytest.raises(InvalidPricingInput, match="on_days"):
        RequestedExtra("Upgrade", (RequestedItem("van", on_days=(1,)),))


def test_itinerary_day_title_is_trimmed_and_must_be_text():
    assert ItineraryDay(1, "  Arequipa - Chivay ").title == "Arequipa - Chivay"
    for title in ("", "   ", 5, None):
        with pytest.raises(InvalidPricingInput, match="title"):
            ItineraryDay(1, title)


@pytest.mark.parametrize("day", [0, -1, True, 1.5, "1"])
def test_itinerary_day_number_must_be_a_positive_integer(day):
    with pytest.raises(InvalidPricingInput, match="day"):
        ItineraryDay(day, "Title")


def test_an_option_keeps_its_sorted_itinerary_and_it_reaches_the_quoted_option():
    itinerary = [ItineraryDay(2, "Second"), ItineraryDay(1, "First")]
    built = QuoteOption("A", None, request(days=2), itinerary)

    (quoted,) = build_quote_options((built,), make_catalog(), POLICY)

    assert [d.day for d in built.itinerary] == [1, 2]
    assert quoted.itinerary == built.itinerary


def test_an_option_has_no_itinerary_by_default():
    assert QuoteOption("A", None, request()).itinerary == ()


def test_itinerary_days_must_lie_within_the_option_days():
    with pytest.raises(InvalidPricingInput, match="itinerary"):
        QuoteOption("A", None, request(days=2), (ItineraryDay(3, "Late"),))


def test_itinerary_days_must_be_unique():
    days = (ItineraryDay(1, "One"), ItineraryDay(1, "Again"))
    with pytest.raises(InvalidPricingInput, match="itinerary"):
        QuoteOption("A", None, request(days=2), days)


def test_itinerary_must_contain_itinerary_days():
    with pytest.raises(InvalidPricingInput, match="itinerary"):
        QuoteOption("A", None, request(days=2), ("nope",))


def test_itinerary_day_text_is_optional_stripped_and_must_be_text():
    assert ItineraryDay(1, "Title").text is None
    assert ItineraryDay(1, "Title", "  A fluent paragraph. ").text == "A fluent paragraph."
    for text in ("", "   ", 5):
        with pytest.raises(InvalidPricingInput, match="text"):
            ItineraryDay(1, "Title", text)
