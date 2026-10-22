import datetime
import json
import os
from types import SimpleNamespace

import pytest

from quotes.application.planner import (
    DayFacts,
    DayService,
    DayWriter,
    PlannedDay,
    PlannedExtra,
    PlannedItem,
    PlannedOption,
    PlannedRequest,
    PlannerCatalog,
    PlannerUnavailable,
    QuotePlanner,
    planner_catalog,
)
from quotes.infrastructure.llm.anthropic_planner import (
    DAY_TOOL_NAME,
    TOOL_NAME,
    AnthropicQuotePlanner,
)
from quotes.infrastructure.llm.factory import planner_from_env
from quotes.infrastructure.llm.planning_contract import PLAN_SYSTEM_PROMPT, request_schema
from tests.application.test_planner import SECRET, make_catalog

VIEW = planner_catalog(make_catalog())
TODAY = datetime.date(2026, 3, 1)
MESSAGE = "Hola, somos los Smith, 2 adultos y un nino de 8 anos, 2 dias a Colca"


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.calls: list[dict] = []
        self.response = response
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.messages = FakeMessages(response, error)


def tool_block(data, name=TOOL_NAME):
    return SimpleNamespace(type="tool_use", name=name, input=data)


def reply(*blocks):
    return SimpleNamespace(content=list(blocks))


def good_input():
    return {
        "client": "Smith family",
        "title": "Colca, 2 days",
        "language": "en",
        "days": 2,
        "adults": 2,
        "child_ages": [8],
        "options": [
            {
                "label": "Standard",
                "subtitle": "Private",
                "days": 2,
                "items": [
                    {"item_id": "van", "on_days": [1, 2]},
                    {"item_id": "tour", "days": 1, "quantity": 3},
                ],
                "extras": [{"label": "Ride", "items": [{"item_id": "horse"}]}],
                "itinerary": [{"day": 1, "title": "Arrival"}],
            }
        ],
        "paid_locally": ["ticket"],
        "hints": ["Confirm hotel"],
    }


def plan(client):
    return AnthropicQuotePlanner(client, "model-x").plan(MESSAGE, VIEW, TODAY)


def test_it_is_a_quote_planner():
    assert isinstance(AnthropicQuotePlanner(FakeClient(), "m"), QuotePlanner)


