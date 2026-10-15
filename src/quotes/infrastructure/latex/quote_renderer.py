"""LaTeX adapter: render a priced quote as the text of a Spanish ``.tex`` document.

Only the total and the per-adult price are shown, never a price per service. The adapter reads
money from the quote as the domain priced it and does no arithmetic on it.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from pathlib import Path

from quotes.application.catalog import LocalPaymentEntry
from quotes.application.quote import QuotedLine
from quotes.application.quote_rendering import QuoteDocument
from quotes.domain.catalog import PricingUnit
from quotes.domain.local_payment import VisitorCategory
from quotes.domain.pricing import PriceBreakdown
from quotes.infrastructure.latex import STYLE_PATH
from quotes.infrastructure.latex.escaping import escape_latex, format_money

_UNSAFE_PATH_CHARS = frozenset("{}%#\\~^$& \t\r\n")

_MONTHS = (
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
)

_CATEGORY_ORDER = (
    ("transport", "Transporte"),
    ("transfer", "Traslados"),
    ("guide", "Guiado"),
    ("activity", "Actividades"),
    ("meal", "Alimentación"),
    ("entrance", "Entradas"),
    ("accommodation", "Alojamiento"),
    ("other", "Otros"),
)
_CATEGORY_HEADINGS = dict(_CATEGORY_ORDER)

_BASIS = {
    PricingUnit.PER_GROUP: "por grupo",
    PricingUnit.PER_DAY: "por día",
    PricingUnit.PER_PERSON: "por persona",
    PricingUnit.PER_UNIT: "por unidad",
}

_VISITOR_LABELS = (
    (VisitorCategory.LATIN_AMERICAN_ADULT, "Adulto latinoamericano"),
    (VisitorCategory.FOREIGN_ADULT, "Adulto extranjero"),
    (VisitorCategory.CHILD_6_15, "Niño de 6 a 15 años"),
)
_VISITOR_HEADINGS = dict(_VISITOR_LABELS)
_VISITOR_ORDER = {category: index for index, (category, _) in enumerate(_VISITOR_LABELS)}

_TABLE_OPEN = "\\noindent\n\\begin{tabularx}{\\linewidth}{@{}Xl@{}}"
_PRICE_TABLE_OPEN = "\\noindent\n\\begin{tabularx}{\\linewidth}{@{}Xr@{}}"
_TABLE_CLOSE = "\\end{tabularx}"


def _checked_path(role: str, path: Path) -> str:
    text = path.as_posix()
    if any(char in _UNSAFE_PATH_CHARS for char in text):
        raise ValueError(
            f"The {role} path contains characters that cannot be written inside \\input{{}}: "
            "braces, % # \\ ~ ^ $ &, spaces or line breaks"
        )
    return text


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _spanish_date(day: datetime.date) -> str:
    return f"{day.day} de {_MONTHS[day.month - 1]} de {day.year}"


def _trip_summary(document: QuoteDocument) -> str:
    request = document.quote.request
    parts = [
        _plural(request.days, "día", "días"),
        _plural(request.travelers.adults, "adulto", "adultos"),
    ]
    children = len(request.travelers.child_ages)
    if children:
        parts.append(_plural(children, "niño", "niños"))
    return ", ".join(parts)


def _service_row(quoted: QuotedLine) -> str:
    name = escape_latex(quoted.entry.name_es)
    # The empty group keeps a name starting with "[" or "*" from being read as an option of
    # the previous row break.
    return f"{{}}{name} & {_BASIS[quoted.entry.item.unit]} \\\\"


def _grouped_by_category(lines: Iterable[QuotedLine]) -> list[tuple[str, list[QuotedLine]]]:
    """Group lines by category: known ones in the fixed order, unknown ones after, by name."""
    groups: dict[str, list[QuotedLine]] = {}
    for quoted in lines:
        groups.setdefault(quoted.entry.category, []).append(quoted)
    known = [(key, groups[key]) for key, _ in _CATEGORY_ORDER if key in groups]
    unknown = sorted((key, value) for key, value in groups.items() if key not in _CATEGORY_HEADINGS)
    return known + unknown


def _services_table(lines: Sequence[QuotedLine]) -> str:
    rows = [_TABLE_OPEN, "\\toprule", "\\textbf{Servicio} & \\textbf{Base} \\\\", "\\midrule"]
    for index, (category, group) in enumerate(_grouped_by_category(lines)):
        if index:
            rows.append("\\addlinespace")
        heading = _CATEGORY_HEADINGS.get(category) or escape_latex(category)
        rows.append(f"\\multicolumn{{2}}{{@{{}}l}}{{\\textbf{{{heading}}}}} \\\\")
        rows.extend(_service_row(quoted) for quoted in group)
    rows += ["\\bottomrule", _TABLE_CLOSE]
    return "\n".join(rows)


def _flat_services_table(lines: Sequence[QuotedLine]) -> str:
    rows = [_TABLE_OPEN, "\\toprule", "\\textbf{Servicio} & \\textbf{Base} \\\\", "\\midrule"]
    rows.extend(_service_row(quoted) for quoted in lines)
    rows += ["\\bottomrule", _TABLE_CLOSE]
    return "\n".join(rows)


def _price_table(breakdown: PriceBreakdown) -> str:
    rows = [
        _PRICE_TABLE_OPEN,
        f"Precio total & \\textbf{{{format_money(breakdown.final_pen)}}} \\\\",
        f"Precio por adulto & \\textbf{{{format_money(breakdown.per_adult_pen)}}} \\\\",
        "\\addlinespace",
        f"Referencia en dólares, total & {format_money(breakdown.final_usd)} \\\\",
        f"Referencia en dólares, por adulto & {format_money(breakdown.per_adult_usd)} \\\\",
        _TABLE_CLOSE,
    ]
    return "\n".join(rows)


def _extras_section(document: QuoteDocument) -> list[str]:
    parts = ["\\sect{Opcionales}"]
    for extra in document.quote.extras:
        parts.append(f"\\par\\medskip\\noindent\\textbf{{{escape_latex(extra.label)}}}\\par")
        parts.append(_flat_services_table(extra.lines))
        parts.append(_price_table(extra.breakdown))
    parts.append(
        "\\notebox{Los servicios opcionales no están incluidos en el total anterior; "
        "se cotizan por separado.}"
    )
    return parts


def _local_price_rows(local: LocalPaymentEntry) -> list[str]:
    """One row per reference price, in the fixed visitor order.

    A category with no Spanish label fails loudly: dropping it would hide a price the client
    is expected to pay on site.
    """
    for price in local.info.prices:
        if price.category not in _VISITOR_HEADINGS:
            raise ValueError(f"No Spanish label for visitor category {price.category!r}")
    prices = sorted(local.info.prices, key=lambda price: _VISITOR_ORDER[price.category])
    return [
        f"{_VISITOR_HEADINGS[price.category]} & {format_money(price.price)} \\\\"
        for price in prices
    ]


def _local_payments_section(document: QuoteDocument) -> list[str]:
    parts = ["\\sect{Pagos en destino}"]
    for local in document.quote.paid_locally:
        parts.append(f"\\par\\medskip\\noindent\\textbf{{{escape_latex(local.name_es)}}}\\par")
        rows = [_PRICE_TABLE_OPEN, *_local_price_rows(local), _TABLE_CLOSE]
        parts.append("\n".join(rows))
    parts.append(
        "\\notebox{Estos importes se pagan directamente en destino y no forman parte del total.}"
    )
    return parts


class LatexQuoteRenderer:
    """Render a quote as a complete Spanish LaTeX document using the brand style."""

    def __init__(
        self, company_path: Path, style_path: Path = STYLE_PATH, assets_dir: Path | None = None
    ) -> None:
        self._company = _checked_path("company", company_path)
        self._style = _checked_path("style", style_path)
        self._assets = _checked_path("assets", assets_dir) if assets_dir is not None else None

    def render(self, document: QuoteDocument) -> str:
        lines = [*self._preamble(), "\\begin{document}", *self._body(document), "\\end{document}"]
        return "\n".join(lines) + "\n"

    def _preamble(self) -> list[str]:
        lines = ["\\documentclass[11pt,a4paper]{article}", "\\newcommand{\\CoLang}{es}"]
        if self._assets is not None:
            lines.append(f"\\newcommand{{\\CoAssetsDir}}{{{self._assets.rstrip('/')}/}}")
        # The company file must come first: the style refuses to load without it.
        lines += [f"\\input{{{self._company}}}", f"\\input{{{self._style}}}"]
        return lines

    def _body(self, document: QuoteDocument) -> list[str]:
        quote = document.quote
        parts = [
            "\\letterhead",
            "\\par\\vspace{1em}\\noindent"
            f"{{\\LARGE\\bfseries {escape_latex(document.title)}}}\\par",
            f"\\noindent Preparado para: \\textbf{{{escape_latex(document.client_name)}}}\\par",
            f"\\noindent {_spanish_date(document.issued_on)}\\par",
            f"\\noindent {_trip_summary(document)}\\par",
            "\\sect{Servicios incluidos}",
            _services_table(quote.lines),
            "\\par\\medskip",
            _price_table(quote.breakdown),
        ]
        if quote.extras:
            parts += _extras_section(document)
        if quote.paid_locally:
            parts += _local_payments_section(document)
        parts += [
            "\\sect{Nuestras credenciales}",
            "\\credentials",
            f"\\signature{{{escape_latex(document.signed_by)}}}",
        ]
        return parts
