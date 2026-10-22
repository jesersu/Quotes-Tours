import dataclasses
import datetime
from decimal import Decimal

import pytest

from quotes.application.catalog import Catalog, CatalogEntry, LocalPaymentEntry
from quotes.application.planner import (
    PlannedDay,
    PlannedExtra,
    PlannedItem,
    PlannedOption,
    PlannedRequest,
    PlannerCatalog,
    PlannerItem,
    PlannerLocalPayment,
    PlannerUnavailable,
    QuotePlanner,
    planner_catalog,
    to_request_data,
)
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.infrastructure.quote_request_file import (
    RequestNeedsReview,
    dump_quote_request,
    parse_quote_request,
)

SECRET = "777.77"


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def make_catalog() -> Catalog:
    van = CatalogEntry(
        item=CatalogItem("van", "Van", pen(SECRET), PricingUnit.PER_GROUP),
        category="transport",
        name_es="Camioneta",
        name_en="Van",
        duration_days=2,
        region="Arequipa",
        description_es="Traslado privado",
        description_en="Private transfer",
    )
    tour = CatalogEntry(
        item=CatalogItem("tour", "Tour", pen(SECRET), PricingUnit.PER_PERSON, pen("555.55")),
        category="tour",
        name_es="Tour",
        name_en="Tour",
    )
    horse = CatalogEntry(
        item=CatalogItem("horse", "Horse", pen(SECRET), PricingUnit.PER_UNIT),
        category="extra",
        name_es="Caballo",
        name_en="Horse",
    )
    info = LocalPaymentInfo("Ticket", (LocalPrice(VisitorCategory.FOREIGN_ADULT, pen(SECRET)),))
    return Catalog([van, tour, horse], [LocalPaymentEntry("ticket", info, "Boleto", "Ticket")])


VIEW = planner_catalog(make_catalog())


def request(**overrides) -> PlannedRequest:
    fields = {
        "client": "Smith family",
        "title": "Colca, 2 days",
        "language": "en",
        "days": 2,
        "adults": 2,
        "child_ages": (8,),
        "options": (PlannedOption(None, None, None, (PlannedItem("van"),)),),
    }
    return PlannedRequest(**{**fields, **overrides})


def test_planner_catalog_copies_ids_names_units_and_text():
    van = VIEW.items[0]
    assert van == PlannerItem(
        id="van",
        category="transport",
        name_es="Camioneta",
        name_en="Van",
        unit="per_group",
        duration_days=2,
        region="Arequipa",
        description_es="Traslado privado",
        description_en="Private transfer",
    )
    assert VIEW.item_ids() == ("van", "tour", "horse")
    assert VIEW.local_payments == (PlannerLocalPayment("ticket", "Boleto", "Ticket"),)
    assert VIEW.local_payment_ids() == ("ticket",)


def _walk(value):
    yield value
    if dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, tuple):
        for inner in value:
            yield from _walk(inner)


def test_planner_catalog_carries_no_price_at_all():
    for value in _walk(VIEW):
        assert not isinstance(value, Decimal | Money | float)
    for cls in (PlannerCatalog, PlannerItem, PlannerLocalPayment):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not names & {"price", "unit_price", "child_unit_price", "margin", "info", "item"}
    assert SECRET not in repr(VIEW)
    assert "555.55" not in repr(VIEW)


def test_plain_request_uses_top_level_keys():
    data = to_request_data(request(), VIEW)
    assert data["client"] == "Smith family"
    assert data["language"] == "en"
    assert data["days"] == 2
    assert data["travelers"] == {"adults": 2, "child_ages": [8]}
    assert data["items"] == [{"id": "van"}]
    assert "options" not in data
    assert data["needs_review"] is True


def test_several_options_use_the_options_key():
    options = (
        PlannedOption("Option 1", "Ends in Puno", 3, (PlannedItem("van"),)),
        PlannedOption("Option 2", None, None, (PlannedItem("tour"),)),
    )
    data = to_request_data(request(options=options), VIEW)
    assert "items" not in data
    assert "itinerary" not in data
    assert data["options"][0] == {
        "label": "Option 1",
        "subtitle": "Ends in Puno",
        "days": 3,
        "items": [{"id": "van"}],
    }
    assert data["options"][1] == {"label": "Option 2", "items": [{"id": "tour"}]}


