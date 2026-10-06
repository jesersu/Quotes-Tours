"""Integration tests against a real Postgres. Set TEST_DATABASE_URL to run them.

The fixture refuses to run unless the target host is local (see tests/support/db_guard.py).
It drops and recreates the ``quotes`` schema and, only if missing, creates stand-ins for the
Supabase roles, ``public.app_role``, ``public.set_updated_at`` and ``public.has_role``.
"""

import os
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from quotes.application.catalog import CatalogRepository
from quotes.domain.catalog import PricingUnit
from quotes.domain.local_payment import VisitorCategory
from quotes.domain.money import Currency
from quotes.infrastructure.postgres_catalog import PostgresCatalogRepository
from tests.support.db_guard import assert_local_database

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


@pytest.fixture
def dsn():
    url = os.environ["TEST_DATABASE_URL"]
    assert_local_database(url)  # fails loudly: the fixture is destructive
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("drop schema if exists quotes cascade")
        conn.execute((SQL_DIR / "supabase_prelude.sql").read_text())
        conn.execute((SQL_DIR / "quotes_schema.sql").read_text())
    return url


@pytest.fixture
def run(dsn):
    def execute(sql: str, params: tuple = ()) -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql, params)

    return execute


def add_item(run, item_id, unit="group", price="1.10", child=None, active=True, days=None):
    run(
        "insert into quotes.pricing_items"
        " (id, category, name_es, name_en, unit, price_pen, child_price_pen, duration_days,"
        "  active, notes)"
        " values (%s, 'test', %s, %s, %s, %s, %s, %s, %s, 'synthetic')",
        (item_id, f"{item_id} es", f"{item_id} en", unit, price, child, days, active),
    )


def test_satisfies_the_port(dsn):
    repo: CatalogRepository = PostgresCatalogRepository(dsn)
    assert repo.load().catalog.items() == ()


def test_empty_database_gives_empty_catalog(dsn):
    catalog = PostgresCatalogRepository(dsn).load().catalog
    assert catalog.items() == ()
    assert catalog.local_payments() == ()


@pytest.mark.parametrize(
    ("db_unit", "domain_unit"),
    [
        ("group", PricingUnit.PER_GROUP),
        ("day", PricingUnit.PER_DAY),
        ("person", PricingUnit.PER_PERSON),
        ("unit", PricingUnit.PER_UNIT),
    ],
)
def test_maps_each_unit(run, dsn, db_unit, domain_unit):
    add_item(run, "sample-item", unit=db_unit, price="2.50", days=2)
    entry = PostgresCatalogRepository(dsn).load().catalog.get_item("sample-item")
    assert entry.item.unit is domain_unit
    assert entry.item.unit_price.currency is Currency.PEN
    assert entry.item.unit_price.amount == Decimal("2.50")
    assert entry.item.child_unit_price is None
    assert (entry.category, entry.name_es, entry.name_en) == (
        "test",
        "sample-item es",
        "sample-item en",
    )
    assert entry.item.name == "sample-item en"
    assert entry.duration_days == 2
    assert entry.notes == "synthetic"


def test_maps_child_price(run, dsn):
    add_item(run, "sample-person", unit="person", price="3.30", child="1.15")
    item = PostgresCatalogRepository(dsn).load().catalog.get_item("sample-person").item
    assert item.child_unit_price.amount == Decimal("1.15")
    assert item.child_unit_price.currency is Currency.PEN


def test_decimal_precision_is_preserved(run, dsn):
    add_item(run, "sample-precise", price="0.07")
    amount = (
        PostgresCatalogRepository(dsn)
        .load()
        .catalog.get_item("sample-precise")
        .item.unit_price.amount
    )
    assert amount == Decimal("0.07")
    assert isinstance(amount, Decimal)


def test_inactive_rows_are_excluded(run, dsn):
    add_item(run, "active-item")
    add_item(run, "retired-item", active=False)
    run(
        "insert into quotes.local_payment_items (id, name_es, name_en, active)"
        " values ('retired-ticket', 'x', 'x', false)"
    )
    run("insert into quotes.local_payment_prices values ('retired-ticket', 'foreign_adult', 1)")
    catalog = PostgresCatalogRepository(dsn).load().catalog
    assert [e.id for e in catalog.items()] == ["active-item"]
    assert catalog.local_payments() == ()


def test_maps_local_payment_with_three_categories(run, dsn):
    run(
        "insert into quotes.local_payment_items (id, name_es, name_en, notes)"
        " values ('sample-ticket', 'Boleto de muestra', 'Sample ticket', 'synthetic')"
    )
    for category, price in [
        ("latin_american_adult", "1.10"),
        ("foreign_adult", "2.20"),
        ("child_6_15", "0.55"),
    ]:
        run(
            "insert into quotes.local_payment_prices values ('sample-ticket', %s, %s)",
            (category, price),
        )
    entry = PostgresCatalogRepository(dsn).load().catalog.local_payment("sample-ticket")
    assert (entry.name_es, entry.name_en, entry.notes) == (
        "Boleto de muestra",
        "Sample ticket",
        "synthetic",
    )
    assert entry.info.label == "Sample ticket"
    assert entry.info.price_for(VisitorCategory.LATIN_AMERICAN_ADULT).amount == Decimal("1.10")
    assert entry.info.price_for(VisitorCategory.FOREIGN_ADULT).amount == Decimal("2.20")
    assert entry.info.price_for(VisitorCategory.CHILD_6_15).amount == Decimal("0.55")
    assert entry.info.price_for(VisitorCategory.CHILD_6_15).currency is Currency.PEN


def test_active_local_item_without_prices_is_reported_not_fatal(run, dsn):
    add_item(run, "good-item")
    run(
        "insert into quotes.local_payment_items (id, name_es, name_en)"
        " values ('priceless-ticket', 'x', 'x')"
    )
    loaded = PostgresCatalogRepository(dsn).load()
    assert [e.id for e in loaded.catalog.items()] == ["good-item"]
    assert loaded.catalog.local_payments() == ()
    (issue,) = loaded.errors
    assert (issue.code, issue.subject_id) == ("no_prices", "priceless-ticket")


def test_partially_priced_local_item_is_kept_with_a_warning(run, dsn):
    add_item(run, "good-item")
    run(
        "insert into quotes.local_payment_items (id, name_es, name_en)"
        " values ('partial-ticket', 'x', 'x')"
    )
    run("insert into quotes.local_payment_prices values ('partial-ticket', 'foreign_adult', 1)")
    loaded = PostgresCatalogRepository(dsn).load()
    assert [e.id for e in loaded.catalog.local_payments()] == ["partial-ticket"]
    assert loaded.errors == ()
    assert [i.code for i in loaded.warnings] == ["missing_visitor_category"]


def test_empty_database_warns(dsn):
    assert [i.code for i in PostgresCatalogRepository(dsn).load().warnings] == ["empty_catalog"]


def test_slow_statement_is_cancelled_by_the_timeout(dsn, monkeypatch):
    import quotes.infrastructure.postgres_catalog as adapter

    monkeypatch.setattr(adapter, "_ITEMS_SQL", "select pg_sleep(2)")
    with pytest.raises(psycopg.errors.QueryCanceled):
        PostgresCatalogRepository(dsn, statement_timeout_ms=100).load()
