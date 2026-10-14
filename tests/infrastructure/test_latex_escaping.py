from decimal import Decimal

import pytest

from quotes.domain.money import Currency, Money
from quotes.infrastructure.latex.escaping import escape_latex, format_money


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ],
)
def test_each_special_character_is_escaped(raw, escaped):
    assert escape_latex(raw) == escaped


def test_several_specials_in_one_string():
    assert escape_latex("A&B 50% #1 a_b") == r"A\&B 50\% \#1 a\_b"


def test_braces_inserted_by_a_replacement_are_not_escaped_again():
    assert escape_latex("\\{x}") == r"\textbackslash{}\{x\}"
    assert escape_latex("~^") == r"\textasciitilde{}\textasciicircum{}"


@pytest.mark.parametrize("raw", ["a\nb", "a\r\nb", "a\tb", "a\n\n\tb"])
def test_line_breaks_and_tabs_collapse_to_one_space(raw):
    assert escape_latex(raw) == "a b"


def test_accented_text_is_untouched():
    text = "¿Qué día? ¡Niño! Cañón, pingüino, Arequipa – Perú"

    assert escape_latex(text) == text


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


@pytest.mark.parametrize(
    ("money", "text"),
    [
        (pen("1250"), "S/ 1,250.00"),
        (pen("0"), "S/ 0.00"),
        (pen("999.5"), "S/ 999.50"),
        (pen("1234567.891"), "S/ 1,234,567.89"),
        (pen("2.005"), "S/ 2.01"),
        (pen("2.004"), "S/ 2.00"),
        (Money(Decimal("357.142857"), Currency.USD), r"US\$ 357.14"),
        (Money(Decimal("0"), Currency.USD), r"US\$ 0.00"),
    ],
)
def test_format_money(money, text):
    assert format_money(money) == text
