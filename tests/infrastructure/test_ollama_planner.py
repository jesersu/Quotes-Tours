import io
import json
import urllib.error
import urllib.request

import pytest

from quotes.application.planner import (
    DayWriter,
    PlannedRequest,
    PlannerCatalog,
    PlannerUnavailable,
    QuotePlanner,
)
from quotes.infrastructure.llm.ollama_planner import OllamaQuotePlanner
from quotes.infrastructure.llm.planning_contract import DAY_TEXTS_SCHEMA, request_schema
from tests.application.test_planner import SECRET, day_facts, placed_request
from tests.infrastructure.test_anthropic_planner import MESSAGE, TODAY, VIEW, good_input

HOST = "http://ollama.test:11434"


class FakeTransport:
    def __init__(self, content=None, error=None, response=None):
        self.calls: list[tuple[str, dict, float]] = []
        self.error = error
        if response is None:
            body = content if isinstance(content, str) else json.dumps(content)
            response = {"message": {"role": "assistant", "content": body}}
        self.response = response

    def __call__(self, url, payload, timeout):
        self.calls.append((url, payload, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def plan(transport):
    return OllamaQuotePlanner(HOST, "model-x", transport).plan(MESSAGE, VIEW, TODAY)


def write(transport, days=None):
    facts = day_facts(placed_request(), VIEW) if days is None else days
    return OllamaQuotePlanner(HOST, "model-x", transport).write_days(facts, "en")


def test_it_satisfies_both_ports():
    planner = OllamaQuotePlanner(HOST, "m", FakeTransport())
    assert isinstance(planner, QuotePlanner)
    assert isinstance(planner, DayWriter)


def test_it_posts_the_chat_request_with_the_schema_and_temperature_zero():
    transport = FakeTransport(good_input())
    plan(transport)
    ((url, payload, timeout),) = transport.calls
    assert url == f"{HOST}/api/chat"
    assert timeout == 300.0
    assert payload["model"] == "model-x"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0, "num_predict": 2048}
    assert payload["format"] == request_schema(VIEW)
    item_ids = payload["format"]["properties"]["options"]["items"]["properties"]["items"]
    assert item_ids["items"]["properties"]["item_id"]["enum"] == ["van", "tour", "horse"]
    system, user = payload["messages"]
    assert system["role"] == "system"
    assert "price" in system["content"].lower()
    assert user["role"] == "user"
    assert MESSAGE in user["content"]
    assert "2026-03-01" in user["content"]
    assert '"id": "van"' in user["content"]


def test_nothing_sent_carries_a_price_or_margin():
    transport = FakeTransport(good_input())
    plan(transport)
    payload = json.dumps(transport.calls[0][1])
    assert SECRET not in payload
    assert "555.55" not in payload
    assert "margin_rate" not in payload


def test_a_well_formed_reply_becomes_a_planned_request():
    planned = plan(FakeTransport(good_input()))
    assert isinstance(planned, PlannedRequest)
    assert planned.client == "Smith family"
    assert planned.adults == 2
    assert planned.child_ages == (8,)
    assert planned.options[0].items[0].item_id == "van"
    assert planned.paid_locally == ("ticket",)


@pytest.mark.parametrize(
    "content",
    ["not json at all", "[1, 2]", json.dumps({"client": 3}), json.dumps({"options": "x"}), ""],
)
def test_unusable_content_is_unavailable(content):
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        plan(FakeTransport(content))


@pytest.mark.parametrize("response", [{}, {"message": None}, {"message": {"content": 5}}, []])
def test_a_reply_without_message_content_is_unavailable(response):
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        plan(FakeTransport(response=response))


@pytest.mark.parametrize(
    "error", [urllib.error.URLError("refused"), ConnectionRefusedError("refused")]
)
def test_an_unreachable_server_says_how_to_start_it(error):
    with pytest.raises(PlannerUnavailable) as caught:
        plan(FakeTransport(error=error))
    assert str(caught.value).startswith("planner request failed (")
    assert f"cannot reach Ollama at {HOST}; start it with: ollama serve" in str(caught.value)
    assert caught.value.__cause__ is error
    assert MESSAGE not in str(caught.value)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("slow"),
        urllib.error.URLError(TimeoutError("timed out")),
    ],
)
def test_a_timeout_suggests_a_smaller_model(error):
    with pytest.raises(PlannerUnavailable) as caught:
        plan(FakeTransport(error=error))
    assert str(caught.value) == (
        f"planner request failed ({type(error).__name__}); the model took too long; "
        "try a smaller one with QUOTES_LLM_MODEL"
    )
    assert "cannot reach Ollama" not in str(caught.value)
    assert caught.value.__cause__ is error


