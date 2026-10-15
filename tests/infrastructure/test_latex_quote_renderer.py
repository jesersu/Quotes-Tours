import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quotes.application.catalog import Catalog, CatalogEntry, LocalPaymentEntry
from quotes.application.quote import (
    Quote,
    QuoteRequest,
    RequestedExtra,
    RequestedItem,
    build_quote,
)
from quotes.application.quote_rendering import Language, QuoteDocument, QuoteRenderer
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy
from quotes.domain.travelers import Travelers
from quotes.infrastructure.latex import EXAMPLE_COMPANY_PATH, STYLE_PATH
from quotes.infrastructure.latex.escaping import format_money
from quotes.infrastructure.latex.pdf import compile_pdf
from quotes.infrastructure.latex.quote_renderer import LatexQuoteRenderer

needs_tectonic = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic is not installed"
)

POLICY = PricingPolicy(margin_rate=Decimal("0.25"))


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def entry(
    item_id: str,
    unit: PricingUnit = PricingUnit.PER_GROUP,
    price: str = "10.00",
    category: str = "transport",
    name_es: str | None = None,
    child: str | None = None,
) -> CatalogEntry:
    item = CatalogItem(
        item_id, f"Item {item_id}", pen(price), unit, pen(child) if child is not None else None
    )
    return CatalogEntry(item, category, name_es or f"Servicio {item_id}", f"Service {item_id}")


def local_entry(item_id: str, name_es: str = "Boleto turístico") -> LocalPaymentEntry:
    info = LocalPaymentInfo(
        "Tourist ticket",
        (
            LocalPrice(VisitorCategory.LATIN_AMERICAN_ADULT, pen("31.00")),
            LocalPrice(VisitorCategory.FOREIGN_ADULT, pen("71.00")),
            LocalPrice(VisitorCategory.CHILD_6_15, pen("11.00")),
        ),
    )
    return LocalPaymentEntry(item_id, info, name_es, "Tourist ticket")


def quote_of(
    entries: list[CatalogEntry],
    items: list[str] | None = None,
    *,
    days: int = 2,
    travelers: Travelers | None = None,
    extras: tuple[RequestedExtra, ...] = (),
    local: list[LocalPaymentEntry] | None = None,
    policy: PricingPolicy = POLICY,
) -> Quote:
    local = local or []
    request = QuoteRequest(
        days,
        travelers or Travelers(2),
        tuple(RequestedItem(i) for i in (items or [e.id for e in entries])),
        extras,
        tuple(e.id for e in local),
    )
    return build_quote(request, Catalog(entries, local), policy)


def doc_of(quote: Quote, **overrides) -> QuoteDocument:
    fields = {
        "quote": quote,
        "client_name": "Ana Pérez",
        "title": "Cañón del Colca",
        "issued_on": date(2026, 10, 13),
        "signed_by": "Equipo de ventas",
    }
    fields.update(overrides)
    return QuoteDocument(**fields)


def renderer(**kwargs) -> LatexQuoteRenderer:
    return LatexQuoteRenderer(EXAMPLE_COMPANY_PATH, **kwargs)


def render(quote: Quote, **overrides) -> str:
    return renderer().render(doc_of(quote, **overrides))


def simple_quote(**kwargs) -> Quote:
    return quote_of([entry("van")], **kwargs)


# --- port and preamble -------------------------------------------------


def test_adapter_satisfies_the_port_structurally():
    assert isinstance(renderer(), QuoteRenderer)


def test_preamble_declares_spanish_and_loads_company_before_style():
    text = render(simple_quote())

    assert text.startswith("\\documentclass[11pt,a4paper]{article}")
    assert "\\newcommand{\\CoLang}{es}" in text
    company = text.index(f"\\input{{{EXAMPLE_COMPANY_PATH.as_posix()}}}")
    style = text.index(f"\\input{{{STYLE_PATH.as_posix()}}}")
    assert text.index("\\CoLang") < company < style < text.index("\\begin{document}")
    assert text.rstrip().endswith("\\end{document}")


def test_assets_dir_is_declared_only_when_given():
    assert "\\CoAssetsDir" not in render(simple_quote())

    text = renderer(assets_dir=Path("/tmp/brand/assets")).render(doc_of(simple_quote()))

    assert "\\newcommand{\\CoAssetsDir}{/tmp/brand/assets/}" in text
    assert text.index("\\CoAssetsDir") < text.index("\\input")


