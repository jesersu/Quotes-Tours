"""Database-free tests: row mapping, constructor validation and connection failure."""

from decimal import Decimal

import psycopg
import pytest

from quotes.domain.catalog import PricingUnit
from quotes.domain.errors import InvalidPricingInput
from quotes.infrastructure.postgres_catalog import (
    CatalogDataError,
    PostgresCatalogRepository,
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
