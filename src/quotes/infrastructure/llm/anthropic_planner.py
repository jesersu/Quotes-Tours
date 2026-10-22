"""The Anthropic adapter for the quote planner.

What leaves the machine: the client's message, today's date and the price-free catalog view
(``PlannerCatalog``). No price, margin or company data is ever part of the request. The model is
forced to answer through one tool, ``propose_quote_request``, whose schema mirrors
``PlannedRequest``; item and local-payment ids are enums built from the catalog.

The ``anthropic`` package is optional (``pip install -e ".[llm]"``) and imported only by
``planner_from_env``. ``AnthropicQuotePlanner`` takes any client with ``.messages.create``.
Failures raise ``PlannerUnavailable`` with the exception type name only, so neither the client's
message, the API key nor the response text can end up in an error.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from quotes.application.planner import (
    DayFacts,
    PlannedDay,
    PlannedExtra,
    PlannedItem,
    PlannedOption,
    PlannedRequest,
    PlannerCatalog,
    PlannerUnavailable,
)
from quotes.infrastructure.settings import anthropic_api_key, llm_model

__all__ = ["DAY_TOOL_NAME", "TOOL_NAME", "AnthropicQuotePlanner", "planner_from_env"]

TOOL_NAME = "propose_quote_request"
DAY_TOOL_NAME = "write_day_texts"

SYSTEM_PROMPT = """\
You turn a travel agency client's message into a draft tour quote request by calling the \
propose_quote_request tool. A person reviews every draft before it is used.

Rules:
- Use only the catalog ids provided in the user message. Never invent an id.
- Never state, estimate or mention prices, costs, discounts or margins, even if the client asks \
or mentions an amount. Pricing is done elsewhere.
- Infer the language of the quote ("es" or "en") from the message, plus the number of adults, \
the ages of children, the number of days and the options the client asks for.
- When the message implies when a service happens, place it on those days with on_days. Give \
each day a short title when the message makes it obvious.
- Use the client's name as the message gives it; if it gives none, leave a short placeholder and \
add a hint.
- Put every doubt, missing fact or assumption in hints, one short sentence each.
- Use paid_locally only for the local payments listed in the catalog.
"""

DAY_SYSTEM_PROMPT = """\
You write the day-by-day text of a travel agency's tour quote by calling the write_day_texts \
tool. A person reviews every text before it is used.