@pytest.mark.parametrize("bad", ["a b", "a{b", "a}b", "a%b", "a#b", "a\\b", "a~b", "a^b", "a$b"])
def test_company_path_with_unsafe_characters_is_rejected(bad):
    with pytest.raises(ValueError, match="company"):
        LatexQuoteRenderer(Path(bad))


def test_style_and_assets_paths_are_checked_too():
    with pytest.raises(ValueError, match="style"):
        LatexQuoteRenderer(EXAMPLE_COMPANY_PATH, style_path=Path("bad path.tex"))
    with pytest.raises(ValueError, match="assets"):
        LatexQuoteRenderer(EXAMPLE_COMPANY_PATH, assets_dir=Path("bad&dir"))


def test_path_with_a_line_break_is_rejected():
    with pytest.raises(ValueError):
        LatexQuoteRenderer(Path("a\nb.tex"))


def test_render_is_deterministic():
    quote = quote_of(
        [entry("van"), entry("tour", PricingUnit.PER_PERSON, category="activity")],
        extras=(RequestedExtra("Extra", (RequestedItem("van"),)),),
    )

    assert render(quote) == render(quote)


# --- header ------------------------------------------------------------


def test_header_has_letterhead_title_client_and_spanish_date():
    text = render(simple_quote())
    body = text[text.index("\\begin{document}") :]

    assert body.index("\\letterhead") < body.index("Cañón del Colca")
    assert body.index("Cañón del Colca") < body.index("Preparado para")
    assert "Ana Pérez" in body
    assert "13 de octubre de 2026" in body


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 1), "1 de enero de 2026"),
        (date(2026, 12, 31), "31 de diciembre de 2026"),
        (date(2027, 3, 9), "9 de marzo de 2027"),
    ],
)
def test_date_is_written_out_in_spanish(day, expected):
    assert expected in render(simple_quote(), issued_on=day)


@pytest.mark.parametrize(
    ("days", "travelers", "summary"),
    [
        (1, Travelers(1), "1 día, 1 adulto"),
        (2, Travelers(3), "2 días, 3 adultos"),
        (3, Travelers(2, (7,)), "3 días, 2 adultos, 1 niño"),
        (3, Travelers(2, (7, 9)), "3 días, 2 adultos, 2 niños"),
    ],
)
def test_trip_summary_handles_singular_plural_and_children(days, travelers, summary):
    assert summary in render(simple_quote(days=days, travelers=travelers))


def test_children_are_not_mentioned_when_there_are_none():
    assert "niño" not in render(simple_quote())


# --- services table ----------------------------------------------------


def test_services_are_grouped_by_category_in_the_fixed_order():
    entries = [
        entry("a", category="other", name_es="Servicio otros"),
        entry("b", category="entrance", name_es="Servicio entradas"),
        entry("c", category="accommodation", name_es="Servicio alojamiento"),
        entry("d", category="meal", name_es="Servicio comida"),
        entry("e", category="activity", name_es="Servicio actividad"),
        entry("f", category="guide", name_es="Servicio guía"),
        entry("g", category="transfer", name_es="Servicio traslado"),
        entry("h", category="transport", name_es="Servicio transporte"),
    ]
    text = render(quote_of(entries))

    headings = [
        "Transporte",
        "Traslados",
        "Guiado",
        "Actividades",
        "Alimentación",
        "Entradas",
        "Alojamiento",
        "Otros",
    ]
    services = [
        "Servicio transporte",
        "Servicio traslado",
        "Servicio guía",
        "Servicio actividad",
        "Servicio comida",
        "Servicio entradas",
        "Servicio alojamiento",
        "Servicio otros",
    ]
    assert text.count("\\sect{Servicios incluidos}") == 1
    positions = [text.index(f"\\textbf{{{h}}}") for h in headings]
    assert positions == sorted(positions)
    service_positions = [text.index(s) for s in services]
    assert service_positions == sorted(service_positions)
    for heading, service in zip(headings, services, strict=True):
        assert text.index(f"\\textbf{{{heading}}}") < text.index(service)


