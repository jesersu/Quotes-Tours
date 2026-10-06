"""The reviewable catalog draft: a YAML file the owner edits before generating SQL."""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import yaml

from quotes.application.catalog_proposal import VISITOR_CATEGORIES
from quotes.infrastructure.output_file import OutputExists, write_new_file
from quotes.infrastructure.postgres_catalog import build_catalog_load

__all__ = [
    "OutputExists",
    "ValidatedDraft",
    "dump_draft",
    "load_draft",
    "validate_draft",
    "write_new_file",
]

PRICING_UNITS = ("group", "day", "person", "unit")
MAX_PRICE = Decimal("99999999.99")  # numeric(10,2)
MAX_DURATION_DAYS = 365
_SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # use fullmatch: "$" would accept a trailing "\n"
_ALLOWED_CONTROLS = "\t\n\r"
_TOP_KEYS = ("pricing_items", "local_payments")
_TOOL_KEYS = ("source_name", "needs_review", "review_hint")  # written by `quotes catalog draft`
_PRICING_KEYS = (
    "id",
    "name_es",
    "name_en",
    "category",
    "unit",
    "duration_days",
    "price_pen",
    "child_price_pen",
    "active",
    "notes",
    *_TOOL_KEYS,
)
_LOCAL_KEYS = ("id", "name_es", "name_en", "prices", "active", "notes", *_TOOL_KEYS)

HEADER = """\
# Catalog draft generated from the price spreadsheet. PRIVATE: do not commit it.
#
# How to review (then run `quotes catalog sql <this file>`):
#   - Every entry starts with needs_review: true. Check its fields (unit, English name,
#     category, child_price_pen, ...), follow review_hint, then set needs_review: false.
#   - Local payments (paid by the tourist on site, information only) need all three prices.
#   - Keep price_pen as a quoted string with two decimals, for example "12.34".
#   - source_name is the original spreadsheet text, kept for reference only.
"""


def is_safe_text(value: str) -> bool:
    """Text the SQL export can carry: no NUL or other control characters, no lone surrogates.

    Tab, newline and carriage return are allowed (notes may span lines). This is the single
    rule shared by draft validation and the SQL renderer.
    """
    return all(c in _ALLOWED_CONTROLS or unicodedata.category(c) not in ("Cc", "Cs") for c in value)


def dump_draft(draft: Mapping[str, Any]) -> str:
    body = yaml.safe_dump(
        dict(draft), sort_keys=False, allow_unicode=True, default_flow_style=False, width=100
    )
    return f"{HEADER}\n{body}"


