import pytest

from tests.support.db_guard import UnsafeTestDatabase, assert_local_database


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://postgres:secret@localhost:5432/quotes_test",
        "postgresql://127.0.0.1/quotes_test",
        "postgresql://[::1]:5432/quotes_test",
        "host=localhost dbname=quotes_test",
        "host=127.0.0.1 port=54329 dbname=quotes_test user=postgres",
        "host=/var/run/postgresql dbname=quotes_test",
        "postgresql://localhost,127.0.0.1/quotes_test",
        "host=localhost hostaddr=127.0.0.1 dbname=quotes_test",
    ],
)
def test_local_targets_are_accepted(dsn):
    assert_local_database(dsn, env={})


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@db.example-project.supabase.co:5432/postgres",
        "postgresql://u:p@aws-0-region.pooler.supabase.com:6543/postgres",
        "postgresql://u:p@db.example.org/quotes_test",
        "host=10.0.0.5 dbname=quotes_test",
        "host=db.example-project.supabase.co dbname=postgres",
        "postgresql://localhost,db.example.org/quotes_test",
        "host=localhost hostaddr=10.0.0.5 dbname=quotes_test",
    ],
)
def test_remote_targets_are_rejected(dsn):
    with pytest.raises(UnsafeTestDatabase):
        assert_local_database(dsn, env={})


def test_rejection_does_not_leak_the_password():
    with pytest.raises(UnsafeTestDatabase) as info:
        assert_local_database("postgresql://u:hunter2-synthetic@db.example.org/x", env={})
    assert "hunter2-synthetic" not in str(info.value)
    assert "db.example.org" in str(info.value)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql:///quotes_test",
        "dbname=quotes_test",
        "postgresql://u:p@/quotes_test",
        "",
    ],
)
def test_host_less_dsn_is_rejected(dsn):
    with pytest.raises(UnsafeTestDatabase, match="host"):
        assert_local_database(dsn, env={})


@pytest.mark.parametrize(
    "dsn",
    [
        "host=localhost service=prod dbname=quotes_test",
        "postgresql://localhost/quotes_test?service=prod",
        "service=prod",
    ],
)
def test_service_key_is_rejected(dsn):
    with pytest.raises(UnsafeTestDatabase, match="service"):
        assert_local_database(dsn, env={})


@pytest.mark.parametrize(
    "env",
    [
        {"PGSERVICE": "prod"},
        {"PGSERVICEFILE": "/some/pg_service.conf"},
        {"PGHOSTADDR": "10.0.0.5"},
        {"PGHOSTADDR": "127.0.0.1"},
        {"PGHOST": "db.example.org"},
    ],
)
def test_redirecting_environment_variables_are_rejected(env):
    with pytest.raises(UnsafeTestDatabase, match=next(iter(env))):
        assert_local_database("host=localhost dbname=quotes_test", env=env)


def test_local_pghost_and_empty_variables_are_allowed():
    dsn = "host=localhost dbname=quotes_test"
    assert_local_database(dsn, env={"PGHOST": "localhost"})
    assert_local_database(dsn, env={"PGSERVICE": "", "PGHOSTADDR": "", "PGHOST": ""})


def test_environment_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("PGSERVICE", "prod")
    with pytest.raises(UnsafeTestDatabase, match="PGSERVICE"):
        assert_local_database("host=localhost dbname=quotes_test")


def test_hostaddr_in_the_dsn_must_be_loopback():
    with pytest.raises(UnsafeTestDatabase, match="10.0.0.5"):
        assert_local_database("host=/var/run/postgresql hostaddr=10.0.0.5", env={})


def test_environment_rejection_does_not_leak_the_password():
    with pytest.raises(UnsafeTestDatabase) as info:
        assert_local_database(
            "postgresql://u:hunter2-synthetic@localhost/x", env={"PGSERVICE": "p"}
        )
    assert "hunter2-synthetic" not in str(info.value)
