from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quotes.application.quote import QuoteRequest, RequestedExtra, RequestedItem
from quotes.application.quote_rendering import Language
from quotes.domain.travelers import Travelers
from quotes.infrastructure.quote_request_file import InvalidRequestFile, read_quote_request

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "quote-request.example.yaml"

MINIMAL = """\
client: Ana
title: Trip
signed_by: Team
days: 2
travelers:
  adults: 2
pricing:
  margin_rate: 0.25
items:
  - id: van
"""


def write(tmp_path, text, name="req.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def problems_of(tmp_path, text):
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(write(tmp_path, text))
    return caught.value.problems


def replaced(old, new):
    assert old in MINIMAL
    return MINIMAL.replace(old, new)


def test_example_file_parses_into_the_expected_objects():
    loaded = read_quote_request(EXAMPLE)
    assert loaded.request == QuoteRequest(
        days=2,
        travelers=Travelers(2, (8,)),
        items=(
            RequestedItem("van"),
            RequestedItem("guide", days=1),
            RequestedItem("bus-seat", quantity=3),
        ),
        extras=(RequestedExtra("Horseback ride", (RequestedItem("horse"),)),),
        paid_locally=("colca-ticket",),
    )
    assert loaded.policy.margin_rate == Decimal("0.25")
    assert loaded.policy.fx_rate == Decimal("3.5")
    assert loaded.policy.usd_rounding_step == Decimal("5")
    assert (loaded.client_name, loaded.title) == ("Smith family", "Colca Canyon, 2 days")
    assert loaded.signed_by == "Sales team"
    assert loaded.language is Language.ENGLISH
    assert loaded.issued_on == date(2026, 10, 14)


def test_defaults_when_optional_keys_are_absent(tmp_path):
    loaded = read_quote_request(write(tmp_path, MINIMAL))
    assert loaded.language is Language.SPANISH
    assert loaded.issued_on is None
    assert loaded.policy.fx_rate == Decimal("3.5")
    assert loaded.policy.usd_rounding_step is None
    assert loaded.request.extras == ()
    assert loaded.request.paid_locally == ()


def test_unquoted_margin_is_exact_decimal_not_float(tmp_path):
    loaded = read_quote_request(write(tmp_path, replaced("0.25", "0.1")))
    assert loaded.policy.margin_rate == Decimal("0.1")
    assert isinstance(loaded.policy.margin_rate, Decimal)


def test_whole_number_margin_is_accepted(tmp_path):
    loaded = read_quote_request(write(tmp_path, replaced("0.25", "1")))
    assert loaded.policy.margin_rate == Decimal(1)


def test_several_problems_are_reported_together(tmp_path):
    text = """\
client: ""
title: Trip
days: 0
travelers:
  adults: two
pricing:
  fx_rate: "3.5"
items:
  - id: van
    days: x
"""
    problems = problems_of(tmp_path, text)
    assert "client must be non-empty text" in problems
    assert "signed_by is required" in problems
    assert "travelers.adults must be a whole number" in problems
    assert "pricing.margin_rate is required" in problems
    assert "items[0].days must be a whole number" in problems


def test_required_keys_missing(tmp_path):
    problems = problems_of(tmp_path, "{}")
    for key in ("client", "title", "signed_by", "days", "travelers", "pricing", "items"):
        assert f"{key} is required" in problems


def test_nested_required_keys_missing(tmp_path):
    text = "client: A\ntitle: T\nsigned_by: S\ndays: 1\ntravelers: {}\npricing: {}\nitems: []\n"
    problems = problems_of(tmp_path, text)
    assert "travelers.adults is required" in problems
    assert "pricing.margin_rate is required" in problems


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("items:\n  - id: van\n", "items:\n  id: van\n", "items"),
        ("items:\n  - id: van\n", "items: van\n", "items"),
        ("items:\n  - id: van\n", "items: 3\n", "items"),
        ("items:\n  - id: van\n", "items: !!set {van}\n", "items"),
    ],
)
def test_items_must_be_a_list(tmp_path, old, new, field):
    assert f"{field} must be a list" in problems_of(tmp_path, replaced(old, new))


@pytest.mark.parametrize("value", ["{a: 1}", "text", "4", "!!set {a}"])
def test_other_collections_must_be_lists(tmp_path, value):
    for key in ("extras", "paid_locally"):
        assert f"{key} must be a list" in problems_of(tmp_path, MINIMAL + f"{key}: {value}\n")
    text = replaced("  adults: 2\n", f"  adults: 2\n  child_ages: {value}\n")
    assert "travelers.child_ages must be a list" in problems_of(tmp_path, text)


@pytest.mark.parametrize("value", ["{a: 1}", "text", "4"])
def test_extra_items_must_be_a_list(tmp_path, value):
    text = MINIMAL + f"extras:\n  - label: Ride\n    items: {value}\n"
    assert "extras[0].items must be a list" in problems_of(tmp_path, text)


