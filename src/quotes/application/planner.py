"""The planner port: turn a client message into a draft quote request, without prices.

The planner sees a ``PlannerCatalog``, a view of the catalog that has no price, money or margin
field at all, so nothing it receives or returns can carry one. What it returns is a
``PlannedRequest``; ``to_request_data`` turns that into the request-file data, always marked
``needs_review: true``. The authoritative validation is ``parse_quote_request``, which runs once the
owner has reviewed the draft; this module only drops what it can prove is wrong (unknown ids).

Owner-only fields stay empty in the draft: ``signed_by`` and ``pricing.margin_rate`` are written
as ``None`` (the reader accepts that while ``needs_review`` is true and then reports each one as
required), and a review hint names each of them.
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from quotes.application.catalog import Catalog

__all__ = [
    "DayFacts",
    "DayService",
    "DayWriter",
    "PlannedDay",
    "PlannedExtra",
    "PlannedItem",
    "PlannedOption",
    "PlannedRequest",
    "PlannerCatalog",
    "PlannerItem",
    "PlannerLocalPayment",
    "PlannerUnavailable",
    "QuotePlanner",
    "planner_catalog",
    "day_facts",
    "to_request_data",
    "with_day_texts",
]


class PlannerUnavailable(Exception):
    """The planner cannot answer (no credentials, network or provider failure, unusable reply).

    Adapters raise it with a short generic message. The message never includes the client's
    message, the catalog or any credential.
    """


@dataclass(frozen=True)
class PlannerItem:
    id: str
    category: str
    name_es: str
    name_en: str
    unit: str  # the PricingUnit value, such as "per_person"
    duration_days: int | None = None
    region: str | None = None
    description_es: str | None = None
    description_en: str | None = None


@dataclass(frozen=True)
class PlannerLocalPayment:
    id: str
    name_es: str
    name_en: str


@dataclass(frozen=True)
class PlannerCatalog:
    """What the planner may see of the catalog. It holds no price, money or margin."""

    items: tuple[PlannerItem, ...] = ()
    local_payments: tuple[PlannerLocalPayment, ...] = ()

    def item_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.items)

    def local_payment_ids(self) -> tuple[str, ...]:
        return tuple(payment.id for payment in self.local_payments)


def planner_catalog(catalog: Catalog) -> PlannerCatalog:
    """The price-free view of a catalog."""
    return PlannerCatalog(
        items=tuple(
            PlannerItem(
                id=entry.id,
                category=entry.category,
                name_es=entry.name_es,
                name_en=entry.name_en,
                unit=entry.item.unit.value,
                duration_days=entry.duration_days,
                region=entry.region,
                description_es=entry.description_es,
                description_en=entry.description_en,
            )
            for entry in catalog.items()
        ),
        local_payments=tuple(
            PlannerLocalPayment(local.id, local.name_es, local.name_en)
            for local in catalog.local_payments()
        ),
    )


@dataclass(frozen=True)
class PlannedItem:
    item_id: str
    on_days: tuple[int, ...] = ()
    days: int | None = None
    quantity: int | None = None


@dataclass(frozen=True)
class PlannedExtra:
    label: str
    items: tuple[PlannedItem, ...]


@dataclass(frozen=True)
class PlannedDay:
    day: int
    title: str


@dataclass(frozen=True)
class PlannedOption:
    label: str | None
    subtitle: str | None
    days: int | None
    items: tuple[PlannedItem, ...]
    extras: tuple[PlannedExtra, ...] = ()
    itinerary: tuple[PlannedDay, ...] = ()


@dataclass(frozen=True)
class PlannedRequest:
    """The planner's answer. One unlabeled option means a plain request."""

    client: str
    title: str
    language: str  # "es" or "en"
    days: int
    adults: int
    child_ages: tuple[int, ...]
    options: tuple[PlannedOption, ...]
    paid_locally: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()


@runtime_checkable
class QuotePlanner(Protocol):
    def plan(
        self, message: str, catalog: PlannerCatalog, today: datetime.date
    ) -> PlannedRequest: ...


@dataclass(frozen=True)
class DayService:
    """A service placed on a day, with the owner's description in the request language."""

    name: str
    description: str | None = None


@dataclass(frozen=True)
class DayFacts:
    """Everything a writer may use for one day: the day title and the placed services."""

    option_label: str | None
    day: int
    title: str | None
    services: tuple[DayService, ...]


@runtime_checkable
class DayWriter(Protocol):
    """Joins the facts of each day into one paragraph. One text per ``DayFacts``, same order."""

    def write_days(self, days: tuple[DayFacts, ...], language: str) -> tuple[str, ...]: ...


def _item_data(item: PlannedItem) -> dict[str, Any]:
    data: dict[str, Any] = {"id": item.item_id}
    if item.on_days:
        data["on_days"] = list(item.on_days)
    if item.days is not None:
        data["days"] = item.days
    if item.quantity is not None:
        data["quantity"] = item.quantity
    return data