Rules:
- Write one short paragraph per day, in the language given, in the same order as the days.
- Use only the facts given for each day: its title, the service names and their descriptions. \
Join them into fluent prose.
- Never add places, times, prices, costs or promises that are not in the facts. No lists.
"""


def _item_schema(item_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "enum": item_ids},
            "on_days": {"type": "array", "items": {"type": "integer", "minimum": 1}},
            "days": {"type": "integer", "minimum": 1},
            "quantity": {"type": "integer", "minimum": 1},
        },
        "required": ["item_id"],
    }


def tool_schema(catalog: PlannerCatalog) -> dict[str, Any]:
    """The JSON schema of ``PlannedRequest`` with the catalog ids as enums."""
    item = _item_schema(list(catalog.item_ids()))
    items = {"type": "array", "items": item}
    option = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "subtitle": {"type": "string"},
            "days": {"type": "integer", "minimum": 1},
            "items": items,
            "extras": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "items": items},
                    "required": ["label", "items"],
                },
            },
            "itinerary": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer", "minimum": 1},
                        "title": {"type": "string"},
                    },
                    "required": ["day", "title"],
                },
            },
        },
        "required": ["items"],
    }
    return {
        "type": "object",
        "properties": {
            "client": {"type": "string"},
            "title": {"type": "string"},
            "language": {"type": "string", "enum": ["es", "en"]},
            "days": {"type": "integer", "minimum": 1},
            "adults": {"type": "integer", "minimum": 1},
            "child_ages": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 17},
            },
            "options": {"type": "array", "items": option},
            "paid_locally": {
                "type": "array",
                "items": {"type": "string", "enum": list(catalog.local_payment_ids())},
            },
            "hints": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["client", "title", "language", "days", "adults", "options"],
    }


def _user_content(message: str, catalog: PlannerCatalog, today: datetime.date) -> str:
    lines = [f"Today is {today.isoformat()}.", "", "Catalog items (one JSON object per line):"]
    lines += [json.dumps(asdict(item), ensure_ascii=False) for item in catalog.items]
    lines += ["", "Local payments (paid by the client on site):"]
    lines += [json.dumps(asdict(p), ensure_ascii=False) for p in catalog.local_payments]
    lines += ["", "Client message:", message]
    return "\n".join(lines)


class _BadOutput(Exception):
    pass


def _int(value: Any, *, required: bool = True) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _BadOutput
    return value


def _text(value: Any, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _BadOutput
    return value


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _BadOutput
    return value


def _dict(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _BadOutput
    return value


def _item(raw: Any) -> PlannedItem:
    data = _dict(raw)
    return PlannedItem(
        item_id=_text(data.get("item_id")),
        on_days=tuple(_int(d) for d in _list(data.get("on_days"))),
        days=_int(data.get("days"), required=False),
        quantity=_int(data.get("quantity"), required=False),
    )


def _option(raw: Any) -> PlannedOption:
    data = _dict(raw)
    extras = []
    for extra in map(_dict, _list(data.get("extras"))):
        extras.append(
            PlannedExtra(
                _text(extra.get("label")), tuple(_item(i) for i in _list(extra.get("items")))
            )
        )
    days = []
    for day in map(_dict, _list(data.get("itinerary"))):
        days.append(PlannedDay(_int(day.get("day")), _text(day.get("title"))))
    return PlannedOption(
        label=_text(data.get("label"), required=False),
        subtitle=_text(data.get("subtitle"), required=False),
        days=_int(data.get("days"), required=False),
        items=tuple(_item(i) for i in _list(data.get("items"))),
        extras=tuple(extras),
        itinerary=tuple(days),
    )


def _parse(raw: Any) -> PlannedRequest:
    data = _dict(raw)
    return PlannedRequest(
        client=_text(data.get("client")),
        title=_text(data.get("title")),
        language=_text(data.get("language")),
        days=_int(data.get("days")),
        adults=_int(data.get("adults")),
        child_ages=tuple(_int(a) for a in _list(data.get("child_ages"))),
        options=tuple(_option(o) for o in _list(data.get("options"))),
        paid_locally=tuple(_text(p) for p in _list(data.get("paid_locally"))),
        hints=tuple(_text(h) for h in _list(data.get("hints"))),
    )


def _tool_input(response: Any, name: str = TOOL_NAME) -> Any:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == name:
            return block.input
    raise _BadOutput


def _day_content(days: tuple[DayFacts, ...], language: str) -> str:
    lines = [f"Language: {language}", "", "Days (one JSON object per line):"]
    lines += [json.dumps(asdict(facts), ensure_ascii=False) for facts in days]
    return "\n".join(lines)


def _parse_texts(raw: Any, expected: int) -> tuple[str, ...]:
    texts = tuple(_text(t) for t in _list(_dict(raw).get("texts")))
    if len(texts) != expected:
        raise _BadOutput
    return texts


class AnthropicQuotePlanner:
    """``QuotePlanner`` and ``DayWriter`` backed by the Anthropic Messages API (forced tool use)."""

    def __init__(self, client: Any, model: str, max_tokens: int = 4096) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def plan(self, message: str, catalog: PlannerCatalog, today: datetime.date) -> PlannedRequest:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _user_content(message, catalog, today)}],
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": "Propose the draft quote request for the client's message.",
                        "input_schema": tool_schema(catalog),
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except Exception as exc:
            raise PlannerUnavailable(f"planner request failed ({type(exc).__name__})") from exc
        try:
            return _parse(_tool_input(response))
        except _BadOutput:
            raise PlannerUnavailable("unexpected planner output") from None

    def write_days(self, days: tuple[DayFacts, ...], language: str) -> tuple[str, ...]:
        if not days:
            return ()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=DAY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _day_content(days, language)}],
                tools=[
                    {
                        "name": DAY_TOOL_NAME,
                        "description": "Write one paragraph for each day from the facts given.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"texts": {"type": "array", "items": {"type": "string"}}},
                            "required": ["texts"],
                        },
                    }
                ],
                tool_choice={"type": "tool", "name": DAY_TOOL_NAME},
            )
        except Exception as exc:
            raise PlannerUnavailable(f"planner request failed ({type(exc).__name__})") from exc
        try:
            return _parse_texts(_tool_input(response, DAY_TOOL_NAME), len(days))
        except _BadOutput:
            raise PlannerUnavailable("unexpected planner output") from None


def planner_from_env(env: Mapping[str, str] | None = None) -> AnthropicQuotePlanner:
    try:
        import anthropic
    except ImportError as exc:
        raise PlannerUnavailable(
            "the [llm] extra is not installed: pip install -e '.[llm]'"
        ) from exc
    client = anthropic.Anthropic(api_key=anthropic_api_key(env))
    return AnthropicQuotePlanner(client, llm_model(env))
