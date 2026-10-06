"""In-memory catalog repository for tests and other layers."""

from __future__ import annotations

from quotes.application.catalog import Catalog, CatalogIssue, CatalogLoad


class InMemoryCatalogRepository:
    def __init__(
        self, catalog: Catalog | None = None, issues: tuple[CatalogIssue, ...] = ()
    ) -> None:
        self._load = CatalogLoad(catalog if catalog is not None else Catalog(), tuple(issues))

    def load(self) -> CatalogLoad:
        return self._load
