"""LaTeX adapter: render a priced quote as the text of a ``.tex`` document in Spanish or English.

Only the total and the per-adult price are shown, never a price per service. The adapter reads
money from the quote as the domain priced it and does no arithmetic on it.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from quotes.application.catalog import LocalPaymentEntry
from quotes.application.quote import QuotedLine
from quotes.application.quote_rendering import Language, QuoteDocument
from quotes.domain.catalog import PricingUnit
from quotes.domain.local_payment import VisitorCategory
from quotes.domain.pricing import PriceBreakdown
from quotes.infrastructure.latex import STYLE_PATH
from quotes.infrastructure.latex.escaping import escape_latex, format_money

_UNSAFE_PATH_CHARS = frozenset("{}%#\\~^$& \t\r\n")


@dataclass(frozen=True)
class _Texts:
    """Every fixed text of the document in one language, plus how its date and counts read."""

    lang: Language
    months: tuple[str, ...]
    date_pattern: str
    prepared_for: str
    day: tuple[str, str]
    adult: tuple[str, str]
    child: tuple[str, str]
    included: str
    optional: str
    paid_on_site: str
    credentials: str
    service: str
    basis: str
    total: str
    per_adult: str
    usd_total: str
    usd_per_adult: str
    optional_note: str
    local_note: str
    categories: tuple[tuple[str, str], ...]
    units: dict[PricingUnit, str]
    visitors: tuple[tuple[VisitorCategory, str], ...]
    language_name: str

    def date(self, day: datetime.date) -> str:
        return self.date_pattern.format(
            day=day.day, month=self.months[day.month - 1], year=day.year
        )


_SPANISH = _Texts(
    lang=Language.SPANISH,
    date_pattern="{day} de {month} de {year}",
    months=(
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ),
    prepared_for="Preparado para",
    day=("día", "días"),
    adult=("adulto", "adultos"),
    child=("niño", "niños"),
    included="Servicios incluidos",
    optional="Opcionales",
    paid_on_site="Pagos en destino",
    credentials="Nuestras credenciales",
    service="Servicio",
    basis="Base",
    total="Precio total",
    per_adult="Precio por adulto",
    usd_total="Referencia en dólares, total",
    usd_per_adult="Referencia en dólares, por adulto",
    optional_note=(
        "Los servicios opcionales no están incluidos en el total anterior; se cotizan por separado."
    ),
    local_note="Estos importes se pagan directamente en destino y no forman parte del total.",
    categories=(
        ("transport", "Transporte"),
        ("transfer", "Traslados"),
        ("guide", "Guiado"),
        ("activity", "Actividades"),
        ("meal", "Alimentación"),
        ("entrance", "Entradas"),
        ("accommodation", "Alojamiento"),
        ("other", "Otros"),
    ),
    units={
        PricingUnit.PER_GROUP: "por grupo",
        PricingUnit.PER_DAY: "por día",
        PricingUnit.PER_PERSON: "por persona",
        PricingUnit.PER_UNIT: "por unidad",
    },
    visitors=(
        (VisitorCategory.LATIN_AMERICAN_ADULT, "Adulto latinoamericano"),
        (VisitorCategory.FOREIGN_ADULT, "Adulto extranjero"),
        (VisitorCategory.CHILD_6_15, "Niño de 6 a 15 años"),
    ),
    language_name="Spanish",
)

_ENGLISH = _Texts(
    lang=Language.ENGLISH,
    date_pattern="{day} {month} {year}",
    months=(
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    prepared_for="Prepared for",
    day=("day", "days"),
    adult=("adult", "adults"),
    child=("child", "children"),
    included="Included services",
    optional="Optional extras",
    paid_on_site="Paid on site",
    credentials="Our credentials",
    service="Service",
    basis="Basis",
    total="Total price",
    per_adult="Price per adult",
    usd_total="US dollar reference, total",
    usd_per_adult="US dollar reference, per adult",
    optional_note=(
        "Optional extras are not included in the total above; they are quoted separately."
    ),
    local_note="These amounts are paid directly on site and are not part of the total.",
    categories=(
        ("transport", "Transport"),
        ("transfer", "Transfers"),
        ("guide", "Guiding"),
        ("activity", "Activities"),
        ("meal", "Meals"),
        ("entrance", "Entrance fees"),
        ("accommodation", "Accommodation"),
        ("other", "Other"),
    ),
    units={
        PricingUnit.PER_GROUP: "per group",
        PricingUnit.PER_DAY: "per day",
        PricingUnit.PER_PERSON: "per person",
        PricingUnit.PER_UNIT: "per unit",
    },
    visitors=(
        (VisitorCategory.LATIN_AMERICAN_ADULT, "Latin American adult"),
        (VisitorCategory.FOREIGN_ADULT, "Foreign adult"),
        (VisitorCategory.CHILD_6_15, "Child aged 6 to 15"),
    ),
    language_name="English",
)

_TEXTS = {Language.SPANISH: _SPANISH, Language.ENGLISH: _ENGLISH}

_TABLE_OPEN = "\\noindent\n\\begin{tabularx}{\\linewidth}{@{}Xl@{}}"
_PRICE_TABLE_OPEN = "\\noindent\n\\begin{tabularx}{\\linewidth}{@{}Xr@{}}"
_TABLE_CLOSE = "\\end{tabularx}"
_KEEP_WITH_NEXT = "\\par\\nopagebreak"


def _checked_path(role: str, path: Path) -> str:
    text = path.as_posix()
    if any(char in _UNSAFE_PATH_CHARS for char in text):
        raise ValueError(
            f"The {role} path contains characters that cannot be written inside \\input{{}}: "
            "braces, % # \\ ~ ^ $ &, spaces or line breaks"
        )
    return text


def _plural(count: int, forms: tuple[str, str]) -> str:
    return f"{count} {forms[0] if count == 1 else forms[1]}"


def _trip_summary(document: QuoteDocument, texts: _Texts) -> str:
    request = document.quote.request
    parts = [
        _plural(request.days, texts.day),
        _plural(request.travelers.adults, texts.adult),
    ]
    children = len(request.travelers.child_ages)
    if children:
        parts.append(_plural(children, texts.child))
    return ", ".join(parts)


def _service_name(quoted: QuotedLine, texts: _Texts) -> str:
    entry = quoted.entry
    return entry.name_en if texts.lang is Language.ENGLISH else entry.name_es


def _service_row(quoted: QuotedLine, texts: _Texts) -> str:
    name = escape_latex(_service_name(quoted, texts))
    # The empty group keeps a name starting with "[" or "*" from being read as an option of
    # the previous row break.
    return f"{{}}{name} & {texts.units[quoted.entry.item.unit]} \\\\"


def _grouped_by_category(
    lines: Iterable[QuotedLine], texts: _Texts
) -> list[tuple[str, list[QuotedLine]]]:
    """Group lines by category: known ones in the fixed order, unknown ones after, by name."""
    groups: dict[str, list[QuotedLine]] = {}
    for quoted in lines:
        groups.setdefault(quoted.entry.category, []).append(quoted)
    known_keys = {key for key, _ in texts.categories}
    known = [(key, groups[key]) for key, _ in texts.categories if key in groups]
    unknown = sorted((key, value) for key, value in groups.items() if key not in known_keys)
    return known + unknown


def _table_head(texts: _Texts) -> list[str]:
    return [
        _TABLE_OPEN,
        "\\toprule",
        f"\\textbf{{{texts.service}}} & \\textbf{{{texts.basis}}} \\\\",
        "\\midrule",
    ]


def _services_table(lines: Sequence[QuotedLine], texts: _Texts) -> str:
    rows = _table_head(texts)
    headings = dict(texts.categories)
    for index, (category, group) in enumerate(_grouped_by_category(lines, texts)):
        if index:
            rows.append("\\addlinespace")
        heading = headings.get(category) or escape_latex(category)
        rows.append(f"\\multicolumn{{2}}{{@{{}}l}}{{\\textbf{{{heading}}}}} \\\\")
        rows.extend(_service_row(quoted, texts) for quoted in group)
    rows += ["\\bottomrule", _TABLE_CLOSE]
    return "\n".join(rows)


def _flat_services_table(lines: Sequence[QuotedLine], texts: _Texts) -> str:
    rows = _table_head(texts)
    rows.extend(_service_row(quoted, texts) for quoted in lines)
    rows += ["\\bottomrule", _TABLE_CLOSE]
    return "\n".join(rows)


def _price_table(breakdown: PriceBreakdown, texts: _Texts) -> str:
    rows = [
        _PRICE_TABLE_OPEN,
        f"{texts.total} & \\textbf{{{format_money(breakdown.final_pen)}}} \\\\",
        f"{texts.per_adult} & \\textbf{{{format_money(breakdown.per_adult_pen)}}} \\\\",
        "\\addlinespace",
        f"{texts.usd_total} & {format_money(breakdown.final_usd)} \\\\",
        f"{texts.usd_per_adult} & {format_money(breakdown.per_adult_usd)} \\\\",
        _TABLE_CLOSE,
    ]
    return "\n".join(rows)


def _extras_section(document: QuoteDocument, texts: _Texts) -> list[str]:
    parts = [f"\\sect{{{texts.optional}}}"]
    for extra in document.quote.extras:
        # Each extra reads as one unit, so its label, services and prices share a page.
        parts.append(f"\\par\\medskip\\noindent\\textbf{{{escape_latex(extra.label)}}}\\par")
        parts.append(_KEEP_WITH_NEXT)
        parts.append(_flat_services_table(extra.lines, texts))
        parts.append(_KEEP_WITH_NEXT)
        parts.append(_price_table(extra.breakdown, texts))
    parts.append(f"\\notebox{{{texts.optional_note}}}")
    return parts


def _local_price_rows(local: LocalPaymentEntry, texts: _Texts) -> list[str]:
    """One row per reference price, in the fixed visitor order.

    A category with no label in the document language fails loudly: dropping it would hide a
    price the client is expected to pay on site.
    """
    labels = dict(texts.visitors)
    order = {category: index for index, (category, _) in enumerate(texts.visitors)}
    for price in local.info.prices:
        if price.category not in labels:
            raise ValueError(
                f"No {texts.language_name} label for visitor category {price.category!r}"
            )
    prices = sorted(local.info.prices, key=lambda price: order[price.category])
    return [f"{labels[price.category]} & {format_money(price.price)} \\\\" for price in prices]


def _local_payments_section(document: QuoteDocument, texts: _Texts) -> list[str]:
    parts = [f"\\sect{{{texts.paid_on_site}}}"]
    for local in document.quote.paid_locally:
        name = local.name_en if texts.lang is Language.ENGLISH else local.name_es
        parts.append(f"\\par\\medskip\\noindent\\textbf{{{escape_latex(name)}}}\\par")
        rows = [_PRICE_TABLE_OPEN, *_local_price_rows(local, texts), _TABLE_CLOSE]
        parts.append("\n".join(rows))
    parts.append(f"\\notebox{{{texts.local_note}}}")
    return parts


class LatexQuoteRenderer:
    """Render a quote as a complete LaTeX document using the brand style.

    The document language (Spanish or English) comes from the ``QuoteDocument``.
    """

    def __init__(
        self, company_path: Path, style_path: Path = STYLE_PATH, assets_dir: Path | None = None
    ) -> None:
        self._company = _checked_path("company", company_path)
        self._style = _checked_path("style", style_path)
        self._assets = _checked_path("assets", assets_dir) if assets_dir is not None else None

    def render(self, document: QuoteDocument) -> str:
        texts = _TEXTS[document.language]
        lines = [
            *self._preamble(texts),
            "\\begin{document}",
            *self._body(document, texts),
            "\\end{document}",
        ]
        return "\n".join(lines) + "\n"

    def _preamble(self, texts: _Texts) -> list[str]:
        lines = [
            "\\documentclass[11pt,a4paper]{article}",
            f"\\newcommand{{\\CoLang}}{{{texts.lang}}}",
        ]
        if self._assets is not None:
            lines.append(f"\\newcommand{{\\CoAssetsDir}}{{{self._assets.rstrip('/')}/}}")
        # The company file must come first: the style refuses to load without it.
        lines += [f"\\input{{{self._company}}}", f"\\input{{{self._style}}}"]
        return lines

    def _body(self, document: QuoteDocument, texts: _Texts) -> list[str]:
        quote = document.quote
        parts = [
            "\\letterhead",
            "\\par\\vspace{1em}\\noindent"
            f"{{\\LARGE\\bfseries {escape_latex(document.title)}}}\\par",
            f"\\noindent {texts.prepared_for}: "
            f"\\textbf{{{escape_latex(document.client_name)}}}\\par",
            f"\\noindent {texts.date(document.issued_on)}\\par",
            f"\\noindent {_trip_summary(document, texts)}\\par",
            f"\\sect{{{texts.included}}}",
            _services_table(quote.lines, texts),
            "\\par\\medskip",
            _price_table(quote.breakdown, texts),
        ]
        if quote.extras:
            parts += _extras_section(document, texts)
        if quote.paid_locally:
            parts += _local_payments_section(document, texts)
        parts += [
            f"\\keepsect{{{texts.credentials}}}{{\\credentials}}",
            f"\\signature{{{escape_latex(document.signed_by)}}}",
        ]
        return parts