def load_draft(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Draft is not valid YAML: {type(exc).__name__}") from exc


@dataclass(frozen=True)
class ValidatedDraft:
    """Draft entries in the dict-row shape the Postgres adapter maps, plus the verdict."""

    item_rows: tuple[dict[str, Any], ...]
    local_rows: tuple[dict[str, Any], ...]
    price_rows: tuple[dict[str, Any], ...]
    problems: tuple[str, ...]
    warnings: tuple[str, ...]


def _money(value: Any) -> Decimal | None:
    """An exact amount with at most two decimals within numeric(10,2), else None."""
    if value is None or isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or amount > MAX_PRICE:
        return None
    if amount != amount.quantize(Decimal("0.01")):
        return None
    return amount.quantize(Decimal("0.01"))


def _text(entry: Mapping[str, Any], key: str, label: str, problems: list[str]) -> str | None:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{label}: {key} must be non-empty text")
        return None
    if not is_safe_text(value):
        problems.append(f"{label}: {key} contains a NUL or other control character")
        return None
    return value


def _check_common(
    entry: Any, label: str, seen: set[str], problems: list[str]
) -> tuple[str | None, bool]:
    """Checks shared by both lists: id, review flag, active, notes. Returns (id, usable)."""
    start = len(problems)
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not _SLUG.fullmatch(entry_id):
        problems.append(f"{label}: id must be a lowercase slug (a-z, 0-9, hyphens)")
        entry_id = None
    elif entry_id in seen:
        problems.append(f"{label}: duplicate id '{entry_id}'")
    else:
        seen.add(entry_id)
    review = entry.get("needs_review")
    if review is True:
        problems.append(f"{label}: needs_review is still true; review it and set it to false")
    elif review is not False:
        problems.append(f"{label}: needs_review must be false once reviewed (found {review!r})")
    if not isinstance(entry.get("active", True), bool):
        problems.append(f"{label}: active must be true or false")
    notes = entry.get("notes")
    if notes is not None and not isinstance(notes, str):
        problems.append(f"{label}: notes must be text or null")
    elif isinstance(notes, str) and not is_safe_text(notes):
        problems.append(f"{label}: notes contains a NUL or other control character")
    return entry_id, len(problems) == start


def _pricing_row(entry: Mapping[str, Any], label: str, problems: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {"id": entry.get("id")}
    for key in ("category", "name_es", "name_en"):
        row[key] = _text(entry, key, label, problems)
    unit = entry.get("unit")
    if unit not in PRICING_UNITS or not isinstance(unit, str):
        problems.append(f"{label}: unit must be one of {', '.join(PRICING_UNITS)} (found {unit!r})")
    row["unit"] = unit
    row["price_pen"] = _money(entry.get("price_pen"))
    if row["price_pen"] is None:
        problems.append(f"{label}: price_pen must be a non-negative amount with at most 2 decimals")
    child = entry.get("child_price_pen")
    row["child_price_pen"] = None if child is None else _money(child)
    if child is not None and row["child_price_pen"] is None:
        problems.append(f"{label}: child_price_pen must be null or a valid amount")
    days = entry.get("duration_days")
    if days is not None and (
        isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_DURATION_DAYS
    ):
        problems.append(
            f"{label}: duration_days must be null or a whole number from 1 to {MAX_DURATION_DAYS}"
        )
    row["duration_days"] = days
    row["notes"] = entry.get("notes")
    row["active"] = entry.get("active", True)
    return row


def _local_rows(
    entry: Mapping[str, Any], label: str, problems: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row: dict[str, Any] = {"id": entry.get("id"), "notes": entry.get("notes")}
    row["active"] = entry.get("active", True)
    for key in ("name_es", "name_en"):
        row[key] = _text(entry, key, label, problems)
    prices = entry.get("prices")
    price_rows: list[dict[str, Any]] = []
    if not isinstance(prices, Mapping):
        problems.append(f"{label}: prices must be a mapping of visitor category to amount")
        return row, price_rows
    for key in prices:
        if key not in VISITOR_CATEGORIES:
            problems.append(f"{label}: unknown visitor category '{key}'")
    for category in VISITOR_CATEGORIES:
        value = prices.get(category)
        if value is None:
            problems.append(f"{label}: price for {category} is null; fill it in")
            continue
        amount = _money(value)
        if amount is None:
            problems.append(f"{label}: price for {category} must be a valid amount")
            continue
        price_rows.append(
            {"item_id": entry.get("id"), "visitor_category": category, "price_pen": amount}
        )
    return row, price_rows


def _shown(entry_id: Any) -> str:
    """The id for messages: a valid slug as is, anything else escaped (no raw control chars)."""
    return entry_id if isinstance(entry_id, str) and _SLUG.fullmatch(entry_id) else repr(entry_id)


def _unknown_keys(
    data: Mapping[Any, Any], allowed: tuple[str, ...], label: str, problems: list[str]
) -> None:
    for key in data:
        if key in allowed:
            continue
        text = str(key)
        close = difflib.get_close_matches(text, allowed, n=1) if isinstance(key, str) else []
        hint = f"; did you mean '{close[0]}'?" if close else ""
        problems.append(f"{label}: unknown key {text!r}{hint}")


def _entries(data: Mapping[str, Any], key: str, problems: list[str]) -> list[Any]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{key} must be a list")
        return []
    return value


def validate_draft(data: Any) -> ValidatedDraft:
    """Validate a loaded draft. Rules shared with the database path are reused, not copied:
    structurally valid entries go through ``build_catalog_load`` (the Postgres adapter's mapping)
    and any of its error issues blocks the export."""
    problems: list[str] = []
    if not isinstance(data, Mapping):
        return ValidatedDraft(
            (), (), (), ("draft must be a mapping with pricing_items and local_payments lists",), ()
        )
    _unknown_keys(data, _TOP_KEYS, "draft", problems)
    pricing = _entries(data, "pricing_items", problems)
    locals_ = _entries(data, "local_payments", problems)
    if not pricing and not locals_ and not problems:
        problems.append("draft has no entries to import")

    item_rows: list[dict[str, Any]] = []
    local_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    seen_locals: set[str] = set()
    for index, entry in enumerate(pricing):
        label = f"pricing_items[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{label}: must be a mapping")
            continue
        label = f"{label} ({_shown(entry.get('id'))})"
        _unknown_keys(entry, _PRICING_KEYS, label, problems)
        _check_common(entry, label, seen_items, problems)
        item_rows.append(_pricing_row(entry, label, problems))
    for index, entry in enumerate(locals_):
        label = f"local_payments[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{label}: must be a mapping")
            continue
        label = f"{label} ({_shown(entry.get('id'))})"
        _unknown_keys(entry, _LOCAL_KEYS, label, problems)
        _check_common(entry, label, seen_locals, problems)
        row, prices = _local_rows(entry, label, problems)
        local_rows.append(row)
        price_rows.extend(prices)

    warnings: list[str] = []
    if not problems:
        loaded = build_catalog_load(item_rows, local_rows, price_rows)
        problems.extend(f"{i.subject_id}: {i.message}" for i in loaded.errors)
        warnings.extend(f"{i.subject_id}: {i.message}" for i in loaded.warnings)
    return ValidatedDraft(
        tuple(item_rows), tuple(local_rows), tuple(price_rows), tuple(problems), tuple(warnings)
    )
