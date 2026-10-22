"""The Ollama adapter for the quote planner (a local model, nothing leaves the machine).

It talks to ``POST {host}/api/chat`` with ``stream: false`` and a JSON schema in ``format``
(Ollama's structured outputs), so the catalog ids are constrained to the schema's enums. The
rules, schemas and parsing are the shared ``planning_contract``. The request carries the
client's message and the price-free catalog view only.

``transport(url, payload, timeout)`` returns the decoded JSON reply; the default uses
``urllib`` and tests inject a fake. Failures raise ``PlannerUnavailable`` with the exception
type name only (plus a start hint when the server is unreachable), so neither the client's
message nor the model output can end up in an error.
"""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from quotes.application.planner import (
    DayFacts,
    PlannedRequest,
    PlannerCatalog,
    PlannerUnavailable,
)
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

__all__ = ["OllamaQuotePlanner"]

# Caps the reply so a small model cannot ramble for minutes; a full draft fits well inside it.
NUM_PREDICT = 2048

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _urllib_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        exc = exc.reason  # type: ignore[assignment]
    return isinstance(exc, TimeoutError)  # socket.timeout is an alias of it since Python 3.10


class OllamaQuotePlanner:
    """``QuotePlanner`` and ``DayWriter`` backed by a local Ollama server."""

    def __init__(
        self,
        host: str,
        model: str,
        transport: Transport | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._transport = transport if transport is not None else _urllib_transport
        self._timeout = timeout

    def plan(self, message: str, catalog: PlannerCatalog, today: datetime.date) -> PlannedRequest:
        if not catalog.items:
            raise PlannerUnavailable("the catalog has no items to plan with")
        content = self._chat(
            PLAN_SYSTEM_PROMPT, plan_user_content(message, catalog, today), request_schema(catalog)
        )
        return parse_planned_request(content)

    def write_days(self, days: tuple[DayFacts, ...], language: str) -> tuple[str, ...]:
        if not days:
            return ()
        content = self._chat(DAY_SYSTEM_PROMPT, day_user_content(days, language), DAY_TEXTS_SCHEMA)
        return parse_day_texts(content, len(days))

    def _chat(self, system: str, user: str, schema: dict[str, Any]) -> Any:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": NUM_PREDICT},
        }
        try:
            response = self._transport(f"{self._host}/api/chat", payload, self._timeout)
        except Exception as exc:
            message = f"planner request failed ({type(exc).__name__})"
            # HTTPError is a URLError too, but it means the server answered.
            unreachable = isinstance(exc, ConnectionRefusedError) or (
                isinstance(exc, urllib.error.URLError)
                and not isinstance(exc, urllib.error.HTTPError)
            )
            if _is_timeout(exc):
                message += "; the model took too long; try a smaller one with QUOTES_LLM_MODEL"
            elif unreachable:
                message += f"; cannot reach Ollama at {self._host}; start it with: ollama serve"
            raise PlannerUnavailable(message) from exc
        try:
            return json.loads(response["message"]["content"])
        except (KeyError, TypeError, ValueError):
            raise PlannerUnavailable("unexpected planner output") from None
