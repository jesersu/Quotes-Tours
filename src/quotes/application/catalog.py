"""Catalog read model and the port used to load it.

Domain objects stay minimal (price, unit, one display name). The catalog entries here wrap
them with the extra data the planner and renderer need: category, bilingual names, duration.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from quotes.domain.catalog import CatalogItem
from quotes.domain.errors import DomainError, InvalidPricingInput
from quotes.domain.local_payment import LocalPaymentInfo


class CatalogItemNotFound(DomainError):
    """Raised when a pricing item id is not in the catalog."""


class LocalPaymentNotFound(DomainError):
    """Raised when a paid-locally item id is not in the catalog."""


class DuplicateCatalogId(DomainError):
    """Raised when a catalog is built with a repeated id."""


def _require_text(label: str, owner_id: str, value: str) -> None:
    if not value.strip():
        raise InvalidPricingInput(f"{label} must not be empty: {owner_id}")


@dataclass(frozen=True)
class CatalogEntry:
    item: CatalogItem
    category: str
    name_es: str
    name_en: str
    duration_days: int | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        _require_text("Category", self.item.id, self.category)
        _require_text("Spanish name", self.item.id, self.name_es)
        _require_text("English name", self.item.id, self.name_en)
        if self.duration_days is not None and self.duration_days < 1:
            raise InvalidPricingInput(f"Duration must be at least 1 day: {self.item.id}")

    @property
    def id(self) -> str:
        return self.item.id


@dataclass(frozen=True)
class LocalPaymentEntry:
    id: str
    info: LocalPaymentInfo
    name_es: str
    name_en: str
    notes: str | None = None

    def __post_init__(self) -> None:
        _require_text("Spanish name", self.id, self.name_es)
        _require_text("English name", self.id, self.name_en)


def _index[T](entries: Iterable[T], key: str, kind: str) -> dict[str, T]:
    indexed: dict[str, T] = {}
    for entry in entries:
        entry_id = getattr(entry, key)
        if entry_id in indexed:
            raise DuplicateCatalogId(f"Duplicate {kind} id: {entry_id}")
        indexed[entry_id] = entry
    return indexed


class Catalog:
    """Immutable-by-convention lookup of pricing entries and paid-locally entries by id."""

    def __init__(
        self,
        entries: Iterable[CatalogEntry] = (),
        local_payments: Iterable[LocalPaymentEntry] = (),
    ) -> None:
        self._entries = _index(entries, "id", "pricing item")
        self._local_payments = _index(local_payments, "id", "local payment")

    def get_item(self, item_id: str) -> CatalogEntry:
        try:
            return self._entries[item_id]
        except KeyError:
            raise CatalogItemNotFound(f"Unknown catalog item: {item_id}") from None

    def items(self) -> tuple[CatalogEntry, ...]:
        return tuple(self._entries.values())

    def local_payment(self, item_id: str) -> LocalPaymentEntry:
        try:
            return self._local_payments[item_id]
        except KeyError:
            raise LocalPaymentNotFound(f"Unknown local payment item: {item_id}") from None

    def local_payments(self) -> tuple[LocalPaymentEntry, ...]:
        return tuple(self._local_payments.values())


class CatalogRepository(Protocol):
    def load(self) -> Catalog:
        """Return the active catalog."""
        ...
