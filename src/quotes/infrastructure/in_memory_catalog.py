"""In-memory catalog repository for tests and other layers."""

from __future__ import annotations

from quotes.application.catalog import Catalog


class InMemoryCatalogRepository:
    def __init__(self, catalog: Catalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else Catalog()

    def load(self) -> Catalog:
        return self._catalog