def test_request_order_is_kept_inside_a_category():
    entries = [entry("a", name_es="Zeta"), entry("b", name_es="Alfa"), entry("c", name_es="Mu")]
    text = render(quote_of(entries, ["b", "c", "a"]))

    assert text.index("Alfa") < text.index("Mu") < text.index("Zeta")


def test_unknown_categories_come_last_sorted_and_escaped():
    entries = [
        entry("a", category="zebra_x", name_es="Servicio z"),
        entry("b", category="other", name_es="Servicio otros"),
        entry("c", category="alpha&co", name_es="Servicio a"),
    ]
    text = render(quote_of(entries))

    assert text.index("Otros") < text.index(r"\textbf{alpha\&co}")
    assert text.index(r"\textbf{alpha\&co}") < text.index(r"\textbf{zebra\_x}")


@pytest.mark.parametrize(
    ("unit", "basis"),
    [
        (PricingUnit.PER_GROUP, "por grupo"),
        (PricingUnit.PER_DAY, "por día"),
        (PricingUnit.PER_PERSON, "por persona"),
        (PricingUnit.PER_UNIT, "por unidad"),
    ],
)
def test_basis_text_for_each_unit(unit, basis):
    item = RequestedItem("x", quantity=2)
    request = QuoteRequest(2, Travelers(2), (item,))
    quote = build_quote(request, Catalog([entry("x", unit)]), POLICY)

    assert f"& {basis} \\\\" in render(quote)


# --- total-only rule ---------------------------------------------------


def bare_forms(money: Money) -> set[str]:
    """Raw and formatted digit forms of an amount, with and without the thousands comma."""
    amount = money.amount
    forms = {str(amount)}
    if amount == amount.quantize(Decimal("0.01")):
        forms |= {f"{amount:.2f}", f"{amount:,.2f}"}
    return forms


@pytest.mark.parametrize("language", list(Language))
def test_only_total_and_per_adult_prices_reach_the_document(language):
    entries = [
        entry("van", PricingUnit.PER_GROUP, "1234.56"),
        entry("hotel", PricingUnit.PER_DAY, "2345.67", category="accommodation"),
        entry("tour", PricingUnit.PER_PERSON, "3456.78", category="activity", child="4567.89"),
        entry("meal", PricingUnit.PER_UNIT, "5678.91", category="meal"),
    ]
    extra = RequestedExtra("Extra", (RequestedItem("hotel"),))
    request = QuoteRequest(
        2,
        Travelers(2, (7,)),
        (
            RequestedItem("van"),
            RequestedItem("hotel"),
            RequestedItem("tour"),
            RequestedItem("meal", quantity=3),
        ),
        (extra,),
    )
    policy = PricingPolicy(margin_rate=Decimal("0.37"), fx_rate=Decimal("3.43"))
    quote = build_quote(request, Catalog(entries), policy)

    text = render(quote, language=language)

    breakdowns = [quote.breakdown, quote.extras[0].breakdown]
    forbidden: set[str] = set()
    for b in breakdowns:
        for money in (b.subtotal_pen, b.margin_pen, b.sale_pen, b.sale_usd_exact):
            forbidden |= bare_forms(money)
        for line in b.lines:
            forbidden |= bare_forms(line.cost)
            forbidden |= bare_forms(line.item.unit_price)
            if line.item.child_unit_price is not None:
                forbidden |= bare_forms(line.item.child_unit_price)
    allowed = {
        format_money(m)
        for b in breakdowns
        for m in (b.final_pen, b.per_adult_pen, b.final_usd, b.per_adult_usd)
    }
    allowed_bare = {a.split(" ", 1)[1] for a in allowed}
    forbidden -= allowed_bare  # a derived price may coincide only if the engine says so

    for value in sorted(forbidden):
        assert value not in text, value
    for value in sorted(allowed):
        assert value in text, value


def test_price_block_labels_the_dollar_figures_as_reference():
    quote = simple_quote()
    text = render(quote)

    assert format_money(quote.breakdown.final_pen) in text
    assert format_money(quote.breakdown.per_adult_pen) in text
    assert "Referencia en dólares" in text
    assert text.index(format_money(quote.breakdown.final_pen)) < text.index("Referencia en dólares")
    assert text.index("Referencia en dólares") < text.index(format_money(quote.breakdown.final_usd))


# --- extras and paid locally ---------------------------------------------


