from decimal import Decimal

import pytest

from quotes.application.catalog import (
    Catalog,
    CatalogEntry,
    CatalogItemNotFound,
    CatalogRepository,
    DuplicateCatalogId,
    LocalPaymentEntry,
    LocalPaymentNotFound,
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
    assert repo.load() is catalog


def test_in_memory_repository_defaults_to_empty():
    assert InMemoryCatalogRepository().load().items() == ()
