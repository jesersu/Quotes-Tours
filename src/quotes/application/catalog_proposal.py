"""Pure heuristics that turn raw spreadsheet rows into proposed catalog draft entries.

Nothing here touches files. Every proposed entry is marked ``needs_review`` because the rules
are keyword guesses; the owner confirms or corrects them in the draft before any SQL is made.

Rule table (matched on the upper-cased, accent-folded, whitespace-collapsed name, in this order):

==============================================  ===========  ======  ===========================
Name                                             category     unit    English name
==============================================  ===========  ======  ===========================
known local payment (``LOCAL_PAYMENT_RULES``)    local payment (see below)
``TRASLADO ...``                                 transfer     group   "Airport transfer" if the
                                                                      name has AEROPUERTO
``MOVILIDAD <place> N DIA(S) [+ PUNO]``          transport    group   "Private transport <place>,
                                                                      N day(s) [+ Puno]";
                                                                      ``duration_days`` = N
``GUIA ...``                                     guide        day     "Official guide, <place>"
``DESAYUNO|ALMUERZO|CENA ...``                   meal         person  "<place> buffet breakfast |
                                                                      buffet lunch | dinner with
                                                                      show (a la carte)"
``TICKET(S) ...``, ``INGRESO|INGRSO ...``,       entrance     person  "<place> entrance ticket",
``... AGUAS TERMALES ...``                                            "Hot springs entrance,
                                                                      <place>"
``CABALGATA ...``                                activity     person  "Horseback ride <rest>"
anything else                                    other        unit    the Spanish text
==============================================  ===========  ======  ===========================

When no English rule applies the English name is the cleaned Spanish text. Spelling in the
Spanish name is never corrected; the verbatim sheet text is kept in ``source_name``.

Paid-locally items (information only, never added to a quote total) are listed in
``LOCAL_PAYMENT_RULES``: the sheet price goes to the ``foreign_adult`` category and the other
visitor categories stay ``null`` until the owner fills them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

VISITOR_CATEGORIES = ("latin_american_adult", "foreign_adult", "child_6_15")


@dataclass(frozen=True)
class RawRow:
    name: str
    price: Decimal
    row: int


@dataclass(frozen=True)
class LocalPaymentRule:
    id: str
    name_en: str


# Known paid-locally items, keyed by folded upper-case sheet name. Add new entries here.
LOCAL_PAYMENT_RULES: dict[str, LocalPaymentRule] = {
    "TICKETS INGRESO COLCA": LocalPaymentRule("colca-tourist-ticket", "Colca tourist ticket"),
}


@dataclass(frozen=True)
class Proposal:
    pricing_items: list[dict[str, Any]]
    local_payments: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {"pricing_items": self.pricing_items, "local_payments": self.local_payments}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _collapse(text: str) -> str:
    return " ".join(text.split())


def slugify(text: str) -> str:
    """Lower-case, accent-free, hyphen-separated; always satisfies the database slug check."""
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(text).lower()).strip("-")
    return slug or "item"


def clean_name(text: str) -> str:
    """Normalise whitespace and use sentence case. Spelling is kept as typed."""
    collapsed = _collapse(text)
    return collapsed[:1].upper() + collapsed[1:].lower()


_LOWER_WORDS = {"DE": "de", "DEL": "del", "LA": "la", "EL": "el", "A": "a", "Y": "and"}


def _place(text: str) -> str:
    words = []
    for word in _collapse(text).split():
        upper = word.upper()
        words.append(_LOWER_WORDS.get(upper, word if word == "+" else word.capitalize()))
    return " ".join(words)


@dataclass(frozen=True)
class _Guess:
    category: str
    unit: str
    name_en: str | None = None
    duration_days: int | None = None
    hints: tuple[str, ...] = ()


def _slice(original: str, folded: str, start: int, end: int) -> str:
    """Take the span of the folded text from the original, so accents survive in place names."""
    return original[start:end] if len(original) == len(folded) else folded[start:end]


def _guess(original_upper: str, folded: str) -> _Guess:
    if folded.startswith("TRASLADO"):
        en = "Airport transfer" if "AEROPUERTO" in folded else None
        return _Guess("transfer", "group", en, hints=("confirm the transfer direction",))
    if m := re.match(r"^MOVILIDAD\s+(.*?)\s*(\d+)\s*DIAS?\s*(\+\s*PUNO)?$", folded):
        days = int(m.group(2))
        place = _place(_slice(original_upper, folded, m.start(1), m.end(1)))
        suffix = " + Puno" if m.group(3) else ""
        en = f"Private transport {place}, {days} {'day' if days == 1 else 'days'}{suffix}".replace(
            "transport , ", "transport, "
        )
        return _Guess("transport", "group", en, days)
    if folded.startswith("MOVILIDAD"):
        return _Guess("transport", "group", hints=("set duration_days (not found in the name)",))
    if m := re.match(r"^GUIA\s+OFICIAL\s+(?:I\s+)?(.+)$", folded):
        place = _place(_slice(original_upper, folded, m.start(1), m.end(1)))
        return _Guess("guide", "day", f"Official guide, {place}")
    if folded.startswith("GUIA"):
        return _Guess("guide", "day")
    if m := re.match(r"^(DESAYUNO|ALMUERZO|CENA)\s+(.*?)\s*(BUFFET|CON SHOW A LA CARTA)$", folded):
        place = _place(_slice(original_upper, folded, m.start(2), m.end(2)))
        meal = {
            ("DESAYUNO", "BUFFET"): "buffet breakfast",
            ("ALMUERZO", "BUFFET"): "buffet lunch",
            ("CENA", "CON SHOW A LA CARTA"): "dinner with show (a la carte)",
        }.get((m.group(1), m.group(3)))
        en = f"{place} {meal}".strip() if meal else None
        return _Guess("meal", "person", en, hints=("set child_price_pen if children pay less",))
    if re.match(r"^(DESAYUNO|ALMUERZO|CENA)\b", folded):
        return _Guess("meal", "person", hints=("set child_price_pen if children pay less",))
    if m := re.match(r"^(?:INGRESO|INGRSO)\s+AGUAS TERMALES\s*(.*)$", folded):
        place = _place(_slice(original_upper, folded, m.start(1), m.end(1)))
        return _Guess("entrance", "person", f"Hot springs entrance, {place}".rstrip(", "))
    if m := re.match(r"^TICKETS?\s+(?:INGRESO\s+)?(.+)$", folded):
        place = _place(_slice(original_upper, folded, m.start(1), m.end(1)))
        return _Guess("entrance", "person", f"{place} entrance ticket")
    if re.match(r"^(TICKETS?|INGRESO|INGRSO)\b", folded) or "AGUAS TERMALES" in folded:
        return _Guess("entrance", "person")
    if m := re.match(r"^CABALGATA\s*(.*)$", folded):
        rest = _place(_slice(original_upper, folded, m.start(1), m.end(1)))
        return _Guess("activity", "person", f"Horseback ride {rest}".strip())
    return _Guess("other", "unit", hints=("confirm the category",))


def _price(value: Decimal) -> str:
    return f"{value:.2f}"


def _unique_id(base: str, taken: set[str]) -> str:
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


def _pricing_entry(row: RawRow, entry_id: str) -> dict[str, Any]:
    original_upper = _collapse(row.name).upper()
    guess = _guess(original_upper, _fold(original_upper))
    name_es = clean_name(row.name)
    hints = ["confirm the unit"]
    if guess.name_en is None:
        hints.append("English name is a copy of the Spanish text: translate it")
    else:
        hints.append("confirm the English name")
    hints.extend(guess.hints)
    return {
        "id": entry_id,
        "name_es": name_es,
        "name_en": guess.name_en or name_es,
        "category": guess.category,
        "unit": guess.unit,
        "duration_days": guess.duration_days,
        "price_pen": _price(row.price),
        "child_price_pen": None,
        "active": True,
        "notes": None,
        "source_name": row.name,
        "needs_review": True,
        "review_hint": "; ".join(hints),
    }


def _local_entry(row: RawRow, rule: LocalPaymentRule) -> dict[str, Any]:
    prices: dict[str, str | None] = dict.fromkeys(VISITOR_CATEGORIES)
    prices["foreign_adult"] = _price(row.price)
    return {
        "id": rule.id,
        "name_es": clean_name(row.name),
        "name_en": rule.name_en,
        "prices": prices,
        "active": True,
        "notes": None,
        "source_name": row.name,
        "needs_review": True,
        "review_hint": (
            "paid by the tourist at the valley entrance, information only; "
            "fill latin_american_adult and child_6_15; confirm foreign_adult"
        ),
    }


def propose_catalog(rows: list[RawRow]) -> Proposal:
    pricing: list[dict[str, Any]] = []
    local: list[dict[str, Any]] = []
    pricing_ids: set[str] = set()
    local_ids: set[str] = set()
    for row in rows:
        key = _fold(_collapse(row.name).upper())
        rule = LOCAL_PAYMENT_RULES.get(key)
        if rule is not None:
            entry = _local_entry(row, rule)
            entry["id"] = _unique_id(rule.id, local_ids)
            local.append(entry)
        else:
            pricing.append(_pricing_entry(row, _unique_id(slugify(row.name), pricing_ids)))
    return Proposal(pricing, local)