def two_extras_quote() -> Quote:
    entries = [
        entry("van", price="100.00"),
        entry("balloon", PricingUnit.PER_PERSON, "333.00", category="activity", name_es="Globo"),
        entry("spa", PricingUnit.PER_DAY, "55.00", category="other", name_es="Spa"),
    ]
    extras = (
        RequestedExtra("Globo aerostático", (RequestedItem("balloon"),)),
        RequestedExtra("Spa", (RequestedItem("spa"),)),
    )
    return quote_of(entries, ["van"], extras=extras)


def test_optional_section_is_absent_without_extras():
    assert "Opcionales" not in render(simple_quote())


def test_each_extra_shows_its_own_prices_and_the_main_total_is_unchanged():
    quote = two_extras_quote()
    solo = quote_of([entry("van", price="100.00")])
    text = render(quote)

    assert quote.breakdown.final_pen == solo.breakdown.final_pen
    section = text[text.index("\\sect{Opcionales}") :]
    assert "Globo aerostático" in section
    assert "Spa" in section
    assert "Globo" in section and "por persona" in section
    assert "no están incluidos en el total" in section
    for extra in quote.extras:
        for money in (
            extra.breakdown.final_pen,
            extra.breakdown.per_adult_pen,
            extra.breakdown.final_usd,
            extra.breakdown.per_adult_usd,
        ):
            assert format_money(money) in section
    assert format_money(quote.breakdown.final_pen) not in section


def test_paid_locally_section_is_absent_without_entries():
    assert "Pagos en destino" not in render(simple_quote())


def test_paid_locally_shows_reference_prices_by_visitor_category():
    text = render(quote_of([entry("van")], local=[local_entry("ticket")]))

    section = text[text.index("\\sect{Pagos en destino}") :]
    assert "Boleto turístico" in section
    for label, price in [
        ("Adulto latinoamericano", "S/ 31.00"),
        ("Adulto extranjero", "S/ 71.00"),
        ("Niño de 6 a 15 años", "S/ 11.00"),
    ]:
        assert label in section
        assert price in section
    assert "directamente en destino" in section
    assert "no forman parte del total" in section


def test_paid_locally_rows_follow_the_fixed_visitor_order():
    info = LocalPaymentInfo(
        "Tourist ticket",
        (
            LocalPrice(VisitorCategory.CHILD_6_15, pen("11.00")),
            LocalPrice(VisitorCategory.FOREIGN_ADULT, pen("71.00")),
        ),
    )
    local = LocalPaymentEntry("ticket", info, "Boleto turístico", "Tourist ticket")
    text = render(quote_of([entry("van")], local=[local]))

    assert text.index("Adulto extranjero") < text.index("Niño de 6 a 15 años")
    assert "Adulto latinoamericano" not in text


def test_every_visitor_category_has_a_spanish_label_and_a_row():
    # Iterates the enum so a new member without a label in the renderer is caught here.
    categories = list(VisitorCategory)
    info = LocalPaymentInfo(
        "Tourist ticket",
        tuple(LocalPrice(c, pen(f"{10 + i}.00")) for i, c in enumerate(categories)),
    )
    local = LocalPaymentEntry("ticket", info, "Boleto turístico", "Tourist ticket")

    text = render(quote_of([entry("van")], local=[local]))

    section = text[text.index("\\sect{Pagos en destino}") :]
    for i in range(len(categories)):
        assert f"S/ {10 + i}.00" in section
    rows = [
        line for line in section.splitlines() if "S/ " in line and line.rstrip().endswith("\\\\")
    ]
    assert len(rows) == len(categories)


def test_a_visitor_category_without_a_label_fails_instead_of_being_dropped():
    # LocalPrice does not check the category type; a value with no Spanish label must not
    # silently disappear from the document the client pays from.
    info = LocalPaymentInfo(
        "Tourist ticket",
        (
            LocalPrice(VisitorCategory.FOREIGN_ADULT, pen("71.00")),
            LocalPrice("resident_adult", pen("21.00")),
        ),
    )
    local = LocalPaymentEntry("ticket", info, "Boleto turístico", "Tourist ticket")
    quote = quote_of([entry("van")], local=[local])

    with pytest.raises(ValueError, match="resident_adult"):
        render(quote)


