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
        "postgresql:///quotes_test",
        "dbname=quotes_test",
        "postgresql://localhost,127.0.0.1/quotes_test",
    ],
)
def test_local_targets_are_accepted(dsn):
    assert_local_database(dsn)


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
        assert_local_database(dsn)


def test_rejection_does_not_leak_the_password():
    with pytest.raises(UnsafeTestDatabase) as info:
        assert_local_database("postgresql://u:hunter2-synthetic@db.example.org/x")
    assert "hunter2-synthetic" not in str(info.value)
    assert "db.example.org" in str(info.value)
