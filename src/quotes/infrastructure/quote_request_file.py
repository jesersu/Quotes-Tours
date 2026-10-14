"""The quote request file: a YAML file the owner writes to ask for one quote.

Money is read without floats (``0.25`` is kept as the text ``"0.25"``), collections must be YAML
lists, and every problem is collected and reported together, naming the field but never echoing
a margin or any other money value.
"""

from __future__ import annotations

import datetime
import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from quotes.application.quote import QuoteRequest, RequestedExtra, RequestedItem
from quotes.application.quote_rendering import Language
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.money import to_decimal
from quotes.domain.pricing import PricingPolicy
from quotes.domain.travelers import Travelers

__all__ = ["InvalidRequestFile", "QuoteRequestFile", "read_quote_request"]

_TOP_KEYS = (
    "client",
    "title",
    "language",
    "date",
    "signed_by",
    "days",
    "travelers",
    "pricing",
    "items",
    "extras",
    "paid_locally",
)
_TRAVELER_KEYS = ("adults", "child_ages")
_PRICING_KEYS = ("margin_rate", "fx_rate", "usd_rounding_step")
_ITEM_KEYS = ("id", "days", "quantity")
_EXTRA_KEYS = ("label", "items")


class InvalidRequestFile(Exception):
    """The request file cannot be used; ``problems`` lists every reason found."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = tuple(problems)
        super().__init__("Invalid request file:\n" + "\n".join(f"  - {p}" for p in self.problems))


@dataclass(frozen=True)
class QuoteRequestFile:
    request: QuoteRequest
    policy: PricingPolicy
    client_name: str
    title: str
    signed_by: str
    language: Language
    issued_on: datetime.date | None  # None: the caller uses today's date


class _NoFloatLoader(yaml.SafeLoader):
    """SafeLoader that leaves would-be floats as text, so money reaches ``Decimal`` exactly."""


_NoFloatLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:float"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _load(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InvalidRequestFile((f"request file not found: {path}",)) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise InvalidRequestFile((f"cannot read {path} ({type(exc).__name__})",)) from None
    try:
        return yaml.load(text, Loader=_NoFloatLoader)  # noqa: S506 - safe subclass, no objects
    except yaml.YAMLError as exc:
        raise InvalidRequestFile((f"{path} is not valid YAML ({type(exc).__name__})",)) from None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _mapping(
    value: Any, path: str, allowed: tuple[str, ...], problems: list[str]
) -> Mapping[str, Any] | None:
    """A mapping with only known keys; unknown ones are reported with a close-match hint."""
    if not isinstance(value, Mapping):
        problems.append(f"{path} must be a mapping")
        return None
    for key in value:
        if key in allowed:
            continue
        close = difflib.get_close_matches(key, allowed, n=1) if isinstance(key, str) else []
        hint = f"; did you mean '{close[0]}'?" if close else ""
        problems.append(f"{path}: unknown key {str(key)!r}{hint}")
    return value


def _list(value: Any, path: str, problems: list[str]) -> list[Any] | None:
    if not isinstance(value, list):
        problems.append(f"{path} must be a list")
        return None
    return value


def _text(value: Any, path: str, problems: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{path} must be non-empty text")
        return None
    return value


def _int(value: Any, path: str, problems: list[str]) -> int | None:
    if not _is_int(value):
        problems.append(f"{path} must be a whole number")
        return None
    return value


def _required(data: Mapping[str, Any], key: str, path: str, problems: list[str]) -> Any:
    if data.get(key) is None:
        problems.append(f"{path}{key} is required")
        return None
    return data[key]


def _decimal_text(value: Any, path: str, problems: list[str]) -> Any:
    """A number kept exact: text or a whole number. The value itself is never echoed."""
    if isinstance(value, bool) or not isinstance(value, str | int):
        problems.append(f"{path} must be a number")
        return None
    try:
        to_decimal(value)
    except InvalidPricingInput:
        problems.append(f"{path} is not a valid number")
        return None
    return value


def _travelers(data: Any, problems: list[str]) -> Travelers | None:
    mapping = _mapping(data, "travelers", _TRAVELER_KEYS, problems)
    if mapping is None:
        return None
    start = len(problems)
    adults = _required(mapping, "adults", "travelers.", problems)
    if adults is not None:
        adults = _int(adults, "travelers.adults", problems)
    ages: list[int] = []
    raw_ages = mapping.get("child_ages")
    if raw_ages is not None:
        listed = _list(raw_ages, "travelers.child_ages", problems)
        for index, age in enumerate(listed or []):
            if (checked := _int(age, f"travelers.child_ages[{index}]", problems)) is not None:
                ages.append(checked)
    if len(problems) > start:
        return None
    try:
        return Travelers(adults, tuple(ages))
    except InvalidPricingInput as exc:
        problems.append(f"travelers: {exc}")
        return None


def _policy(data: Any, problems: list[str]) -> PricingPolicy | None:
    mapping = _mapping(data, "pricing", _PRICING_KEYS, problems)
    if mapping is None:
        return None
    start = len(problems)
    kwargs: dict[str, Any] = {}
    margin = _required(mapping, "margin_rate", "pricing.", problems)
    if margin is not None:
        kwargs["margin_rate"] = _decimal_text(margin, "pricing.margin_rate", problems)
    for key in ("fx_rate", "usd_rounding_step"):
        if mapping.get(key) is not None:
            kwargs[key] = _decimal_text(mapping[key], f"pricing.{key}", problems)
    if len(problems) > start:
        return None
    try:
        return PricingPolicy(**kwargs)
    except InvalidPricingInput as exc:
        problems.append(f"pricing: {exc}")
        return None


def _items(data: Any, path: str, problems: list[str]) -> tuple[RequestedItem, ...] | None:
    listed = _list(data, path, problems)
    if listed is None:
        return None
    start = len(problems)
    items: list[RequestedItem] = []
    for index, entry in enumerate(listed):
        label = f"{path}[{index}]"
        mapping = _mapping(entry, label, _ITEM_KEYS, problems)
        if mapping is None:
            continue
        before = len(problems)
        item_id = _text(_required(mapping, "id", f"{label}.", problems), f"{label}.id", problems)
        options: dict[str, int | None] = {}
        for key in ("days", "quantity"):
            if mapping.get(key) is not None:
                options[key] = _int(mapping[key], f"{label}.{key}", problems)
        if len(problems) > before:
            continue
        try:
            items.append(RequestedItem(item_id, **options))
        except InvalidPricingInput as exc:
            problems.append(f"{label}: {exc}")
    return tuple(items) if len(problems) == start else None


def _extras(data: Any, problems: list[str]) -> tuple[RequestedExtra, ...]:
    listed = _list(data, "extras", problems)
    extras: list[RequestedExtra] = []
    for index, entry in enumerate(listed or []):
        label = f"extras[{index}]"
        mapping = _mapping(entry, label, _EXTRA_KEYS, problems)
        if mapping is None:
            continue
        name = _text(_required(mapping, "label", f"{label}.", problems), f"{label}.label", problems)
        raw_items = _required(mapping, "items", f"{label}.", problems)
        items = _items(raw_items, f"{label}.items", problems) if raw_items is not None else None
        if name is None or items is None:
            continue
        try:
            extras.append(RequestedExtra(name, items))
        except InvalidPricingInput as exc:
            problems.append(f"{label}: {exc}")
    return tuple(extras)


def _paid_locally(data: Any, problems: list[str]) -> tuple[str, ...]:
    listed = _list(data, "paid_locally", problems)
    ids = [
        _text(value, f"paid_locally[{index}]", problems) for index, value in enumerate(listed or [])
    ]
    return tuple(i for i in ids if i is not None)


def _language(value: Any, problems: list[str]) -> Language:
    if value is None:
        return Language.SPANISH
    if value not in {member.value for member in Language}:
        problems.append("language must be 'es' or 'en'")
        return Language.SPANISH
    return Language(value)


def _issue_date(value: Any, problems: list[str]) -> datetime.date | None:
    if value is None:
        return None
    # A datetime is a date subclass; the quote carries a day, never a time.
    if not isinstance(value, datetime.date) or isinstance(value, datetime.datetime):
        problems.append("date must be a calendar date such as 2026-10-14")
        return None
    return value


def read_quote_request(path: Path) -> QuoteRequestFile:
    """Read and validate a request file, raising ``InvalidRequestFile`` with all problems."""
    data = _load(Path(path))
    problems: list[str] = []
    top = _mapping(data, "request file", _TOP_KEYS, problems)
    if top is None:
        raise InvalidRequestFile(tuple(problems))

    client = _text(_required(top, "client", "", problems), "client", problems)
    title = _text(_required(top, "title", "", problems), "title", problems)
    signed_by = _text(_required(top, "signed_by", "", problems), "signed_by", problems)
    days = _required(top, "days", "", problems)
    days = _int(days, "days", problems) if days is not None else None
    language = _language(top.get("language"), problems)
    issued_on = _issue_date(top.get("date"), problems)

    travelers_data = _required(top, "travelers", "", problems)
    travelers = _travelers(travelers_data, problems) if travelers_data is not None else None
    pricing_data = _required(top, "pricing", "", problems)
    policy = _policy(pricing_data, problems) if pricing_data is not None else None
    items_data = _required(top, "items", "", problems)
    items = _items(items_data, "items", problems) if items_data is not None else None
    extras = _extras(top["extras"], problems) if top.get("extras") is not None else ()
    paid = (
        _paid_locally(top["paid_locally"], problems) if top.get("paid_locally") is not None else ()
    )

    request = None
    if not problems:
        try:
            request = QuoteRequest(days, travelers, items, extras, paid)
        except InvalidPricingInput as exc:
            problems.append(f"request: {exc}")
    if problems or request is None or policy is None:
        raise InvalidRequestFile(tuple(problems))
    return QuoteRequestFile(request, policy, client, title, signed_by, language, issued_on)