def test_body_ends_with_credentials_and_signature_in_order():
    text = render(simple_quote())

    assert (
        text.index("\\sect{Nuestras credenciales}")
        < text.index("\\credentials")
        < text.index("\\signature{Equipo de ventas}")
    )


# --- escaping -------------------------------------------------------------


NASTY = r"A&B_50% #1 {x} ~^ \ $"
NASTY_ESCAPED = r"A\&B\_50\% \#1 \{x\} \textasciitilde{}\textasciicircum{} \textbackslash{} \$"


def nasty_quote() -> Quote:
    entries = [
        entry("van", category="cat_1", name_es=f"Van {NASTY}"),
        entry("extra", name_es=f"Extra {NASTY}"),
    ]
    return quote_of(
        entries,
        ["van"],
        extras=(RequestedExtra(f"Label {NASTY}", (RequestedItem("extra"),)),),
        local=[local_entry("ticket", name_es=f"Ticket {NASTY}")],
    )


def test_every_user_value_is_escaped():
    text = render(
        nasty_quote(),
        client_name=f"Cliente {NASTY}",
        title=f"Título {NASTY}",
        signed_by=f"Firma {NASTY}",
    )

    for prefix in ["Cliente", "Título", "Firma", "Van", "Extra", "Label", "Ticket"]:
        assert f"{prefix} {NASTY_ESCAPED}" in text
    assert "cat\\_1" in text
    assert NASTY not in text


def test_service_names_are_guarded_against_the_previous_row_break():
    # After a row break LaTeX reads a following "[" or "*" as an option; every service row
    # starts with an empty group to stop it. Checked on the text so it holds without tectonic.
    entries = [entry("van", name_es="[Opcional] Van"), entry("extra", name_es="*Extra")]
    text = render(
        quote_of(
            entries,
            ["van"],
            extras=(RequestedExtra("Más", (RequestedItem("extra"),)),),
        )
    )

    assert "\n{}[Opcional] Van & por grupo" in text
    assert "\n{}*Extra & por grupo" in text


# --- English ------------------------------------------------------------------

EN = Language.ENGLISH

# Rendered by the Spanish-only renderer before the language switch existed, with a fixed
# company and style path; the Spanish output must never drift from it.
SPANISH_GOLDEN = r"""\documentclass[11pt,a4paper]{article}
\newcommand{\CoLang}{es}
\input{company.tex}
\input{style.tex}
\begin{document}
\letterhead
\par\vspace{1em}\noindent{\LARGE\bfseries Cañón del Colca}\par
\noindent Preparado para: \textbf{Ana Pérez}\par
\noindent 13 de octubre de 2026\par
\noindent 2 días, 2 adultos, 1 niño\par
\sect{Servicios incluidos}
\noindent
\begin{tabularx}{\linewidth}{@{}Xl@{}}
\toprule
\textbf{Servicio} & \textbf{Base} \\
\midrule
\multicolumn{2}{@{}l}{\textbf{Transporte}} \\
{}Furgoneta \& chofer & por grupo \\
\addlinespace
\multicolumn{2}{@{}l}{\textbf{Actividades}} \\
{}Servicio tour & por persona \\
\addlinespace
\multicolumn{2}{@{}l}{\textbf{Alojamiento}} \\
{}Servicio bed & por día \\
\addlinespace
\multicolumn{2}{@{}l}{\textbf{zeta\_x}} \\
{}Servicio odd & por grupo \\
\bottomrule
\end{tabularx}
\par\medskip
\noindent
\begin{tabularx}{\linewidth}{@{}Xr@{}}
Precio total & \textbf{S/ 500.00} \\
Precio por adulto & \textbf{S/ 250.00} \\
\addlinespace
Referencia en dólares, total & US\$ 142.86 \\
Referencia en dólares, por adulto & US\$ 71.43 \\
\end{tabularx}
\sect{Opcionales}
\par\medskip\noindent\textbf{Globo aerostático}\par
\noindent
\begin{tabularx}{\linewidth}{@{}Xl@{}}
\toprule
\textbf{Servicio} & \textbf{Base} \\
\midrule
{}Servicio balloon & por persona \\
\bottomrule
\end{tabularx}
\noindent
\begin{tabularx}{\linewidth}{@{}Xr@{}}
Precio total & \textbf{S/ 1,248.75} \\
Precio por adulto & \textbf{S/ 624.38} \\
\addlinespace
Referencia en dólares, total & US\$ 356.79 \\
Referencia en dólares, por adulto & US\$ 178.40 \\
\end{tabularx}
\notebox{Los servicios opcionales no están incluidos en el total anterior; se cotizan por separado.}
\sect{Pagos en destino}
\par\medskip\noindent\textbf{Boleto turístico}\par
\noindent
\begin{tabularx}{\linewidth}{@{}Xr@{}}
Adulto latinoamericano & S/ 31.00 \\
Adulto extranjero & S/ 71.00 \\
Niño de 6 a 15 años & S/ 11.00 \\
\end{tabularx}
\notebox{Estos importes se pagan directamente en destino y no forman parte del total.}
\sect{Nuestras credenciales}
\credentials
\signature{Equipo de ventas}
\end{document}"""


