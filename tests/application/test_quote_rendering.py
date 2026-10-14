from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from quotes.application.catalog import Catalog, CatalogEntry
from quotes.application.quote import QuoteRequest, RequestedItem, build_quote
from quotes.application.quote_rendering import QuoteDocument
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy
from quotes.domain.travelers import Travelers


def make_quote():
    item = CatalogItem("van", "Van", Money(Decimal("10.00"), Currency.PEN), PricingUnit.PER_GROUP)
    entry = CatalogEntry(item, "transport", "Furgoneta", "Van")
    request = QuoteRequest(2, Travelers(2), (RequestedItem("van"),))
    return build_quote(request, Catalog([entry]), PricingPolicy(margin_rate=Decimal("0.25")))


def document(**overrides) -> QuoteDocument:
    fields = {
        "quote": make_quote(),
        "client_name": "Ana Pérez",
        "title": "Cañón del Colca",
        "issued_on": date(2026, 10, 13),
        "signed_by": "Equipo de ventas",
    }
    fields.update(overrides)
    return QuoteDocument(**fields)


def test_valid_document_keeps_its_fields():
    doc = document()

    assert doc.client_name == "Ana Pérez"
    assert doc.issued_on == date(2026, 10, 13)


def test_texts_are_stored_stripped():
    doc = document(client_name="  Ana  ", title=" T\n", signed_by="\tEquipo ")

    assert (doc.client_name, doc.title, doc.signed_by) == ("Ana", "T", "Equipo")


@pytest.mark.parametrize("field", ["client_name", "title", "signed_by"])
@pytest.mark.parametrize("value", ["", "   ", None, 5])
def test_texts_must_be_non_empty_text(field, value):
    with pytest.raises(InvalidPricingInput):
        document(**{field: value})


def test_quote_must_be_a_quote():
    with pytest.raises(InvalidPricingInput):
        document(quote="not a quote")


@pytest.mark.parametrize("value", [datetime(2026, 10, 13, 8, 0, tzinfo=UTC), "2026-10-13", None])
def test_issued_on_must_be_a_plain_date(value):
    with pytest.raises(InvalidPricingInput):
        document(issued_on=value)


def test_document_is_immutable():
    with pytest.raises(FrozenInstanceError):
        document().title = "other"
