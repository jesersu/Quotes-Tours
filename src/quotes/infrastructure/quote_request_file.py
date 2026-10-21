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

from quotes.application.quote import (
    ItineraryDay,
    QuoteOption,
    QuoteRequest,
    RequestedExtra,
    RequestedItem,
)
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
    "options",
    "itinerary",
    "paid_locally",
)
_TRAVELER_KEYS = ("adults", "child_ages")
_PRICING_KEYS = ("margin_rate", "fx_rate", "usd_rounding_step")
_ITEM_KEYS = ("id", "days", "quantity", "on_days")
_ITINERARY_KEYS = ("day", "title")
_EXTRA_KEYS = ("label", "items")
_OPTION_KEYS = ("label", "subtitle", "days", "items", "extras", "itinerary")


class InvalidRequestFile(Exception):
    """The request file cannot be used; ``problems`` lists every reason found."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = tuple(problems)
        super().__init__("Invalid request file:\n" + "\n".join(f"  - {p}" for p in self.problems))


@dataclass(frozen=True)
class QuoteRequestFile:
    options: tuple[QuoteOption, ...]  # one unlabeled option for a plain request
    policy: PricingPolicy
    client_name: str
    title: str
    signed_by: str
    language: Language
    issued_on: datetime.date | None  # None: the caller uses today's date

    @property
    def request(self) -> QuoteRequest:
        """The request of a plain, single-option file; several options have no one request."""
        if len(self.options) != 1:
            raise ValueError("This file has several options; read them from `options`")
        return self.options[0].request


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


def _day_number(value: Any, path: str, days: int | None, problems: list[str]) -> int | None:
    """A day of the trip: a whole number from 1 to the days of the quote, when those are known."""
    if (day := _int(value, path, problems)) is None:
        return None
    if day < 1:
        problems.append(f"{path} must be at least 1")
        return None
    if days is not None and day > days:
        problems.append(f"{path} must not exceed the {days} days of the quote")
        return None
    return day


def _on_days(value: Any, path: str, days: int | None, problems: list[str]) -> tuple[int, ...]:
    listed = _list(value, path, problems)
    found: list[int] = []
    for index, raw in enumerate(listed or []):
        day = _day_number(raw, f"{path}[{index}]", days, problems)
        if day is None:
            continue
        if day in found:
            problems.append(f"{path} must not repeat day {day}")
        found.append(day)
    return tuple(found)


def _itinerary(
    data: Any, path: str, days: int | None, problems: list[str]
) -> tuple[ItineraryDay, ...]:
    listed = _list(data, path, problems)
    entries: list[ItineraryDay] = []
    seen: dict[int, int] = {}
    for index, entry in enumerate(listed or []):
        label = f"{path}[{index}]"
        mapping = _mapping(entry, label, _ITINERARY_KEYS, problems)
        if mapping is None:
            continue
        raw_day = _required(mapping, "day", f"{label}.", problems)
        day = _day_number(raw_day, f"{label}.day", days, problems) if raw_day is not None else None
        raw_title = _required(mapping, "title", f"{label}.", problems)
        title = _text(raw_title, f"{label}.title", problems) if raw_title is not None else None
        if day is not None and day in seen:
            problems.append(f"{label}.day repeats {path}[{seen[day]}].day")
            continue
        if day is not None:
            seen[day] = index
        if day is not None and title is not None:
            entries.append(ItineraryDay(day, title))
    return tuple(entries)


def _items(
    data: Any,
    path: str,
    problems: list[str],
    days: int | None = None,
    placeable: bool = True,
) -> tuple[RequestedItem, ...] | None:
    """Requested items. ``days`` bounds ``on_days``; extras are not placed in the itinerary."""
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
        options: dict[str, Any] = {}
        for key in ("days", "quantity"):
            if mapping.get(key) is not None:
                options[key] = _int(mapping[key], f"{label}.{key}", problems)
        if mapping.get("on_days") is not None:
            if placeable:
                options["on_days"] = _on_days(
                    mapping["on_days"], f"{label}.on_days", days, problems
                )
            else:
                problems.append(f"{label}.on_days is not allowed on optional extras")
        if len(problems) > before:
            continue
        try:
            items.append(RequestedItem(item_id, **options))
        except InvalidPricingInput as exc:
            problems.append(f"{label}: {exc}")
    return tuple(items) if len(problems) == start else None


def _extras(data: Any, problems: list[str], path: str = "extras") -> tuple[RequestedExtra, ...]:
    listed = _list(data, path, problems)
    extras: list[RequestedExtra] = []
    for index, entry in enumerate(listed or []):
        label = f"{path}[{index}]"
        mapping = _mapping(entry, label, _EXTRA_KEYS, problems)
        if mapping is None:
            continue
        name = _text(_required(mapping, "label", f"{label}.", problems), f"{label}.label", problems)
        raw_items = _required(mapping, "items", f"{label}.", problems)
        items = (
            _items(raw_items, f"{label}.items", problems, placeable=False)
            if raw_items is not None
            else None
        )
        if name is None or items is None:
            continue
        try:
            extras.append(RequestedExtra(name, items))
        except InvalidPricingInput as exc:
            problems.append(f"{label}: {exc}")
    return tuple(extras)


def _known(days: Any) -> int | None:
    """The days of a quote when they are a usable number, else None (already reported)."""
    return days if _is_int(days) and days >= 1 else None


def _option(
    entry: Any,
    index: int,
    default_days: Any,
    travelers: Travelers | None,
    paid: tuple[str, ...],
    problems: list[str],
) -> QuoteOption | None:
    path = f"options[{index}]"
    mapping = _mapping(entry, path, _OPTION_KEYS, problems)
    if mapping is None:
        return None
    start = len(problems)
    label = _text(_required(mapping, "label", f"{path}.", problems), f"{path}.label", problems)
    subtitle = mapping.get("subtitle")
    if subtitle is not None:
        subtitle = _text(subtitle, f"{path}.subtitle", problems)
    days = default_days
    if mapping.get("days") is not None:
        days = _int(mapping["days"], f"{path}.days", problems)
    raw_items = _required(mapping, "items", f"{path}.", problems)
    items = (
        _items(raw_items, f"{path}.items", problems, _known(days))
        if raw_items is not None
        else None
    )
    itinerary: tuple[ItineraryDay, ...] = ()
    if mapping.get("itinerary") is not None:
        itinerary = _itinerary(mapping["itinerary"], f"{path}.itinerary", _known(days), problems)
    extras = ()
    if mapping.get("extras") is not None:
        extras = _extras(mapping["extras"], problems, f"{path}.extras")
    if len(problems) > start or travelers is None or days is None:
        return None
    try:
        request = QuoteRequest(days, travelers, items, extras, paid)
        return QuoteOption(label, subtitle, request, itinerary)
    except InvalidPricingInput as exc:
        problems.append(f"{path}: {exc}")
        return None


def _options(
    data: Any,
    default_days: Any,
    travelers: Travelers | None,
    paid: tuple[str, ...],
    problems: list[str],
) -> tuple[QuoteOption, ...]:
    listed = _list(data, "options", problems)
    if listed is not None and not listed:
        problems.append("options needs at least one option")
    options = [
        _option(entry, index, default_days, travelers, paid, problems)
        for index, entry in enumerate(listed or [])
    ]
    seen: dict[str, int] = {}
    for index, option in enumerate(options):
        if option is None:
            continue
        if option.label in seen:
            problems.append(
                f"options[{index}].label must be unique; "
                f"it repeats options[{seen[option.label]}].label"
            )
        seen.setdefault(option.label, index)
    return tuple(option for option in options if option is not None)


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
    has_options = top.get("options") is not None
    flat_keys = [key for key in ("items", "extras", "itinerary") if top.get(key) is not None]
    if has_options and flat_keys:
        problems.append(
            f"options cannot be combined with top-level {' or '.join(flat_keys)}; "
            "put them inside each option"
        )
    elif not has_options and top.get("items") is None:
        problems.append("items is required")
        problems.append("request: give either top-level items or options")
    language = _language(top.get("language"), problems)
    issued_on = _issue_date(top.get("date"), problems)

    days = top.get("days")
    days = _int(days, "days", problems) if days is not None else None
    option_entries = top["options"] if isinstance(top.get("options"), list) else []
    # Top-level days is optional only when every option names its own.
    if (
        days is None
        and top.get("days") is None
        and (
            not has_options
            or not option_entries
            or not all(isinstance(e, Mapping) and e.get("days") is not None for e in option_entries)
        )
    ):
        problems.append("days is required")

    travelers_data = _required(top, "travelers", "", problems)
    travelers = _travelers(travelers_data, problems) if travelers_data is not None else None
    pricing_data = _required(top, "pricing", "", problems)
    policy = _policy(pricing_data, problems) if pricing_data is not None else None
    paid = (
        _paid_locally(top["paid_locally"], problems) if top.get("paid_locally") is not None else ()
    )

    options: tuple[QuoteOption, ...] = ()
    if has_options:
        options = _options(top["options"], days, travelers, paid, problems)
    elif top.get("items") is not None:
        items = _items(top["items"], "items", problems, _known(days))
        extras = _extras(top["extras"], problems) if top.get("extras") is not None else ()
        itinerary: tuple[ItineraryDay, ...] = ()
        if top.get("itinerary") is not None:
            itinerary = _itinerary(top["itinerary"], "itinerary", _known(days), problems)
        if not problems:
            try:
                request = QuoteRequest(days, travelers, items, extras, paid)
                options = (QuoteOption(None, None, request, itinerary),)
            except InvalidPricingInput as exc:
                problems.append(f"request: {exc}")

    if problems or not options or policy is None:
        raise InvalidRequestFile(tuple(problems))
    return QuoteRequestFile(options, policy, client, title, signed_by, language, issued_on)