def golden_document() -> QuoteDocument:
    entries = [
        entry("van", price="100.00", name_es="Furgoneta & chofer"),
        entry("tour", PricingUnit.PER_PERSON, "50.00", category="activity", child="30.00"),
        entry("bed", PricingUnit.PER_DAY, "80.00", category="accommodation"),
        entry("odd", category="zeta_x"),
        entry("balloon", PricingUnit.PER_PERSON, "333.00", category="activity"),
    ]
    quote = quote_of(
        entries,
        ["van", "tour", "bed", "odd"],
        travelers=Travelers(2, (7,)),
        extras=(RequestedExtra("Globo aerostático", (RequestedItem("balloon"),)),),
        local=[local_entry("ticket")],
    )
    return doc_of(quote)


def test_spanish_output_is_byte_for_byte_the_frozen_golden():
    golden_renderer = LatexQuoteRenderer(Path("company.tex"), style_path=Path("style.tex"))

    assert golden_renderer.render(golden_document()) == SPANISH_GOLDEN + "\n"


def test_explicit_spanish_equals_the_default():
    quote = simple_quote()

    assert render(quote, language=Language.SPANISH) == render(quote)


def full_quote() -> Quote:
    entries = [
        entry("van", category="transport"),
        entry("transfer", category="transfer"),
        entry("guide", category="guide"),
        entry("tour", PricingUnit.PER_PERSON, category="activity", child="5.00"),
        entry("meal", category="meal"),
        entry("gate", category="entrance"),
        entry("bed", PricingUnit.PER_DAY, category="accommodation"),
        entry("misc", category="other"),
        entry("odd", category="zeta_x"),
        entry("balloon", PricingUnit.PER_PERSON, "333.00", category="activity"),
    ]
    return quote_of(
        entries,
        ["van", "transfer", "guide", "tour", "meal", "gate", "bed", "misc", "odd"],
        travelers=Travelers(2, (7,)),
        extras=(RequestedExtra("Globo aerostático", (RequestedItem("balloon"),)),),
        local=[local_entry("ticket")],
    )


def english(quote: Quote | None = None, **overrides) -> str:
    return render(quote or full_quote(), language=EN, **overrides)


SPANISH_FIXED_TEXTS = [
    "Preparado para",
    "Servicios incluidos",
    "Opcionales",
    "Pagos en destino",
    "Nuestras credenciales",
    "Servicio",
    "Base}",
    "por grupo",
    "por día",
    "por persona",
    "por unidad",
    "Precio",
    "Referencia en dólares",
    "Adulto latinoamericano",
    "Adulto extranjero",
    "Niño",
    "niño",
    "adulto",
    "día",
    "Los servicios opcionales",
    "Estos importes",
    "directamente en destino",
    "Transporte",
    "Traslados",
    "Guiado",
    "Actividades",
    "Alimentación",
    "Entradas",
    "Alojamiento",
    "Otros",
    " de octubre de ",
]


def test_english_preamble_declares_english_before_the_style():
    text = english()

    assert "\\newcommand{\\CoLang}{en}" in text
    assert "\\newcommand{\\CoLang}{es}" not in text
    assert text.index("\\CoLang") < text.index(f"\\input{{{STYLE_PATH.as_posix()}}}")


