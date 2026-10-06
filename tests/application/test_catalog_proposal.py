from decimal import Decimal

import pytest

from quotes.application.catalog_proposal import (
    RawRow,
    clean_name,
    propose_catalog,
    slugify,
)

SLUG = __import__("re").compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def rows(*pairs):
    return [RawRow(name, Decimal(price), i + 4) for i, (name, price) in enumerate(pairs)]


def one(name, price="12.34"):
    proposal = propose_catalog(rows((name, price)))
    return (proposal.pricing_items + proposal.local_payments)[0]


def test_slugify_strips_accents_and_collapses():
    assert slugify("  CAMPIÑA   Tour + Uyo/Uyo ") == "campina-tour-uyo-uyo"


def test_slugify_never_empty():
    assert slugify("+++") == "item"


def test_clean_name_normalises_whitespace_and_case_but_keeps_spelling():
    assert clean_name("INGRSO AGUAS  TERMALES   CHIVAY") == "Ingrso aguas termales chivay"


@pytest.mark.parametrize("days", [1, 2, 3, 4, 5])
def test_transport_parses_duration(days):
    unit = "DIA" if days == 1 else "DIAS"
    entry = one(f"MOVILIDAD COLCA  {days} {unit}")
    assert (entry["category"], entry["unit"], entry["duration_days"]) == (
        "transport",
        "group",
        days,
    )


def test_puno_variants_have_distinct_ids():
    proposal = propose_catalog(
        rows(("MOVILIDAD COLCA 2 DIAS", "310"), ("MOVILIDAD COLCA 2 DIAS + PUNO", "55.5"))
    )
    ids = [e["id"] for e in proposal.pricing_items]
    assert len(set(ids)) == 2
    assert all(SLUG.match(i) for i in ids)
    assert "puno" in proposal.pricing_items[1]["name_en"].lower()


@pytest.mark.parametrize(
    ("name", "category", "unit"),
    [
        ("TRASLADO AEROPUERTO AQP-HOTEL", "transfer", "group"),
        ("TRASLADO HOTEL - AEROPUERTO", "transfer", "group"),
        ("GUIA OFICIAL  CITY TOUR", "guide", "day"),
        ("DESAYUNO COLCA BUFFET", "meal", "person"),
        ("ALMUERZO COLCA BUFFET", "meal", "person"),
        ("CENA  COLCA  CON SHOW A LA CARTA", "meal", "person"),
        ("TICKETS CITY TOUR", "entrance", "person"),
        ("INGRESO AGUAS TERMALES  YANQUE", "entrance", "person"),
        ("INGRSO AGUAS TERMALES CHIVAY", "entrance", "person"),
        ("CABALGATA  + UYO UYO", "activity", "person"),
        ("SOMETHING UNKNOWN", "other", "unit"),
    ],
)
def test_category_and_unit_rules(name, category, unit):
    entry = one(name)
    assert (entry["category"], entry["unit"]) == (category, unit)


def test_english_names_from_dictionary_and_fallback():
    assert one("DESAYUNO COLCA BUFFET")["name_en"] == "Colca buffet breakfast"
    assert one("ALMUERZO COLCA BUFFET")["name_en"] == "Colca buffet lunch"
    assert one("GUIA OFICIAL PILLONES")["name_en"] == "Official guide, Pillones"
    assert one("TICKETS PILLONES")["name_en"] == "Pillones entrance ticket"
    assert one("INGRSO AGUAS TERMALES CHIVAY")["name_en"] == "Hot springs entrance, Chivay"
    assert one("TRASLADO AEROPUERTO AQP-HOTEL")["name_en"] == "Airport transfer"
    assert one("SOMETHING UNKNOWN")["name_en"] == "Something unknown"


def test_every_entry_needs_review_with_hint_and_defaults():
    proposal = propose_catalog(rows(("DESAYUNO COLCA BUFFET", "12.34"), ("X", "1")))
    for entry in proposal.pricing_items:
        assert entry["needs_review"] is True
        assert entry["review_hint"]
        assert entry["child_price_pen"] is None
        assert entry["active"] is True
        assert entry["notes"] is None
    assert "child" in proposal.pricing_items[0]["review_hint"]


def test_price_is_two_place_string_and_source_name_kept_verbatim():
    entry = one("TICKETS  CITY TOUR", "55.5")
    assert entry["price_pen"] == "55.50"
    assert entry["source_name"] == "TICKETS  CITY TOUR"


def test_duplicate_names_get_distinct_ids():
    proposal = propose_catalog(rows(("TICKETS CITY TOUR", "1.5"), ("TICKETS  CITY TOUR", "2.5")))
    assert [e["id"] for e in proposal.pricing_items] == ["tickets-city-tour", "tickets-city-tour-2"]


def test_colca_ticket_is_a_local_payment_not_a_pricing_item():
    proposal = propose_catalog(rows(("TICKETS  INGRESO COLCA", "310"), ("TICKETS PILLONES", "1")))
    assert [e["id"] for e in proposal.pricing_items] == ["tickets-pillones"]
    (local,) = proposal.local_payments
    assert local["id"] == "colca-tourist-ticket"
    assert local["name_en"] == "Colca tourist ticket"
    assert local["prices"] == {
        "latin_american_adult": None,
        "foreign_adult": "310.00",
        "child_6_15": None,
    }
    assert local["needs_review"] is True
    assert "latin_american_adult" in local["review_hint"]
