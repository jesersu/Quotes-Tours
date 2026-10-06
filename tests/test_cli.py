import io
from decimal import Decimal

import pytest

from quotes.application.catalog import (
    Catalog,
    CatalogEntry,
    CatalogIssue,
    LocalPaymentEntry,
)
from quotes.cli import main
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.infrastructure.in_memory_catalog import InMemoryCatalogRepository


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def catalog() -> Catalog:
    item = CatalogEntry(
        CatalogItem("tour-a", "Tour A", pen("1.25"), PricingUnit.PER_PERSON),
        "tour",
        "Tour A",
        "Tour A",
    )
    prices = tuple(LocalPrice(c, pen("1.00")) for c in VisitorCategory)
    ticket = LocalPaymentEntry("ticket-a", LocalPaymentInfo("Ticket", prices), "Boleto", "Ticket")
    return Catalog([item], [ticket])


def run(argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def test_clean_catalog_exits_zero_with_counts():
    code, out, err = run(["catalog", "check"], repository=InMemoryCatalogRepository(catalog()))
    assert code == 0
    assert "pricing items: 1" in out
    assert "local payment items: 1" in out
    assert "no issues" in out.lower()
    assert err == ""


def test_warnings_alone_exit_zero_and_are_listed():
    issue = CatalogIssue("warning", "missing_visitor_category", "ticket-a", "lacks child_6_15")
    repo = InMemoryCatalogRepository(catalog(), issues=(issue,))
    code, out, _ = run(["catalog", "check"], repository=repo)
    assert code == 0
    assert "warning ticket-a: lacks child_6_15" in out


def test_errors_exit_one_and_are_listed_before_warnings():
    warn = CatalogIssue("warning", "empty_catalog", "catalog", "no active items")
    err = CatalogIssue("error", "no_prices", "ticket-b", "has no prices")
    repo = InMemoryCatalogRepository(catalog(), issues=(warn, err))
    code, out, _ = run(["catalog", "check"], repository=repo)
    assert code == 1
    assert "error ticket-b: has no prices" in out
    assert out.index("error ticket-b") < out.index("warning catalog")


def test_missing_database_url_exits_two_with_one_line():
    code, out, err = run(["catalog", "check"], env={})
    assert code == 2
    assert out == ""
    assert "DATABASE_URL" in err
    assert len(err.strip().splitlines()) == 1


def test_connection_failure_exits_two_and_never_leaks_the_dsn():
    password = "hunter2-synthetic"
    dsn = f"postgresql://someone:{password}@127.0.0.1:1/nowhere?connect_timeout=1"
    code, out, err = run(["catalog", "check"], env={"DATABASE_URL": dsn})
    assert code == 2
    for text in (out, err):
        assert password not in text
        assert "someone" not in text
        assert dsn not in text
    assert len(err.strip().splitlines()) == 1


def test_malformed_dsn_never_leaks_its_content():
    secret = "hunter2-synthetic"
    code, out, err = run(["catalog", "check"], env={"DATABASE_URL": f"{secret} garbage"})
    assert code == 2
    assert secret not in out + err


def test_unknown_command_is_a_usage_error():
    with pytest.raises(SystemExit) as info:
        run(["catalog", "explode"], repository=InMemoryCatalogRepository())
    assert info.value.code == 2


def test_injected_repository_is_used_even_when_it_is_falsy():
    class FalsyRepository(InMemoryCatalogRepository):
        def __bool__(self) -> bool:
            return False

    code, out, _ = run(["catalog", "check"], repository=FalsyRepository(catalog()))
    assert code == 0
    assert "pricing items: 1" in out
