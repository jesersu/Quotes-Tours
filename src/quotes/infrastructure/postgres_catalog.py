"""Read-only Postgres adapter for the pricing catalog (schema ``quotes``)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from quotes.application.catalog import (
    Catalog,
    CatalogEntry,
    CatalogIssue,
    CatalogLoad,
    LocalPaymentEntry,
    audit_catalog,
)
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
    """A catalog row holds an unsupported value; the message names the row and column."""


def _pen(amount: Decimal) -> Money:
    return Money(amount, Currency.PEN)


def _unknown_value(kind: str, row_id: str, column: str, value: object, allowed: Any) -> Exception:
    return CatalogDataError(
        f"Cannot map {kind} '{row_id}': unknown {column} {value!r} "
        f"(allowed: {', '.join(sorted(allowed))})"
    )


def map_pricing_row(row: dict[str, Any]) -> CatalogEntry:
    """Map one ``pricing_items`` row. A missing column raises KeyError (programming error)."""
    unit = _UNITS.get(row["unit"])
    if unit is None:
        raise _unknown_value("pricing item", row["id"], "unit", row["unit"], _UNITS)
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


def map_local_payment_row(
    row: dict[str, Any], prices_by_item: dict[str, list[dict[str, Any]]]
) -> LocalPaymentEntry:
    """Map one ``local_payment_items`` row with its price rows."""
    categories = {c.value for c in VisitorCategory}
    prices = []
    for p in prices_by_item.get(row["id"], []):
        if p["visitor_category"] not in categories:
            raise _unknown_value(
                "local payment item",
                row["id"],
                "visitor_category",
                p["visitor_category"],
                categories,
            )
        prices.append(LocalPrice(VisitorCategory(p["visitor_category"]), _pen(p["price_pen"])))
    return LocalPaymentEntry(
        id=row["id"],
        info=LocalPaymentInfo(row["name_en"], tuple(prices)),
        name_es=row["name_es"],
        name_en=row["name_en"],
        notes=row["notes"],
    )


class PostgresCatalogRepository:
    """Loads the active catalog. One short-lived read-only connection per ``load()``."""

    def __init__(
        self, dsn: str, *, connect_timeout: int = 10, statement_timeout_ms: int = 15000
    ) -> None:
        for name, value in (
            ("connect_timeout", connect_timeout),
            ("statement_timeout_ms", statement_timeout_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")
        self._dsn = dsn
        self._connect_timeout = connect_timeout
        self._statement_timeout_ms = statement_timeout_ms

    def load(self) -> CatalogLoad:
        with psycopg.connect(
            self._dsn, row_factory=dict_row, connect_timeout=self._connect_timeout
        ) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            conn.execute(
                "select set_config('statement_timeout', %s, true)",
                (str(self._statement_timeout_ms),),
            )
            item_rows = conn.execute(_ITEMS_SQL).fetchall()
            local_rows = conn.execute(_LOCAL_ITEMS_SQL).fetchall()
            price_rows = conn.execute(_LOCAL_PRICES_SQL).fetchall()

        return build_catalog_load(item_rows, local_rows, price_rows)


def build_catalog_load(
    item_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    price_rows: list[dict[str, Any]],
) -> CatalogLoad:
    """Map rows one by one. Unmappable rows become error issues and are excluded.

    Programming errors (for example a missing column) are not data errors and still raise.
    """
    prices_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for price_row in price_rows:
        prices_by_item[price_row["item_id"]].append(price_row)

    issues: list[CatalogIssue] = []
    entries: list[CatalogEntry] = []
    for row in item_rows:
        mapped = _mapped(row, map_pricing_row, issues)
        if mapped is not None:
            entries.append(mapped)

    local: list[LocalPaymentEntry] = []
    for row in local_rows:
        if not prices_by_item.get(row["id"]):
            issues.append(
                CatalogIssue(
                    "error", "no_prices", row["id"], "Active local payment item has no prices"
                )
            )
            continue
        mapped_local = _mapped(row, lambda r: map_local_payment_row(r, prices_by_item), issues)
        if mapped_local is not None:
            local.append(mapped_local)

    catalog = Catalog(entries, local)
    return CatalogLoad(catalog, (*issues, *audit_catalog(catalog)))


def _mapped[T](
    row: dict[str, Any], mapper: Callable[[dict[str, Any]], T], issues: list[CatalogIssue]
) -> T | None:
    try:
        return mapper(row)
    except (CatalogDataError, DomainError) as exc:
        issues.append(CatalogIssue("error", "invalid_row", row["id"], str(exc)))
        return None
