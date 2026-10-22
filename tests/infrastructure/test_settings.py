import pytest

from quotes.infrastructure.settings import (
    MissingSetting,
    anthropic_api_key,
    database_url,
    llm_model,
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


def test_llm_model_defaults_and_can_be_overridden():
    assert llm_model({}) == "claude-sonnet-5-5"
    assert llm_model({"QUOTES_LLM_MODEL": "  "}) == "claude-sonnet-5-5"
    assert llm_model({"QUOTES_LLM_MODEL": " other-model "}) == "other-model"
