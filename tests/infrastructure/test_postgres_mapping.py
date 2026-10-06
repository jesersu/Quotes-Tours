"""Database-free tests: row mapping, constructor validation and connection failure."""

from decimal import Decimal

import psycopg
import pytest

from quotes.domain.catalog import PricingUnit
from quotes.domain.errors import InvalidPricingInput
from quotes.infrastructure.postgres_catalog import (
    CatalogDataError,
    PostgresCatalogRepository,
    build_catalog_load,
    map_local_payment_row,
    map_pricing_row,
)


def pricing_row(**overrides):
    row = {
        "id": "sample-item",
        "category": "test",
        "name_es": "Muestra",
        "name_en": "Sample",
        "unit": "group",
        "price_pen": Decimal("1.10"),
        "child_price_pen": None,
        "duration_days": None,
        "notes": None,
    }
    row.update(overrides)
    return row


def test_maps_a_valid_pricing_row():
    entry = map_pricing_row(pricing_row(unit="person"))
    assert entry.item.unit is PricingUnit.PER_PERSON


def test_unknown_unit_names_row_column_and_allowed_values():
    with pytest.raises(CatalogDataError) as info:
        map_pricing_row(pricing_row(unit="fortnight"))
    message = str(info.value)
    assert "sample-item" in message
    assert "unit" in message
    assert "fortnight" in message
    for allowed in ("day", "group", "person", "unit"):
        assert allowed in message


def test_missing_column_is_a_programming_error_not_a_data_error():
    row = pricing_row()
    del row["unit"]
    with pytest.raises(KeyError):
        map_pricing_row(row)


def test_invalid_domain_value_surfaces_as_domain_error():
    with pytest.raises(InvalidPricingInput):
        map_pricing_row(pricing_row(duration_days=0))


def test_unknown_visitor_category_names_row_column_and_allowed_values():
    row = {"id": "sample-ticket", "name_es": "Boleto", "name_en": "Ticket", "notes": None}
    prices = {"sample-ticket": [{"visitor_category": "martian", "price_pen": Decimal("1.00")}]}
    with pytest.raises(CatalogDataError) as info:
        map_local_payment_row(row, prices)
    message = str(info.value)
    assert "sample-ticket" in message
    assert "visitor_category" in message
    assert "martian" in message
    assert "foreign_adult" in message


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connect_timeout": 0},
        {"connect_timeout": -1},
        {"statement_timeout_ms": 0},
        {"statement_timeout_ms": -5},
        {"connect_timeout": 1.5},
        {"statement_timeout_ms": "10"},
        {"connect_timeout": True},
    ],
)
def test_constructor_rejects_non_positive_or_non_int_timeouts(kwargs):
    with pytest.raises(ValueError, match="positive integer"):
        PostgresCatalogRepository("postgresql://localhost/x", **kwargs)


def test_connection_failure_is_not_swallowed():
    repo = PostgresCatalogRepository(
        "postgresql://nobody@127.0.0.1:1/none", connect_timeout=1, statement_timeout_ms=1000
    )
    with pytest.raises(psycopg.OperationalError):
        repo.load()


def local_row(item_id="sample-ticket"):
    return {"id": item_id, "name_es": "Boleto", "name_en": "Ticket", "notes": None}


def price_row(item_id="sample-ticket", category="foreign_adult", price="1.00"):
    return {"item_id": item_id, "visitor_category": category, "price_pen": Decimal(price)}


def test_build_load_excludes_a_bad_pricing_row_and_reports_it():
    loaded = build_catalog_load(
        [pricing_row(id="good"), pricing_row(id="bad", unit="fortnight")], [], []
    )
    assert [e.id for e in loaded.catalog.items()] == ["good"]
    (issue,) = loaded.errors
    assert (issue.code, issue.subject_id) == ("invalid_row", "bad")
    assert "fortnight" in issue.message


def test_build_load_reports_domain_violations_as_row_errors():
    loaded = build_catalog_load([pricing_row(id="bad", duration_days=0)], [], [])
    (issue,) = loaded.errors
    assert issue.subject_id == "bad"
    assert "1 day" in issue.message


def test_build_load_excludes_a_local_item_without_prices():
    loaded = build_catalog_load([pricing_row()], [local_row("priceless")], [])
    assert loaded.catalog.local_payments() == ()
    (issue,) = loaded.errors
    assert (issue.code, issue.subject_id) == ("no_prices", "priceless")


def test_build_load_keeps_a_partially_priced_local_item_with_a_warning():
    loaded = build_catalog_load([pricing_row()], [local_row()], [price_row()])
    assert [e.id for e in loaded.catalog.local_payments()] == ["sample-ticket"]
    assert loaded.errors == ()
    (issue,) = loaded.warnings
    assert (issue.code, issue.subject_id) == ("missing_visitor_category", "sample-ticket")


def test_build_load_warns_about_an_empty_catalog():
    loaded = build_catalog_load([], [], [])
    assert [i.code for i in loaded.warnings] == ["empty_catalog"]
    assert loaded.ok


def test_build_load_lets_programming_errors_surface():
    row = pricing_row()
    del row["unit"]
    with pytest.raises(KeyError):
        build_catalog_load([row], [], [])


def test_build_load_reports_negative_price_and_keeps_valid_rows():
    loaded = build_catalog_load(
        [
            pricing_row(id="good-a"),
            pricing_row(id="negative", price_pen=Decimal("-1.00")),
            pricing_row(id="good-b"),
        ],
        [],
        [],
    )
    assert [e.id for e in loaded.catalog.items()] == ["good-a", "good-b"]
    (issue,) = loaded.errors
    assert (issue.code, issue.subject_id) == ("invalid_row", "negative")


def test_build_load_reports_child_price_on_a_non_person_unit():
    loaded = build_catalog_load(
        [
            pricing_row(id="good"),
            pricing_row(id="group-child", unit="group", child_price_pen=Decimal("1.00")),
        ],
        [],
        [],
    )
    assert [e.id for e in loaded.catalog.items()] == ["good"]
    (issue,) = loaded.errors
    assert (issue.code, issue.subject_id) == ("invalid_row", "group-child")
    assert "child_price_pen" in issue.message


def test_child_price_on_a_person_unit_is_accepted():
    entry = map_pricing_row(
        pricing_row(unit="person", price_pen=Decimal("2.00"), child_price_pen=Decimal("1.00"))
    )
    assert entry.item.child_unit_price is not None


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_build_load_reports_non_finite_numbers(value):
    loaded = build_catalog_load(
        [pricing_row(id="good"), pricing_row(id="odd", price_pen=value)], [], []
    )
    assert [e.id for e in loaded.catalog.items()] == ["good"]
    (issue,) = loaded.errors
    assert (issue.code, issue.subject_id) == ("invalid_row", "odd")


def test_build_load_reports_non_finite_local_price_and_keeps_valid_rows():
    loaded = build_catalog_load(
        [],
        [local_row("good-ticket"), local_row("odd-ticket")],
        [price_row("good-ticket"), price_row("odd-ticket", price="NaN")],
    )
    assert [e.id for e in loaded.catalog.local_payments()] == ["good-ticket"]
    (issue,) = loaded.errors
    assert issue.subject_id == "odd-ticket"


def test_build_load_still_raises_on_a_missing_column():
    row = pricing_row()
    del row["price_pen"]
    with pytest.raises(KeyError):
        build_catalog_load([row], [], [])