def test_empty_paid_locally_values_that_are_not_lists_are_rejected(tmp_path):
    assert "paid_locally must be a list" in problems_of(tmp_path, MINIMAL + "paid_locally: {}\n")


def test_true_is_never_a_number(tmp_path):
    text = replaced("adults: 2", "adults: true").replace("days: 2", "days: true")
    text = text.replace("margin_rate: 0.25", "margin_rate: true")
    problems = problems_of(tmp_path, text)
    assert "travelers.adults must be a whole number" in problems
    assert "days must be a whole number" in problems
    assert "pricing.margin_rate must be a number" in problems


def test_bool_in_item_numbers_and_ages_is_rejected(tmp_path):
    text = replaced("  - id: van\n", "  - id: van\n    quantity: true\n")
    text = text.replace("  adults: 2\n", "  adults: 2\n  child_ages: [false]\n")
    problems = problems_of(tmp_path, text)
    assert "items[0].quantity must be a whole number" in problems
    assert "travelers.child_ages[0] must be a whole number" in problems


def test_datetime_is_not_a_date(tmp_path):
    problems = problems_of(tmp_path, MINIMAL + "date: 2026-10-14 10:30:00\n")
    assert "date must be a calendar date such as 2026-10-14" in problems


def test_text_is_not_a_date(tmp_path):
    assert any(p.startswith("date must") for p in problems_of(tmp_path, MINIMAL + "date: soon\n"))


def test_language_must_be_es_or_en(tmp_path):
    assert "language must be 'es' or 'en'" in problems_of(tmp_path, MINIMAL + "language: fr\n")
    assert read_quote_request(write(tmp_path, MINIMAL + "language: es\n")).language is (
        Language.SPANISH
    )


def test_unknown_keys_at_every_level(tmp_path):
    text = MINIMAL.replace("title: Trip", "titel: Trip\ntitle: Trip")
    text = text.replace("  adults: 2\n", "  adults: 2\n  kids: 1\n")
    text = text.replace("  margin_rate: 0.25\n", "  margin_rate: 0.25\n  margin: 1\n")
    text = text.replace("  - id: van\n", "  - id: van\n    qty: 2\n")
    text += "extras:\n  - label: R\n    colour: red\n    items:\n      - id: x\n        y: 1\n"
    problems = problems_of(tmp_path, text)
    assert "request file: unknown key 'titel'; did you mean 'title'?" in problems
    assert "travelers: unknown key 'kids'" in problems
    assert "pricing: unknown key 'margin'; did you mean 'margin_rate'?" in problems
    assert "items[0]: unknown key 'qty'" in problems
    assert "extras[0]: unknown key 'colour'" in problems
    assert "extras[0].items[0]: unknown key 'y'" in problems


def test_domain_errors_become_problems(tmp_path):
    text = replaced("adults: 2", "adults: 0").replace("0.25", "-1")
    text = text.replace("  - id: van\n", "  - id: van\n    days: 0\n")
    problems = problems_of(tmp_path, text)
    assert any(p.startswith("travelers:") for p in problems)
    assert any(p.startswith("pricing:") for p in problems)
    assert any(p.startswith("items[0]:") for p in problems)


def test_duplicate_paid_locally_ids_become_a_problem(tmp_path):
    problems = problems_of(tmp_path, MINIMAL + "paid_locally: [a, a]\n")
    assert any(p.startswith("request:") for p in problems)


def test_empty_items_list_is_rejected(tmp_path):
    problems = problems_of(tmp_path, replaced("items:\n  - id: van\n", "items: []\n"))
    assert any(p.startswith("request:") for p in problems)


def test_bad_numbers_never_echo_their_value(tmp_path):
    problems = problems_of(tmp_path, replaced("0.25", "banana7"))
    assert "pricing.margin_rate is not a valid number" in problems
    assert not any("banana7" in p for p in problems)


def test_problems_never_contain_the_margin(tmp_path):
    problems = problems_of(tmp_path, replaced("0.25", "-0.37").replace("days: 2", "days: x"))
    assert problems
    assert not any("0.37" in p for p in problems)


def test_missing_file_is_one_problem(tmp_path):
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(tmp_path / "nope.yaml")
    assert len(caught.value.problems) == 1
    assert "not found" in caught.value.problems[0]


def test_broken_yaml_is_one_problem_without_contents(tmp_path):
    text = "client: [unclosed secretword\n"
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(write(tmp_path, text))
    assert len(caught.value.problems) == 1
    assert "secretword" not in str(caught.value)


def test_unreadable_encoding_is_one_problem(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(path)
    assert len(caught.value.problems) == 1


@pytest.mark.parametrize("text", ["", "- a\n- b\n", "just text\n"])
def test_top_level_must_be_a_mapping(tmp_path, text):
    assert problems_of(tmp_path, text) == ("request file must be a mapping",)


def test_message_lists_every_problem(tmp_path):
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(write(tmp_path, "{}"))
    message = str(caught.value)
    assert all(problem in message for problem in caught.value.problems)
