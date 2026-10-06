from decimal import Decimal

import pytest

from quotes.application.catalog import (
    Catalog,
    CatalogEntry,
    CatalogIssue,
    CatalogItemNotFound,
    CatalogLoad,
    CatalogRepository,
    DuplicateCatalogId,
    LocalPaymentEntry,
    LocalPaymentNotFound,
    audit_catalog,
)
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.errors import DomainError, InvalidPricingInput
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.infrastructure.in_memory_catalog import InMemoryCatalogRepository


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def entry(item_id: str = "sample-tour", **overrides) -> CatalogEntry:
    fields = {
        "item": CatalogItem(item_id, "Sample tour", pen("1.25"), PricingUnit.PER_PERSON),
        "category": "tour",
        "name_es": "Tour de muestra",
        "name_en": "Sample tour",
        "duration_days": 1,
        "notes": None,
    }
    fields.update(overrides)
    return CatalogEntry(**fields)


def local_entry(item_id: str = "sample-ticket") -> LocalPaymentEntry:
    info = LocalPaymentInfo(
        "Sample ticket", (LocalPrice(VisitorCategory.FOREIGN_ADULT, pen("2.50")),)
    )
    return LocalPaymentEntry(
        id=item_id, info=info, name_es="Boleto de muestra", name_en="Sample ticket"
    )


def test_entry_exposes_id_and_domain_item():
    e = entry()
    assert e.id == "sample-tour"
    assert e.item.unit is PricingUnit.PER_PERSON


@pytest.mark.parametrize("field", ["category", "name_es", "name_en"])
def test_entry_rejects_blank_text(field):
    with pytest.raises(InvalidPricingInput):
        entry(**{field: "  "})


@pytest.mark.parametrize("days", [0, -1])
def test_entry_rejects_non_positive_duration(days):
    with pytest.raises(InvalidPricingInput):
        entry(duration_days=days)


@pytest.mark.parametrize(
    ("name_es", "name_en"),
    [("", "Ticket"), ("Boleto", ""), ("  ", "Ticket"), ("Boleto", "   ")],
)
def test_local_entry_rejects_blank_names(name_es, name_en):
    with pytest.raises(InvalidPricingInput):
        LocalPaymentEntry(id="x", info=local_entry().info, name_es=name_es, name_en=name_en)


def test_catalog_lookups():
    a, b = entry("tour-a"), entry("tour-b")
    lp = local_entry()
    catalog = Catalog(entries=[a, b], local_payments=[lp])
    assert catalog.get_item("tour-b") is b
    assert catalog.items() == (a, b)
    assert catalog.local_payment("sample-ticket") is lp
    assert catalog.local_payments() == (lp,)


def test_catalog_unknown_item_raises_clear_error():
    catalog = Catalog(entries=[entry()])
    with pytest.raises(CatalogItemNotFound, match="missing-id"):
        catalog.get_item("missing-id")
    with pytest.raises(LocalPaymentNotFound, match="missing-id"):
        catalog.local_payment("missing-id")


def test_not_found_errors_are_domain_errors():
    assert issubclass(CatalogItemNotFound, DomainError)
    assert issubclass(LocalPaymentNotFound, DomainError)
    assert issubclass(DuplicateCatalogId, DomainError)


def test_catalog_rejects_duplicate_ids():
    with pytest.raises(DuplicateCatalogId, match="tour-a"):
        Catalog(entries=[entry("tour-a"), entry("tour-a")])
    with pytest.raises(DuplicateCatalogId, match="sample-ticket"):
        Catalog(local_payments=[local_entry(), local_entry()])


def test_empty_catalog():
    catalog = Catalog()
    assert catalog.items() == ()
    assert catalog.local_payments() == ()


def test_in_memory_repository_returns_its_catalog():
    catalog = Catalog(entries=[entry()])
    repo: CatalogRepository = InMemoryCatalogRepository(catalog)
    loaded = repo.load()
    assert loaded.catalog is catalog
    assert loaded.issues == ()
    assert loaded.ok


def test_in_memory_repository_defaults_to_empty():
    assert InMemoryCatalogRepository().load().catalog.items() == ()


def test_in_memory_repository_can_carry_issues():
    issue = CatalogIssue("error", "invalid_row", "bad-item", "broken")
    assert InMemoryCatalogRepository(issues=(issue,)).load().issues == (issue,)


def test_issue_rejects_unknown_severity():
    with pytest.raises(ValueError, match="severity"):
        CatalogIssue("fatal", "x", "id", "msg")


def test_load_separates_errors_from_warnings():
    err = CatalogIssue("error", "invalid_row", "a", "broken")
    warn = CatalogIssue("warning", "empty_catalog", "catalog", "empty")
    loaded = CatalogLoad(Catalog(), (warn, err))
    assert loaded.errors == (err,)
    assert loaded.warnings == (warn,)
    assert not loaded.ok


def test_warnings_alone_keep_the_load_ok():
    warn = CatalogIssue("warning", "empty_catalog", "catalog", "empty")
    assert CatalogLoad(Catalog(), (warn,)).ok


def test_audit_warns_about_an_empty_catalog():
    issues = audit_catalog(Catalog(local_payments=[local_entry()]))
    assert [(i.severity, i.code, i.subject_id) for i in issues] == [
        ("warning", "empty_catalog", "catalog"),
        ("warning", "missing_visitor_category", "sample-ticket"),
    ]


def test_audit_names_the_missing_visitor_categories():
    (issue,) = audit_catalog(Catalog(entries=[entry()], local_payments=[local_entry()]))
    assert issue.code == "missing_visitor_category"
    assert "latin_american_adult" in issue.message
    assert "child_6_15" in issue.message
    assert "foreign_adult" not in issue.message


def test_audit_is_silent_for_a_complete_catalog():
    prices = tuple(LocalPrice(c, pen("1.00")) for c in VisitorCategory)
    full = LocalPaymentEntry("full-ticket", LocalPaymentInfo("Full", prices), "Completo", "Full")
    assert audit_catalog(Catalog(entries=[entry()], local_payments=[full])) == ()
