"""Read-only Postgres adapter for the pricing catalog (schema ``quotes``)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from quotes.application.catalog import Catalog, CatalogEntry, LocalPaymentEntry
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.errors import DomainError
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money

_UNITS = {
    "group": PricingUnit.PER_GROUP,
    "day": PricingUnit.PER_DAY,
    "person": PricingUnit.PER_PERSON,
    "unit": PricingUnit.PER_UNIT,
}

_ITEMS_SQL = """
    select id, category, name_es, name_en, unit::text as unit, price_pen, child_price_pen,
           duration_days, notes
    from quotes.pricing_items
    where active
    order by id
"""

_LOCAL_ITEMS_SQL = """
    select id, name_es, name_en, notes
    from quotes.local_payment_items
    where active
    order by id
"""

_LOCAL_PRICES_SQL = """
    select p.item_id, p.visitor_category::text as visitor_category, p.price_pen
    from quotes.local_payment_prices p
    join quotes.local_payment_items i on i.id = p.item_id
    where i.active
    order by p.item_id, p.visitor_category
"""


class CatalogDataError(Exception):
    """Raised when a catalog row cannot be mapped; the message names the offending row."""


def _pen(amount: Decimal) -> Money:
    return Money(amount, Currency.PEN)


def _map_item(row: dict[str, Any]) -> CatalogEntry:
    unit = _UNITS[row["unit"]]
    child = row["child_price_pen"]
    item = CatalogItem(
        id=row["id"],
        name=row["name_en"],
        unit_price=_pen(row["price_pen"]),
        unit=unit,
        child_unit_price=None if child is None else _pen(child),
    )
    return CatalogEntry(
        item=item,
        category=row["category"],
        name_es=row["name_es"],
        name_en=row["name_en"],
        duration_days=row["duration_days"],
        notes=row["notes"],
    )


def _map_local_payment(
    row: dict[str, Any], prices_by_item: dict[str, list[dict[str, Any]]]
) -> LocalPaymentEntry:
    prices = tuple(
        LocalPrice(VisitorCategory(p["visitor_category"]), _pen(p["price_pen"]))
        for p in prices_by_item.get(row["id"], [])
    )
    return LocalPaymentEntry(
        id=row["id"],
        info=LocalPaymentInfo(row["name_en"], prices),
        name_es=row["name_es"],
        name_en=row["name_en"],
        notes=row["notes"],
    )


class PostgresCatalogRepository:
    """Loads the active catalog. One short-lived read-only connection per ``load()``."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def load(self) -> Catalog:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            item_rows = conn.execute(_ITEMS_SQL).fetchall()
            local_rows = conn.execute(_LOCAL_ITEMS_SQL).fetchall()
            price_rows = conn.execute(_LOCAL_PRICES_SQL).fetchall()

        prices_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for price_row in price_rows:
            prices_by_item[price_row["item_id"]].append(price_row)

        entries = [_mapped("pricing item", r, _map_item) for r in item_rows]
        local = [
            _mapped("local payment item", r, lambda row: _map_local_payment(row, prices_by_item))
            for r in local_rows
        ]
        return Catalog(entries, local)


def _mapped[T](kind: str, row: dict[str, Any], mapper: Callable[[dict[str, Any]], T]) -> T:
    try:
        return mapper(row)
    except (DomainError, KeyError, ValueError) as exc:
        raise CatalogDataError(f"Cannot map {kind} '{row['id']}': {exc}") from exc
