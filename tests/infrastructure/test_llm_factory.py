import sys
from types import SimpleNamespace

import pytest

from quotes.application.planner import PlannerUnavailable
from quotes.infrastructure.llm import planner_from_env
from quotes.infrastructure.llm.anthropic_planner import AnthropicQuotePlanner
from quotes.infrastructure.llm.ollama_planner import OllamaQuotePlanner
from quotes.infrastructure.settings import DEFAULT_OLLAMA_MODEL, InvalidSetting, MissingSetting


def test_ollama_is_the_default_and_needs_no_key_or_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    planner = planner_from_env({})
    assert isinstance(planner, OllamaQuotePlanner)
    assert planner._host == "http://localhost:11434"
    assert planner._model == DEFAULT_OLLAMA_MODEL


def test_ollama_reads_host_and_model():
    planner = planner_from_env({"OLLAMA_HOST": "http://box:9/", "QUOTES_LLM_MODEL": "m-2"})
    assert isinstance(planner, OllamaQuotePlanner)
    assert planner._host == "http://box:9"
    assert planner._model == "m-2"


def test_anthropic_keeps_its_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(PlannerUnavailable, match=r"\[llm\] extra"):
        planner_from_env({"QUOTES_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-test"})


def test_anthropic_builds_a_client_with_the_key_and_model(monkeypatch):
    created = []

    class Anthropic:
        def __init__(self, api_key):
            created.append(api_key)

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=Anthropic))
    env = {"QUOTES_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-test"}
    planner = planner_from_env(env)
    assert isinstance(planner, AnthropicQuotePlanner)
    assert created == ["sk-test"]
    assert planner._model == "claude-sonnet-5-5"
    with pytest.raises(MissingSetting, match="ANTHROPIC_API_KEY"):
        planner_from_env({"QUOTES_LLM_PROVIDER": "anthropic"})


def test_an_unknown_provider_is_refused():
    with pytest.raises(InvalidSetting, match="QUOTES_LLM_PROVIDER"):
        planner_from_env({"QUOTES_LLM_PROVIDER": "other"})
