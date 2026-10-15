"""Port for turning a priced quote into a client-facing document.

The renderer only formats what the domain already priced; it never computes money.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from quotes.application.quote import Quote
from quotes.domain.errors import InvalidPricingInput


def _require_text(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPricingInput(f"{label} must be non-empty text")
    return value.strip()


class Language(StrEnum):
    """The language a document is written in; the value is its ISO 639-1 code."""

    SPANISH = "es"
    ENGLISH = "en"


@dataclass(frozen=True)
class QuoteDocument:
    """A priced quote plus the wording around it: who it is for, its title, date and signer."""

    quote: Quote
    client_name: str
    title: str
    issued_on: datetime.date
    signed_by: str
    language: Language = Language.SPANISH

    def __post_init__(self) -> None:
        if not isinstance(self.quote, Quote):
            raise InvalidPricingInput("Quote must be a Quote instance")
        object.__setattr__(self, "client_name", _require_text("Client name", self.client_name))
        object.__setattr__(self, "title", _require_text("Title", self.title))
        object.__setattr__(self, "signed_by", _require_text("Signer", self.signed_by))
        # A datetime is a date subclass; reject it so the issue date never carries a time.
        if not isinstance(self.issued_on, datetime.date) or isinstance(
            self.issued_on, datetime.datetime
        ):
            raise InvalidPricingInput("Issue date must be a date, not a datetime")
        try:
            language = Language(self.language)
        except ValueError:
            raise InvalidPricingInput("Language must be a known language") from None
        object.__setattr__(self, "language", language)


@runtime_checkable
class QuoteRenderer(Protocol):
    def render(self, document: QuoteDocument) -> str: ...
