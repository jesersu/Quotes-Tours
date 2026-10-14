"""LaTeX-safe text and money formatting. Everything that reaches the document goes through here."""

from __future__ import annotations

import re

from quotes.domain.money import Currency, Money

_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# Line breaks and tabs are matched in the same pass so a value can never start a paragraph.
_PATTERN = re.compile(r"[\\&%$#_{}~^]|[\r\n\t\f\v\x85\u2028\u2029]+")

_MONEY_PREFIX = {Currency.PEN: "S/ ", Currency.USD: r"US\$ "}


def escape_latex(text: str) -> str:
    """Escape LaTeX special characters in one pass so the text prints literally."""
    return _PATTERN.sub(lambda match: _SPECIALS.get(match.group(), " "), text)


def format_money(money: Money) -> str:
    """Format as already-LaTeX-safe text: ``S/ 1,250.00`` or ``US\\$ 357.14``."""
    return f"{_MONEY_PREFIX[money.currency]}{money.quantized().amount:,.2f}"
