"""Executes the generated SQL against a throwaway local Postgres (TEST_DATABASE_URL)."""

import copy
import os
from decimal import Decimal

import psycopg
import pytest

from quotes.infrastructure.catalog_draft import dump_draft, load_draft, validate_draft
from quotes.infrastructure.catalog_sql import render_sql
from quotes.infrastructure.postgres_catalog import PostgresCatalogRepository
from tests.infrastructure.test_postgres_catalog import dsn  # noqa: F401  (guarded fixture)
from tests.support.draft_fixture import NASTY, mutate, valid_draft

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"),
]


def sql_for(draft):
    result = validate_draft(load_draft(dump_draft(draft)))
    assert not result.problems, result.problems
    return render_sql(result)


def apply(url, sql):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)


def counts(url):
    with psycopg.connect(url) as conn:
        return [
            conn.execute(f"select count(*) from quotes.{t}").fetchone()[0]
            for t in ("pricing_items", "local_payment_items", "local_payment_prices")
        ]


def test_generated_sql_loads_back_idempotently_and_upserts(dsn):  # noqa: F811
    draft = valid_draft()
    sql = sql_for(draft)
    apply(dsn, sql)

    load = PostgresCatalogRepository(dsn).load()
    assert load.ok, load.issues
    alpha = load.catalog.get_item("alpha-tour")
    assert alpha.name_es == NASTY
    assert alpha.item.unit_price.amount == Decimal("7391.46")
    assert alpha.item.child_unit_price.amount == Decimal("2468.13")
    assert load.catalog.get_item("beta-transport-2-days").duration_days == 2
    ticket = load.catalog.local_payment("gamma-ticket")
    assert {p.category.value: p.price.amount for p in ticket.info.prices} == {
        "latin_american_adult": Decimal("3017.52"),
        "foreign_adult": Decimal("6642.08"),
        "child_6_15": Decimal("1259.37"),
    }
    assert counts(dsn) == [2, 1, 3]

    apply(dsn, sql)  # idempotent: same script again changes nothing
    assert counts(dsn) == [2, 1, 3]

    changed = copy.deepcopy(draft)
    changed["pricing_items"][0]["price_pen"] = "99.99"
    changed["pricing_items"][0]["name_en"] = "Alpha tour v2"
    changed["local_payments"][0]["prices"]["foreign_adult"] = "60.00"
    apply(dsn, sql_for(changed))
    after = PostgresCatalogRepository(dsn).load()
    assert after.ok
    assert after.catalog.get_item("alpha-tour").item.unit_price.amount == Decimal("99.99")
    assert after.catalog.get_item("alpha-tour").name_en == "Alpha tour v2"
    prices = {
        p.category.value: p.price.amount
        for p in after.catalog.local_payment("gamma-ticket").info.prices
    }
    assert prices["foreign_adult"] == Decimal("60.00")
    assert counts(dsn) == [2, 1, 3]


def test_descriptions_load_back_and_a_null_in_the_draft_keeps_the_stored_value(dsn):  # noqa: F811
    draft = mutate(region="Puno", description_es="Texto es", description_en="Text en")
    apply(dsn, sql_for(draft))
    alpha = PostgresCatalogRepository(dsn).load().catalog.get_item("alpha-tour")
    assert (alpha.region, alpha.description_es, alpha.description_en) == (
        "Puno",
        "Texto es",
        "Text en",
    )

    apply(dsn, sql_for(valid_draft()))  # descriptions null in the draft: stored ones stay
    kept = PostgresCatalogRepository(dsn).load().catalog.get_item("alpha-tour")
    assert (kept.region, kept.description_es, kept.description_en) == (
        "Puno",
        "Texto es",
        "Text en",
    )

    apply(dsn, sql_for(mutate(description_en="Text v2")))  # a value replaces the stored one
    changed = PostgresCatalogRepository(dsn).load().catalog.get_item("alpha-tour")
    assert (changed.region, changed.description_en) == ("Puno", "Text v2")
