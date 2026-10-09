"""Quote use case: turn a request into priced lines using the catalog and the pricing engine.

All money arithmetic stays in the domain; this module only looks items up and wires them in.
"""

from __future__ import annotations

from dataclasses import dataclass

from quotes.application.catalog import Catalog, CatalogEntry, LocalPaymentEntry
from quotes.domain.catalog import QuoteLine, build_line
from quotes.domain.errors import InvalidPricingInput
from quotes.domain.extras import price_optional_extras
from quotes.domain.pricing import PriceBreakdown, PricingPolicy, price_quote
from quotes.domain.travelers import Travelers


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_text(label: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPricingInput(f"{label} must be non-empty text")


def _require_positive_or_none(label: str, value: object) -> None:
    if value is not None and (not _is_int(value) or value < 1):
        raise InvalidPricingInput(f"{label} must be an integer of at least 1")


def _as_tuple(label: str, value: object) -> tuple:
    """Normalize a list-like value; text and non-iterables are rejected, not split or crashed on."""
    if isinstance(value, str | bytes):
        raise InvalidPricingInput(f"{label} must be a list, not text")
    try:
        return tuple(value)
    except TypeError as exc:
        raise InvalidPricingInput(f"{label} must be a list") from exc


def _require_items(label: str, items: tuple[object, ...]) -> None:
    if not items:
        raise InvalidPricingInput(f"{label} needs at least one item")
    if not all(isinstance(item, RequestedItem) for item in items):
        raise InvalidPricingInput(f"{label} must contain only requested items")


@dataclass(frozen=True)
class RequestedItem:
    """A catalog item to quote. ``days`` overrides the request's days for this line only."""

    item_id: str
    days: int | None = None
    quantity: int | None = None  # passed to the domain as the explicit PER_UNIT quantity

    def __post_init__(self) -> None:
        _require_text("Item id", self.item_id)
        _require_positive_or_none("Item days", self.days)
        _require_positive_or_none("Item quantity", self.quantity)


@dataclass(frozen=True)
class RequestedExtra:
    """An optional extra offered separately from the main quote."""

    label: str
    items: tuple[RequestedItem, ...]

    def __post_init__(self) -> None:
        _require_text("Extra label", self.label)
        # The domain trims labels; store the same form so results match back by label.
        object.__setattr__(self, "label", self.label.strip())
        object.__setattr__(self, "items", _as_tuple("Extra items", self.items))
        _require_items("Extra", self.items)


@dataclass(frozen=True)
class QuoteRequest:
    days: int
    travelers: Travelers
    items: tuple[RequestedItem, ...]
    extras: tuple[RequestedExtra, ...] = ()
    paid_locally: tuple[str, ...] = ()  # ids of local payment items

    def __post_init__(self) -> None:
        if not _is_int(self.days) or self.days < 1:
            raise InvalidPricingInput("Days must be an integer of at least 1")
        if not isinstance(self.travelers, Travelers):
            raise InvalidPricingInput("Travelers must be a Travelers instance")
        object.__setattr__(self, "items", _as_tuple("Quote items", self.items))
        object.__setattr__(self, "extras", _as_tuple("Extras", self.extras))
        object.__setattr__(self, "paid_locally", _as_tuple("Paid-locally ids", self.paid_locally))
        _require_items("Quote", self.items)
        if not all(isinstance(extra, RequestedExtra) for extra in self.extras):
            raise InvalidPricingInput("Extras must contain only requested extras")
        for local_id in self.paid_locally:
            _require_text("Paid-locally id", local_id)
        for local_id in self.paid_locally:
            if self.paid_locally.count(local_id) > 1:
                raise InvalidPricingInput(f"Paid-locally ids must be unique: {local_id}")


@dataclass(frozen=True)
class QuotedLine:
    """A priced line next to the catalog entry that carries its bilingual names."""

    entry: CatalogEntry
    line: QuoteLine


@dataclass(frozen=True)
class QuotedExtra:
    label: str
    lines: tuple[QuotedLine, ...]
    breakdown: PriceBreakdown


@dataclass(frozen=True)
class Quote:
    request: QuoteRequest
    lines: tuple[QuotedLine, ...]
    breakdown: PriceBreakdown
    extras: tuple[QuotedExtra, ...]
    paid_locally: tuple[LocalPaymentEntry, ...]


def _quote_lines(
    requested: tuple[RequestedItem, ...], request: QuoteRequest, catalog: Catalog
) -> tuple[QuotedLine, ...]:
    quoted = []
    for item in requested:
        entry = catalog.get_item(item.item_id)
        days = item.days if item.days is not None else request.days
        line = build_line(entry.item, days, request.travelers, item.quantity)
        quoted.append(QuotedLine(entry, line))
    return tuple(quoted)


def build_quote(request: QuoteRequest, catalog: Catalog, policy: PricingPolicy) -> Quote:
    """Look up every requested id, build and price the lines, and price extras separately.

    Unknown ids raise the catalog's own errors. Extras never enter the main breakdown.
    """
    lines = _quote_lines(request.items, request, catalog)
    paid_locally = tuple(catalog.local_payment(local_id) for local_id in request.paid_locally)
    breakdown = price_quote(
        [quoted.line for quoted in lines],
        request.travelers,
        policy,
        [entry.info for entry in paid_locally],
    )

    extra_lines = [
        (extra.label, _quote_lines(extra.items, request, catalog)) for extra in request.extras
    ]
    priced = price_optional_extras(
        [(label, [quoted.line for quoted in quoted_lines]) for label, quoted_lines in extra_lines],
        request.travelers,
        policy,
    )
    # Matched by label (the domain guarantees labels are unique), never by position.
    breakdown_by_label = {price.label: price.breakdown for price in priced}
    extras = tuple(
        QuotedExtra(label, quoted_lines, breakdown_by_label[label])
        for label, quoted_lines in extra_lines
    )
    return Quote(request, lines, breakdown, extras, paid_locally)
