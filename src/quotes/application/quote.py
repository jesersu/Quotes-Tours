"""Quote use case: turn a request into priced lines using the catalog and the pricing engine.

All money arithmetic stays in the domain; this module only looks items up and wires them in.
"""

from __future__ import annotations

from collections.abc import Iterable
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
    """A catalog item to quote.

    ``days`` overrides the request's days for this line only. ``on_days`` places the item in the
    itinerary and, when ``days`` is not given, sets how many days it is priced for.
    """

    item_id: str
    days: int | None = None
    quantity: int | None = None  # passed to the domain as the explicit PER_UNIT quantity
    on_days: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _require_text("Item id", self.item_id)
        _require_positive_or_none("Item days", self.days)
        _require_positive_or_none("Item quantity", self.quantity)
        on_days = _as_tuple("Item on_days", self.on_days)
        if not all(_is_int(day) and day >= 1 for day in on_days):
            raise InvalidPricingInput("Item on_days must be integers of at least 1")
        if len(set(on_days)) != len(on_days):
            raise InvalidPricingInput("Item on_days must not repeat a day")
        object.__setattr__(self, "on_days", tuple(sorted(on_days)))

    def priced_days(self, request_days: int) -> int:
        """Explicit days, else the number of placed days, else the request's days."""
        if self.days is not None:
            return self.days
        return len(self.on_days) or request_days


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
        if any(item.on_days for item in self.items):
            raise InvalidPricingInput("Extra items cannot have on_days; extras are not itinerary")


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
        for item in self.items:
            if item.on_days and item.on_days[-1] > self.days:
                raise InvalidPricingInput(
                    f"Item on_days must lie within the {self.days} days of the quote"
                )
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
    on_days: tuple[int, ...] = ()  # days of the itinerary this line is placed on


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


@dataclass(frozen=True)
class ItineraryDay:
    """The owner's title for one day of the trip, such as ``Arequipa - Chivay``.

    ``text`` is an optional paragraph for the day, reviewed by the owner before it is printed.
    """

    day: int
    title: str
    text: str | None = None

    def __post_init__(self) -> None:
        if not _is_int(self.day) or self.day < 1:
            raise InvalidPricingInput("Itinerary day must be an integer of at least 1")
        _require_text("Itinerary title", self.title)
        object.__setattr__(self, "title", self.title.strip())
        if self.text is not None:
            _require_text("Itinerary text", self.text)
            object.__setattr__(self, "text", self.text.strip())


@dataclass(frozen=True)
class QuoteOption:
    """One priced alternative of a quote: a request with an optional label and subtitle.

    A label of ``None`` is only for the single unlabeled option of a plain quote. The itinerary
    holds the day titles the owner wrote; the services placed on each day come from the request.
    """

    label: str | None
    subtitle: str | None
    request: QuoteRequest
    itinerary: tuple[ItineraryDay, ...] = ()

    def __post_init__(self) -> None:
        if self.label is not None:
            _require_text("Option label", self.label)
            object.__setattr__(self, "label", self.label.strip())
        if self.subtitle is not None:
            if not isinstance(self.subtitle, str):
                raise InvalidPricingInput("Option subtitle must be text")
            object.__setattr__(self, "subtitle", self.subtitle.strip() or None)
        if not isinstance(self.request, QuoteRequest):
            raise InvalidPricingInput("Option request must be a QuoteRequest")
        itinerary = _as_tuple("Option itinerary", self.itinerary)
        if not all(isinstance(day, ItineraryDay) for day in itinerary):
            raise InvalidPricingInput("Option itinerary must contain only itinerary days")
        numbers = [day.day for day in itinerary]
        if len(set(numbers)) != len(numbers):
            raise InvalidPricingInput("Option itinerary must not repeat a day")
        if numbers and max(numbers) > self.request.days:
            raise InvalidPricingInput(
                f"Option itinerary days must lie within the {self.request.days} days of the option"
            )
        object.__setattr__(self, "itinerary", tuple(sorted(itinerary, key=lambda d: d.day)))


@dataclass(frozen=True)
class QuotedOption:
    label: str | None
    subtitle: str | None
    quote: Quote
    itinerary: tuple[ItineraryDay, ...] = ()


def _quote_lines(
    requested: tuple[RequestedItem, ...], request: QuoteRequest, catalog: Catalog
) -> tuple[QuotedLine, ...]:
    quoted = []
    for item in requested:
        entry = catalog.get_item(item.item_id)
        line = build_line(
            entry.item, item.priced_days(request.days), request.travelers, item.quantity
        )
        quoted.append(QuotedLine(entry, line, item.on_days))
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


def check_option_labels(labels: Iterable[str | None]) -> None:
    """Several options must all be labeled, with unique labels. One option may be unlabeled."""
    labels = list(labels)
    if len(labels) > 1:
        if None in labels:
            raise InvalidPricingInput("Every option needs a label when there are several")
        if len(set(labels)) != len(labels):
            raise InvalidPricingInput("Option labels must be unique")


def build_quote_options(
    options: tuple[QuoteOption, ...], catalog: Catalog, policy: PricingPolicy
) -> tuple[QuotedOption, ...]:
    """Quote every option alone with the same policy; there is no arithmetic across options.

    Several options must all be labeled, with unique labels. One option may be unlabeled.
    """
    options = _as_tuple("Options", options)
    if not options:
        raise InvalidPricingInput("Options need at least one option")
    if not all(isinstance(option, QuoteOption) for option in options):
        raise InvalidPricingInput("Options must contain only quote options")
    check_option_labels(option.label for option in options)
    return tuple(
        QuotedOption(
            option.label,
            option.subtitle,
            build_quote(option.request, catalog, policy),
            option.itinerary,
        )
        for option in options
    )