def test_an_empty_catalog_is_refused_before_any_call():
    transport = FakeTransport(good_input())
    planner = OllamaQuotePlanner(HOST, "model-x", transport)
    with pytest.raises(PlannerUnavailable, match="^the catalog has no items to plan with$"):
        planner.plan(MESSAGE, PlannerCatalog(), TODAY)
    assert transport.calls == []


@pytest.mark.parametrize("error", [ValueError(MESSAGE), RuntimeError("x")])
def test_other_failures_keep_only_the_type_name(error):
    with pytest.raises(PlannerUnavailable) as caught:
        plan(FakeTransport(error=error))
    assert str(caught.value) == f"planner request failed ({type(error).__name__})"
    assert MESSAGE not in str(caught.value)
    assert caught.value.__cause__ is error


def test_day_texts_use_their_own_schema_and_send_only_facts():
    transport = FakeTransport({"texts": ["One", "Two"]})
    assert write(transport) == ("One", "Two")
    ((url, payload, _),) = transport.calls
    assert url == f"{HOST}/api/chat"
    assert payload["format"] == DAY_TEXTS_SCHEMA
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0, "num_predict": 2048}
    assert "never add" in payload["messages"][0]["content"].lower()
    assert "Private transfer" in payload["messages"][1]["content"]
    assert SECRET not in json.dumps(payload)


def test_write_days_without_days_makes_no_call():
    transport = FakeTransport({"texts": []})
    assert write(transport, days=()) == ()
    assert transport.calls == []


@pytest.mark.parametrize(
    "content", [{"texts": ["only one"]}, {"texts": "nope"}, {"texts": ["a", 2]}, "garbage"]
)
def test_day_texts_with_a_wrong_count_or_shape_are_unavailable(content):
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        write(FakeTransport(content))


def test_day_transport_errors_are_mapped_too():
    with pytest.raises(PlannerUnavailable, match=r"cannot reach Ollama"):
        write(FakeTransport(error=urllib.error.URLError("refused")))
    with pytest.raises(PlannerUnavailable, match=r"^planner request failed \(RuntimeError\)$"):
        write(FakeTransport(error=RuntimeError("x")))


class FakeHttpResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_default_transport_posts_json_and_decodes_the_reply(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["type"] = request.get_header("Content-type")
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        body = {"message": {"content": json.dumps(good_input())}}
        return FakeHttpResponse(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    planned = OllamaQuotePlanner(HOST, "model-x", timeout=7.0).plan(MESSAGE, VIEW, TODAY)
    assert planned.client == "Smith family"
    assert seen["url"] == f"{HOST}/api/chat"
    assert seen["method"] == "POST"
    assert seen["type"] == "application/json"
    assert seen["timeout"] == 7.0
    assert seen["body"]["model"] == "model-x"


def test_the_default_transport_maps_http_and_bad_json_errors(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(PlannerUnavailable, match=r"^planner request failed \(HTTPError\)$"):
        OllamaQuotePlanner(HOST, "m").plan(MESSAGE, VIEW, TODAY)

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout: FakeHttpResponse(b"<html>")
    )
    with pytest.raises(PlannerUnavailable, match=r"^planner request failed \(JSONDecodeError\)$"):
        OllamaQuotePlanner(HOST, "m").plan(MESSAGE, VIEW, TODAY)