def test_item_fields_are_written_only_when_set():
    items = (PlannedItem("van", on_days=(1, 2), days=2, quantity=3), PlannedItem("tour"))
    option = PlannedOption(None, None, None, items)
    data = to_request_data(request(options=(option,)), VIEW)
    assert data["items"] == [
        {"id": "van", "on_days": [1, 2], "days": 2, "quantity": 3},
        {"id": "tour"},
    ]


def test_extras_and_itinerary_are_written():
    option = PlannedOption(
        None,
        None,
        None,
        (PlannedItem("van"),),
        extras=(PlannedExtra("Horseback ride", (PlannedItem("horse"),)),),
        itinerary=(PlannedDay(1, "Arequipa - Chivay"),),
    )
    data = to_request_data(request(options=(option,)), VIEW)
    assert data["extras"] == [{"label": "Horseback ride", "items": [{"id": "horse"}]}]
    assert data["itinerary"] == [{"day": 1, "title": "Arequipa - Chivay"}]


def test_unknown_ids_are_dropped_with_a_hint_naming_them():
    option = PlannedOption(
        None,
        None,
        None,
        (PlannedItem("van"), PlannedItem("ghost")),
        extras=(PlannedExtra("Lost", (PlannedItem("phantom"),)),),
    )
    planned = request(options=(option,), paid_locally=("ticket", "unknown-ticket"))
    data = to_request_data(planned, VIEW)
    assert data["items"] == [{"id": "van"}]
    assert "extras" not in data
    assert data["paid_locally"] == ["ticket"]
    hints = " | ".join(data["review_hints"])
    assert "ghost" in hints
    assert "phantom" in hints
    assert "unknown-ticket" in hints
    assert "Lost" in hints


def test_an_option_left_without_items_is_kept_with_a_hint():
    options = (
        PlannedOption("Option 1", None, None, (PlannedItem("ghost"),)),
        PlannedOption("Option 2", None, None, (PlannedItem("van"),)),
    )
    data = to_request_data(request(options=options), VIEW)
    assert data["options"][0]["items"] == []
    assert any("Option 1" in hint and "no items" in hint for hint in data["review_hints"])


def test_owner_only_fields_are_left_empty_with_hints():
    data = to_request_data(request(hints=("Client wants a quiet hotel",)), VIEW)
    assert data["signed_by"] is None
    assert data["pricing"] == {"margin_rate": None}
    assert data["review_hints"][0] == "Client wants a quiet hotel"
    assert "Set signed_by" in data["review_hints"]
    assert "Set pricing.margin_rate" in data["review_hints"]


def test_the_draft_is_gated_until_the_owner_reviews_it():
    with pytest.raises(RequestNeedsReview) as caught:
        parse_quote_request(to_request_data(request(), VIEW))
    assert "Set pricing.margin_rate" in caught.value.hints


@pytest.mark.parametrize("shape", ["plain", "options"])
def test_reviewed_draft_round_trips_through_the_reader(shape):
    if shape == "plain":
        options = (
            PlannedOption(
                None,
                None,
                None,
                (PlannedItem("van"), PlannedItem("tour", on_days=(1,))),
                extras=(PlannedExtra("Horseback ride", (PlannedItem("horse"),)),),
                itinerary=(PlannedDay(1, "Arequipa - Chivay"),),
            ),
        )
    else:
        options = (
            PlannedOption("Option 1", "Ends in Puno", 2, (PlannedItem("van"),)),
            PlannedOption("Option 2", None, None, (PlannedItem("tour"),)),
        )
    data = to_request_data(request(options=options, paid_locally=("ticket",)), VIEW)
    data["needs_review"] = False
    data["signed_by"] = "Sales team"
    data["pricing"] = {"margin_rate": "0.25"}
    parsed = parse_quote_request(data)
    assert parsed.client_name == "Smith family"
    assert len(parsed.options) == len(options)
    assert dump_quote_request(data)


def test_dump_accepts_the_draft_as_is():
    text = dump_quote_request(to_request_data(request(), VIEW))
    assert "needs_review: true" in text
    assert "Set signed_by" in text


class FakePlanner:
    def plan(self, message: str, catalog: PlannerCatalog, today: datetime.date) -> PlannedRequest:
        return request()


def test_a_fake_planner_satisfies_the_port():
    assert isinstance(FakePlanner(), QuotePlanner)
    assert not isinstance(object(), QuotePlanner)


def test_planner_unavailable_is_an_exception():
    assert issubclass(PlannerUnavailable, Exception)