def test_it_forces_the_tool_and_passes_model_and_limits():
    client = FakeClient(reply(tool_block(good_input())))
    AnthropicQuotePlanner(client, "model-x", max_tokens=123).plan(MESSAGE, VIEW, TODAY)
    (call,) = client.messages.calls
    assert call["model"] == "model-x"
    assert call["max_tokens"] == 123
    assert call["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    (tool,) = call["tools"]
    assert tool["name"] == TOOL_NAME
    assert isinstance(call["system"], str)
    assert "price" in call["system"].lower()


def test_an_empty_catalog_is_refused_before_any_call():
    client = FakeClient(reply(tool_block(good_input())))
    with pytest.raises(PlannerUnavailable, match="^the catalog has no items to plan with$"):
        AnthropicQuotePlanner(client, "m").plan(MESSAGE, PlannerCatalog(), TODAY)
    assert client.messages.calls == []


def test_every_top_level_field_is_required_and_nested_requirements_are_unchanged():
    schema = request_schema(VIEW)
    assert sorted(schema["required"]) == sorted(schema["properties"])
    assert set(schema["required"]) == {
        "client",
        "title",
        "language",
        "days",
        "adults",
        "child_ages",
        "options",
        "paid_locally",
        "hints",
    }
    option = schema["properties"]["options"]["items"]
    assert option["required"] == ["items"]
    assert option["properties"]["items"]["items"]["required"] == ["item_id"]
    assert option["properties"]["extras"]["items"]["required"] == ["label", "items"]
    assert option["properties"]["itinerary"]["items"]["required"] == ["day", "title"]


@pytest.mark.parametrize(
    "phrase",
    [
        "one integer per child",
        "[9, 12]",
        "adults counts only adults",
        "items must hold every service the requested trip needs",
        "leave out services for places or tours the client did not mention",
        "a greeting such as hello is not a name",
        "goes in extras, never also in items",
        "only for services whose unit is per_unit",
        "empty string for client",
    ],
)
def test_the_prompt_carries_the_quality_rules(phrase):
    assert phrase in PLAN_SYSTEM_PROMPT.lower()


def test_the_schema_asks_for_at_least_one_option_with_at_least_one_service():
    # A local model returned no options at all until the schema required one.
    schema = request_schema(VIEW)
    options = schema["properties"]["options"]
    assert options["minItems"] == 1
    assert options["items"]["properties"]["items"]["minItems"] == 1


def test_schema_enums_are_the_catalog_ids():
    client = FakeClient(reply(tool_block(good_input())))
    plan(client)
    schema = client.messages.calls[0]["tools"][0]["input_schema"]
    option = schema["properties"]["options"]["items"]
    assert option["properties"]["items"]["items"]["properties"]["item_id"]["enum"] == [
        "van",
        "tour",
        "horse",
    ]
    extra_items = option["properties"]["extras"]["items"]["properties"]["items"]
    assert extra_items["items"]["properties"]["item_id"]["enum"] == ["van", "tour", "horse"]
    assert schema["properties"]["paid_locally"]["items"]["enum"] == ["ticket"]
    assert schema["properties"]["language"]["enum"] == ["es", "en"]
    assert schema["properties"]["adults"]["minimum"] == 1
    assert set(schema["required"]) >= {"client", "title", "language", "days", "adults"}


def test_content_has_message_today_and_catalog_without_prices():
    client = FakeClient(reply(tool_block(good_input())))
    plan(client)
    (call,) = client.messages.calls
    (message,) = call["messages"]
    assert message["role"] == "user"
    content = message["content"]
    assert MESSAGE in content
    assert "2026-03-01" in content
    van = next(line for line in content.splitlines() if '"id": "van"' in line)
    assert json.loads(van) == {
        "id": "van",
        "category": "transport",
        "name_es": "Camioneta",
        "name_en": "Van",
        "unit": "per_group",
        "duration_days": 2,
        "region": "Arequipa",
        "description_es": "Traslado privado",
        "description_en": "Private transfer",
    }
    assert '"id": "ticket"' in content


def test_nothing_sent_carries_a_price_or_margin():
    client = FakeClient(reply(tool_block(good_input())))
    plan(client)
    payload = json.dumps(client.messages.calls[0], default=str)
    assert SECRET not in payload
    assert "555.55" not in payload
    assert "margin_rate" not in payload


def test_a_well_formed_tool_input_becomes_a_planned_request():
    planned = plan(FakeClient(reply(tool_block(good_input()))))
    assert planned == PlannedRequest(
        client="Smith family",
        title="Colca, 2 days",
        language="en",
        days=2,
        adults=2,
        child_ages=(8,),
        options=(
            PlannedOption(
                label="Standard",
                subtitle="Private",
                days=2,
                items=(
                    PlannedItem("van", on_days=(1, 2)),
                    PlannedItem("tour", days=1, quantity=3),
                ),
                extras=(PlannedExtra("Ride", (PlannedItem("horse"),)),),
                itinerary=(PlannedDay(1, "Arrival"),),
            ),
        ),
        paid_locally=("ticket",),
        hints=("Confirm hotel",),
    )


def test_optional_fields_default():
    data = {
        "client": "A",
        "title": "T",
        "language": "es",
        "days": 1,
        "adults": 1,
        "options": [{"items": [{"item_id": "van"}]}],
    }
    planned = plan(FakeClient(reply(tool_block(data))))
    assert planned.child_ages == ()
    assert planned.paid_locally == ()
    assert planned.hints == ()
    assert planned.options == (PlannedOption(None, None, None, (PlannedItem("van"),)),)


def test_unknown_ids_are_kept_as_strings():
    data = good_input()
    data["options"][0]["items"] = [{"item_id": "ghost"}]
    planned = plan(FakeClient(reply(tool_block(data))))
    assert planned.options[0].items == (PlannedItem("ghost"),)


def test_first_matching_tool_block_is_used():
    text = SimpleNamespace(type="text", text="thinking")
    other = tool_block({}, name="other")
    planned = plan(FakeClient(reply(text, other, tool_block(good_input()))))
    assert planned.client == "Smith family"


def break_(key, value):
    data = good_input()
    if value is ...:
        del data[key]
    else:
        data[key] = value
    return data


BAD_INPUTS = [
    break_("client", ...),
    break_("adults", "two"),
    break_("adults", True),
    break_("days", 1.5),
    break_("language", 3),
    break_("child_ages", ["8"]),
    break_("options", "van"),
    break_("options", [{"items": [{"item_id": 5}]}]),
    break_("hints", "one"),
    "not a dict",
]


@pytest.mark.parametrize("data", BAD_INPUTS)
def test_malformed_tool_input_is_unavailable(data):
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        plan(FakeClient(reply(tool_block(data))))


@pytest.mark.parametrize(
    "response",
    [
        reply(),
        reply(SimpleNamespace(type="text", text="no tool")),
        reply(tool_block(good_input(), name="other")),
        SimpleNamespace(),
    ],
)
def test_missing_tool_block_is_unavailable(response):
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        plan(FakeClient(response))


def test_provider_errors_keep_only_the_type_name():
    class ProviderBoom(Exception):
        pass

    error = ProviderBoom(f"key sk-secret rejected: {MESSAGE}")
    with pytest.raises(PlannerUnavailable) as caught:
        plan(FakeClient(error=error))
    assert str(caught.value) == "planner request failed (ProviderBoom)"
    assert caught.value.__cause__ is error
    assert "sk-secret" not in str(caught.value)
    assert MESSAGE not in str(caught.value)


@pytest.mark.llm
# Opt-in only: a loaded .env must never make an ordinary test run call the paid API.
@pytest.mark.skipif(
    os.environ.get("QUOTES_LIVE_LLM") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="set QUOTES_LIVE_LLM=1 and ANTHROPIC_API_KEY to call the real API",
)
def test_live_planner_answers():  # pragma: no cover - never runs in CI
    planned = planner_from_env({**os.environ, "QUOTES_LLM_PROVIDER": "anthropic"}).plan(
        MESSAGE, VIEW, TODAY
    )
    assert planned.adults >= 1


# --- day texts ---

DAYS = (
    DayFacts(None, 1, "Arrival", (DayService("Van", "Private transfer"),)),
    DayFacts(None, 2, None, (DayService("Tour", None),)),
)


def days_block(texts, name=DAY_TOOL_NAME):
    return tool_block({"texts": texts}, name=name)


def write(client, days=DAYS, language="en"):
    return AnthropicQuotePlanner(client, "model-x").write_days(days, language)


def test_it_is_a_day_writer():
    assert isinstance(AnthropicQuotePlanner(FakeClient(), "m"), DayWriter)


def test_write_days_forces_its_own_tool_and_sends_only_facts():
    client = FakeClient(reply(days_block(["One", "Two"])))
    assert write(client) == ("One", "Two")
    (call,) = client.messages.calls
    assert call["tool_choice"] == {"type": "tool", "name": DAY_TOOL_NAME}
    (tool,) = call["tools"]
    assert tool["name"] == "write_day_texts"
    assert tool["input_schema"]["properties"]["texts"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert "never add" in call["system"].lower()
    (message,) = call["messages"]
    content = message["content"]
    assert "Arrival" in content
    assert "Private transfer" in content
    assert "en" in content
    payload = json.dumps(call, default=str)
    assert SECRET not in payload


def test_write_days_without_days_makes_no_call():
    client = FakeClient(reply(days_block([])))
    assert write(client, days=()) == ()
    assert client.messages.calls == []


def test_write_days_count_mismatch_is_unavailable():
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        write(FakeClient(reply(days_block(["only one"]))))


@pytest.mark.parametrize(
    "response",
    [
        reply(),
        reply(days_block(["a", "b"], name="other")),
        reply(tool_block({"texts": "nope"}, name="write_day_texts")),
        reply(tool_block({"texts": ["a", 2]}, name="write_day_texts")),
        SimpleNamespace(),
    ],
)
def test_write_days_bad_output_is_unavailable(response):
    with pytest.raises(PlannerUnavailable, match="^unexpected planner output$"):
        write(FakeClient(response))


def test_write_days_provider_errors_keep_only_the_type_name():
    class ProviderBoom(Exception):
        pass

    with pytest.raises(PlannerUnavailable) as caught:
        write(FakeClient(error=ProviderBoom("key sk-secret")))
    assert str(caught.value) == "planner request failed (ProviderBoom)"