def test_english_fixed_texts_appear():
    text = english()

    for fixed in [
        "Prepared for: ",
        "\\sect{Included services}",
        "\\sect{Optional extras}",
        "\\sect{Paid on site}",
        "\\sect{Our credentials}",
        "\\textbf{Service} & \\textbf{Basis}",
        "Total price & ",
        "Price per adult & ",
        "US dollar reference, total & ",
        "US dollar reference, per adult & ",
        "Latin American adult & ",
        "Foreign adult & ",
        "Child aged 6 to 15 & ",
        "\\notebox{Optional extras are not included in the total above; "
        "they are quoted separately.}",
        "\\notebox{These amounts are paid directly on site and are not part of the total.}",
    ]:
        assert fixed in text, fixed


def test_no_spanish_fixed_text_reaches_an_english_document():
    text = english()

    for fixed in SPANISH_FIXED_TEXTS:
        assert fixed not in text, fixed


def test_english_categories_use_english_headings_in_the_fixed_order():
    text = english()

    headings = [
        "Transport",
        "Transfers",
        "Guiding",
        "Activities",
        "Meals",
        "Entrance fees",
        "Accommodation",
        "Other",
    ]
    positions = [text.index(f"\\textbf{{{h}}}") for h in headings]
    assert positions == sorted(positions)
    assert text.index("\\textbf{Other}") < text.index("\\textbf{zeta\\_x}")


@pytest.mark.parametrize(
    ("unit", "basis"),
    [
        (PricingUnit.PER_GROUP, "per group"),
        (PricingUnit.PER_DAY, "per day"),
        (PricingUnit.PER_PERSON, "per person"),
        (PricingUnit.PER_UNIT, "per unit"),
    ],
)
def test_english_basis_text_for_each_unit(unit, basis):
    request = QuoteRequest(2, Travelers(2), (RequestedItem("x", quantity=2),))
    quote = build_quote(request, Catalog([entry("x", unit)]), POLICY)

    assert f"& {basis} \\\\" in render(quote, language=EN)


def test_english_names_are_used_for_services_and_local_payments():
    quote = quote_of([entry("van", name_es="Furgoneta")], local=[local_entry("ticket", "Boleto")])
    text = render(quote, language=EN)

    assert "Service van" in text
    assert "Furgoneta" not in text
    assert "\\textbf{Tourist ticket}" in text
    assert "Boleto" not in text


def test_english_extra_labels_client_title_and_signer_are_printed_as_given():
    text = english(client_name="Ana Pérez", title="Cañón del Colca", signed_by="Equipo de ventas")

    for given in ["Globo aerostático", "Ana Pérez", "Cañón del Colca", "Equipo de ventas"]:
        assert given in text


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 1), "1 January 2026"),
        (date(2026, 10, 14), "14 October 2026"),
        (date(2027, 3, 9), "9 March 2027"),
        (date(2026, 12, 31), "31 December 2026"),
    ],
)
def test_date_is_written_out_in_english(day, expected):
    assert f"\\noindent {expected}\\par" in english(simple_quote(), issued_on=day)


@pytest.mark.parametrize(
    ("days", "travelers", "summary"),
    [
        (1, Travelers(1), "1 day, 1 adult"),
        (2, Travelers(3), "2 days, 3 adults"),
        (3, Travelers(2, (7,)), "3 days, 2 adults, 1 child"),
        (3, Travelers(2, (7, 9)), "3 days, 2 adults, 2 children"),
    ],
)
def test_english_trip_summary_handles_singular_plural_and_children(days, travelers, summary):
    text = english(simple_quote(days=days, travelers=travelers))

    assert f"\\noindent {summary}\\par" in text


def test_english_children_are_not_mentioned_when_there_are_none():
    assert "child" not in english(simple_quote())


def test_english_optional_and_local_sections_are_absent_without_entries():
    text = english(simple_quote())

    assert "Optional extras" not in text
    assert "Paid on site" not in text


def test_every_visitor_category_has_an_english_label_and_a_row():
    categories = list(VisitorCategory)
    info = LocalPaymentInfo(
        "Tourist ticket",
        tuple(LocalPrice(c, pen(f"{10 + i}.00")) for i, c in enumerate(categories)),
    )
    local = LocalPaymentEntry("ticket", info, "Boleto turístico", "Tourist ticket")

    text = render(quote_of([entry("van")], local=[local]), language=EN)

    section = text[text.index("\\sect{Paid on site}") :]
    rows = [
        line for line in section.splitlines() if "S/ " in line and line.rstrip().endswith("\\\\")
    ]
    assert len(rows) == len(categories)
    for row in rows:
        assert not row.startswith("S/ ")