def _known_items(
    items: tuple[PlannedItem, ...], known: set[str], where: str, hints: list[str]
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in items:
        if item.item_id in known:
            kept.append(_item_data(item))
        else:
            hints.append(f"Removed unknown item id '{item.item_id}' from {where}")
    return kept


def _option_data(
    option: PlannedOption, known: set[str], where: str, hints: list[str]
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if option.label is not None:
        data["label"] = option.label
    if option.subtitle is not None:
        data["subtitle"] = option.subtitle
    if option.days is not None:
        data["days"] = option.days
    data["items"] = _known_items(option.items, known, where, hints)
    if not data["items"]:
        hints.append(f"{where} has no items; add services or remove it")
    extras: list[dict[str, Any]] = []
    for extra in option.extras:
        items = _known_items(extra.items, known, f"extra '{extra.label}' of {where}", hints)
        if items:
            extras.append({"label": extra.label, "items": items})
        else:
            hints.append(f"Removed extra '{extra.label}' of {where}: it had no valid items")
    if extras:
        data["extras"] = extras
    if option.itinerary:
        data["itinerary"] = [{"day": d.day, "title": d.title} for d in option.itinerary]
    return data


def to_request_data(planned: PlannedRequest, catalog: PlannerCatalog) -> dict[str, Any]:
    """The request-file data for a planned request: a draft with ``needs_review: true``.

    Unknown item ids and unknown paid-locally ids are dropped, each with a hint naming the id.
    """
    hints: list[str] = list(planned.hints)
    hints.append("Set signed_by")
    hints.append("Set pricing.margin_rate")
    known = set(catalog.item_ids())
    options = planned.options or (PlannedOption(None, None, None, ()),)
    several = len(options) > 1 or any(o.label is not None for o in options)

    data: dict[str, Any] = {
        "needs_review": True,
        "review_hints": hints,
        "client": planned.client,
        "title": planned.title,
        "language": planned.language,
        "signed_by": None,  # owner-only; the reader asks for it once the draft is reviewed
        "days": planned.days,
        "travelers": {"adults": planned.adults, "child_ages": list(planned.child_ages)},
        "pricing": {"margin_rate": None},  # owner-only; the planner never chooses the margin
    }
    if several:
        data["options"] = [
            _option_data(option, known, f"option '{option.label or index}'", hints)
            for index, option in enumerate(options, start=1)
        ]
    else:
        option_data = _option_data(options[0], known, "the request", hints)
        data.update(
            {
                key: option_data[key]
                for key in ("items", "extras", "itinerary")
                if key in option_data
            }
        )
    paid_known = set(catalog.local_payment_ids())
    paid: list[str] = []
    for paid_id in planned.paid_locally:
        if paid_id in paid_known:
            paid.append(paid_id)
        else:
            hints.append(f"Removed unknown paid-locally id '{paid_id}'")
    if paid:
        data["paid_locally"] = paid
    return data


def day_facts(planned: PlannedRequest, catalog: PlannerCatalog) -> tuple[DayFacts, ...]:
    """The facts per option and day: the title and the catalog's own names and descriptions.

    Only days of the request that have a title or a placed service appear. Unknown ids are
    skipped, as ``to_request_data`` drops them. No price is involved.
    """
    spanish = planned.language == "es"
    by_id = {item.id: item for item in catalog.items}
    facts: list[DayFacts] = []
    for option in planned.options:
        titles = {day.day: day.title for day in option.itinerary}
        for number in range(1, (option.days or planned.days) + 1):
            services = []
            for placed in option.items:
                item = by_id.get(placed.item_id)
                if item is None or number not in placed.on_days:
                    continue
                name, description = (
                    (item.name_es, item.description_es)
                    if spanish
                    else (item.name_en, item.description_en)
                )
                services.append(DayService(name, description))
            title = titles.get(number)
            if title is not None or services:
                facts.append(DayFacts(option.label, number, title, tuple(services)))
    return tuple(facts)


def _target_option(data: dict[str, Any], label: str | None) -> dict[str, Any]:
    options = data.get("options")
    if not options:
        return data
    for option in options:
        if option.get("label") == label:
            return option
    raise PlannerUnavailable("unexpected planner output")


def with_day_texts(
    data: dict[str, Any], days: tuple[DayFacts, ...], texts: tuple[str, ...]
) -> dict[str, Any]:
    """A copy of the request data with each text in its option's itinerary entry.

    A blank text is skipped and named in a review hint. A day that gets text without a title is
    written without one: the reader asks for it at review, and a hint says so.
    """
    if len(texts) != len(days):
        raise PlannerUnavailable("unexpected planner output")
    result = copy.deepcopy(data)
    hints: list[str] = result.setdefault("review_hints", [])
    for facts, text in zip(days, texts, strict=True):
        if not text.strip():
            hints.append(f"No text for day {facts.day}")
            continue
        target = _target_option(result, facts.option_label)
        itinerary: list[dict[str, Any]] = target.setdefault("itinerary", [])
        entry = next((e for e in itinerary if e["day"] == facts.day), None)
        if entry is None:
            entry = {"day": facts.day}
            itinerary.append(entry)
            itinerary.sort(key=lambda e: e["day"])
        if "title" not in entry:
            hints.append(f"Set a title for day {facts.day}")
        entry["text"] = text.strip()
    return result
