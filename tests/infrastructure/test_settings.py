import pytest

from quotes.infrastructure.settings import MissingSetting, database_url


def test_reads_database_url_from_environment():
    assert database_url({"DATABASE_URL": "postgresql://example"}) == "postgresql://example"


@pytest.mark.parametrize("env", [{}, {"DATABASE_URL": ""}, {"DATABASE_URL": "  "}])
def test_missing_database_url_is_a_clear_error(env):
    with pytest.raises(MissingSetting, match="DATABASE_URL"):
        database_url(env)