def test_an_unlabeled_visitor_category_fails_in_english_too():
    info = LocalPaymentInfo(
        "Tourist ticket",
        (
            LocalPrice(VisitorCategory.FOREIGN_ADULT, pen("71.00")),
            LocalPrice("resident_adult", pen("21.00")),
        ),
    )
    local = LocalPaymentEntry("ticket", info, "Boleto turístico", "Tourist ticket")
    quote = quote_of([entry("van")], local=[local])

    with pytest.raises(ValueError, match="resident_adult"):
        render(quote, language=EN)


def test_english_values_are_escaped():
    text = render(
        nasty_quote(),
        language=EN,
        client_name=f"Cliente {NASTY}",
        title=f"Título {NASTY}",
        signed_by=f"Firma {NASTY}",
    )

    assert NASTY not in text
    assert f"Cliente {NASTY_ESCAPED}" in text
    assert f"Label {NASTY_ESCAPED}" in text
    assert "Service van" in text  # service names come from name_en, not the nasty name_es
    assert "cat\\_1" in text


@needs_tectonic
def test_full_english_quote_compiles_to_a_pdf(tmp_path):
    entries = [
        entry("van", price="100.00", name_es=f"Van {NASTY}"),
        entry("tour", PricingUnit.PER_PERSON, "50.00", category="activity", child="30.00"),
        entry("bed", PricingUnit.PER_DAY, "80.00", category="accommodation"),
        entry("odd", category="cat_1&x"),
        entry("balloon", PricingUnit.PER_PERSON, "333.00", category="activity"),
    ]
    quote = quote_of(
        entries,
        ["van", "tour", "bed", "odd"],
        travelers=Travelers(2, (7,)),
        extras=(RequestedExtra(f"Globo {NASTY}", (RequestedItem("balloon"),)),),
        local=[local_entry("ticket", name_es=f"Ticket {NASTY}")],
    )
    text = render(
        quote,
        language=EN,
        client_name=f"Cliente {NASTY}",
        title=f"Título {NASTY}",
        signed_by=f"Firma {NASTY}",
    )
    out = tmp_path / "quote-en.pdf"

    compile_pdf(text, out)

    assert out.stat().st_size > 0


# --- real compile -----------------------------------------------------------


@needs_tectonic
def test_full_quote_with_special_characters_compiles(tmp_path):
    entries = [
        entry("van", price="100.00", name_es=f"Van {NASTY}"),
        entry("tour", PricingUnit.PER_PERSON, "50.00", category="activity", child="30.00"),
        entry("bed", PricingUnit.PER_DAY, "80.00", category="accommodation"),
        entry("odd", category="cat_1&x"),
        entry("balloon", PricingUnit.PER_PERSON, "333.00", category="activity"),
    ]
    quote = quote_of(
        entries,
        ["van", "tour", "bed", "odd"],
        travelers=Travelers(2, (7,)),
        extras=(
            RequestedExtra(f"Globo {NASTY}", (RequestedItem("balloon"),)),
            RequestedExtra("Otro", (RequestedItem("bed"),)),
        ),
        local=[local_entry("ticket", name_es=f"Ticket {NASTY}")],
    )
    text = render(
        quote, client_name=f"Cliente {NASTY}", title=f"Título {NASTY}", signed_by=f"Firma {NASTY}"
    )
    (tmp_path / "doc.tex").write_text(text, encoding="utf-8")

    result = subprocess.run(
        ["tectonic", "--outdir", str(tmp_path), "doc.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "doc.pdf").stat().st_size > 0


@needs_tectonic
def test_a_name_starting_with_a_bracket_is_not_read_as_a_row_option(tmp_path):
    # After a row break LaTeX reads a following "[" as the optional spacing argument.
    entries = [entry("van", name_es="[Opcional] Van"), entry("bus", name_es="*Bus")]
    quote = quote_of(
        entries,
        ["van", "bus"],
        local=[local_entry("ticket", name_es="[Boleto] turístico")],
    )
    (tmp_path / "doc.tex").write_text(render(quote), encoding="utf-8")

    result = subprocess.run(
        ["tectonic", "--outdir", str(tmp_path), "doc.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "doc.pdf").stat().st_size > 0
