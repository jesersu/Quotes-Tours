import pytest

from quotes.infrastructure.settings import (
    DEFAULT_OLLAMA_MODEL,
    InvalidSetting,
    MissingSetting,
    anthropic_api_key,
    database_url,
    llm_model,
    llm_provider,
    ollama_host,
)


def test_reads_database_url_from_environment():
    assert database_url({"DATABASE_URL": "postgresql://example"}) == "postgresql://example"


@pytest.mark.parametrize("env", [{}, {"DATABASE_URL": ""}, {"DATABASE_URL": "  "}])
def test_missing_database_url_is_a_clear_error(env):
    with pytest.raises(MissingSetting, match="DATABASE_URL"):
        database_url(env)


def test_reads_anthropic_api_key_from_environment():
    assert anthropic_api_key({"ANTHROPIC_API_KEY": " sk-test "}) == "sk-test"


@pytest.mark.parametrize("env", [{}, {"ANTHROPIC_API_KEY": ""}, {"ANTHROPIC_API_KEY": "  "}])
def test_missing_anthropic_api_key_is_a_clear_error(env):
    with pytest.raises(MissingSetting, match="ANTHROPIC_API_KEY"):
        anthropic_api_key(env)


def test_llm_model_defaults_per_provider_and_can_be_overridden():
    anthropic = {"QUOTES_LLM_PROVIDER": "anthropic"}
    assert llm_model({**anthropic}) == "claude-sonnet-5-5"
    assert llm_model({**anthropic, "QUOTES_LLM_MODEL": "  "}) == "claude-sonnet-5-5"
    assert llm_model({}) == DEFAULT_OLLAMA_MODEL == "qwen2.5:14b"
    assert llm_model({"QUOTES_LLM_PROVIDER": "ollama"}) == DEFAULT_OLLAMA_MODEL
    assert llm_model({"QUOTES_LLM_MODEL": " other-model "}) == "other-model"
    assert llm_model({**anthropic, "QUOTES_LLM_MODEL": " other-model "}) == "other-model"


def test_llm_provider_defaults_to_ollama_and_accepts_the_two_names():
    assert llm_provider({}) == "ollama"
    assert llm_provider({"QUOTES_LLM_PROVIDER": "  "}) == "ollama"
    assert llm_provider({"QUOTES_LLM_PROVIDER": " Anthropic "}) == "anthropic"
    assert llm_provider({"QUOTES_LLM_PROVIDER": "ollama"}) == "ollama"


def test_an_unknown_provider_is_a_clear_error_that_does_not_echo_the_value():
    with pytest.raises(InvalidSetting, match="QUOTES_LLM_PROVIDER") as caught:
        llm_provider({"QUOTES_LLM_PROVIDER": "sk-secret-looking"})
    assert "sk-secret-looking" not in str(caught.value)
    assert "ollama" in str(caught.value)
    assert "anthropic" in str(caught.value)


def test_ollama_host_defaults_and_is_normalised():
    assert ollama_host({}) == "http://localhost:11434"
    assert ollama_host({"OLLAMA_HOST": "  "}) == "http://localhost:11434"
    assert ollama_host({"OLLAMA_HOST": " http://box:1234/ "}) == "http://box:1234"
    assert ollama_host({"OLLAMA_HOST": "http://box:1234//"}) == "http://box:1234"
