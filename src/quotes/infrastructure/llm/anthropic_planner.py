"""The Anthropic adapter for the quote planner.

The model is forced to answer through one tool, ``propose_quote_request`` (or ``write_day_texts``),
whose input schema is the shared one from ``planning_contract``; the rules, user content and
parsing are shared too, and so is the privacy rule: no price, margin or company data is sent.

The ``anthropic`` package is optional (``pip install -e ".[llm]"``); ``planner_from_env`` in the
factory imports it. ``AnthropicQuotePlanner`` takes any client with ``.messages.create``.
Failures raise ``PlannerUnavailable`` with the exception type name only, so neither the client's
message, the API key nor the response text can end up in an error.
"""

from __future__ import annotations

import datetime
from typing import Any

from quotes.application.planner import DayFacts, PlannedRequest, PlannerCatalog, PlannerUnavailable
from quotes.infrastructure.llm.planning_contract import (
    DAY_SYSTEM_PROMPT,
    DAY_TEXTS_SCHEMA,
    PLAN_SYSTEM_PROMPT,
    day_user_content,
    parse_day_texts,
    parse_planned_request,
    plan_user_content,
    request_schema,
)

__all__ = ["DAY_TOOL_NAME", "TOOL_NAME", "AnthropicQuotePlanner"]

TOOL_NAME = "propose_quote_request"
DAY_TOOL_NAME = "write_day_texts"


def _tool_input(response: Any, name: str) -> Any:
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == name:
            return block.input
    raise PlannerUnavailable("unexpected planner output")


class AnthropicQuotePlanner:
    """``QuotePlanner`` and ``DayWriter`` backed by the Anthropic Messages API (forced tool use)."""

    def __init__(self, client: Any, model: str, max_tokens: int = 4096) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def plan(self, message: str, catalog: PlannerCatalog, today: datetime.date) -> PlannedRequest:
        if not catalog.items:
            raise PlannerUnavailable("the catalog has no items to plan with")
        response = self._call(
            PLAN_SYSTEM_PROMPT,
            plan_user_content(message, catalog, today),
            TOOL_NAME,
            "Propose the draft quote request for the client's message.",
            request_schema(catalog),
        )
        return parse_planned_request(_tool_input(response, TOOL_NAME))

    def write_days(self, days: tuple[DayFacts, ...], language: str) -> tuple[str, ...]:
        if not days:
            return ()
        response = self._call(
            DAY_SYSTEM_PROMPT,
            day_user_content(days, language),
            DAY_TOOL_NAME,
            "Write one paragraph for each day from the facts given.",
            DAY_TEXTS_SCHEMA,
        )
        return parse_day_texts(_tool_input(response, DAY_TOOL_NAME), len(days))

    def _call(self, system: str, user: str, tool: str, description: str, schema: dict) -> Any:
        try:
            return self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{"name": tool, "description": description, "input_schema": schema}],
                tool_choice={"type": "tool", "name": tool},
            )
        except Exception as exc:
            raise PlannerUnavailable(f"planner request failed ({type(exc).__name__})") from exc
