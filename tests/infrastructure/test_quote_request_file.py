from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from quotes.application.quote import (
    ItineraryDay,
    QuoteOption,
    QuoteRequest,
    RequestedExtra,
    RequestedItem,
)
from quotes.application.quote_rendering import Language
from quotes.domain.travelers import Travelers
from quotes.infrastructure.quote_request_file import (
    HEADER,
    InvalidRequestFile,
    RequestNeedsReview,
    _NoFloatLoader,
    dump_quote_request,
    parse_quote_request,
    read_quote_request,
)

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
            RequestedItem("guide", days=1, on_days=(1,)),
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
    assert "pricing.margin_rate: set the margin for this quote" in problems
    assert "items[0].days must be a whole number" in problems


def test_required_keys_missing(tmp_path):
    problems = problems_of(tmp_path, "{}")
    for key in ("client", "title", "signed_by", "days", "travelers", "pricing", "items"):
        assert f"{key} is required" in problems


def test_nested_required_keys_missing(tmp_path):
    text = "client: A\ntitle: T\nsigned_by: S\ndays: 1\ntravelers: {}\npricing: {}\nitems: []\n"
    problems = problems_of(tmp_path, text)
    assert "travelers.adults is required" in problems
    assert "pricing.margin_rate: set the margin for this quote" in problems


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


# --- several options ---

OPTIONS = """\
client: Ana
title: Trip
signed_by: Team
days: 2
travelers:
  adults: 2
pricing:
  margin_rate: 0.25
paid_locally: [ticket]
options:
  - label: Option 1
    subtitle: Ends in Puno
    items:
      - id: van
    extras:
      - label: Horse
        items:
          - id: horse
  - label: Option 2
    days: 3
    items:
      - id: van
      - id: hotel
"""


def test_options_are_read_with_shared_travelers_and_paid_locally(tmp_path):
    loaded = read_quote_request(write(tmp_path, OPTIONS))

    first, second = loaded.options
    assert (first.label, first.subtitle) == ("Option 1", "Ends in Puno")
    assert (second.label, second.subtitle) == ("Option 2", None)
    assert first.request == QuoteRequest(
        2,
        Travelers(2),
        (RequestedItem("van"),),
        (RequestedExtra("Horse", (RequestedItem("horse"),)),),
        ("ticket",),
    )
    assert second.request.days == 3
    assert second.request.travelers == first.request.travelers
    assert second.request.paid_locally == ("ticket",)
    assert second.request.extras == ()


def test_the_top_level_format_is_one_unlabeled_option(tmp_path):
    loaded = read_quote_request(write(tmp_path, MINIMAL))

    (only,) = loaded.options
    assert (only.label, only.subtitle) == (None, None)
    assert only.request == loaded.request


def test_request_is_only_available_for_a_single_option(tmp_path):
    loaded = read_quote_request(write(tmp_path, OPTIONS))

    with pytest.raises(ValueError, match="options"):
        loaded.request  # noqa: B018


def test_every_option_may_carry_its_own_days_without_a_default(tmp_path):
    text = OPTIONS.replace("days: 2\n", "").replace("    subtitle", "    days: 1\n    subtitle")

    loaded = read_quote_request(write(tmp_path, text))

    assert [o.request.days for o in loaded.options] == [1, 3]


def test_days_are_required_when_an_option_has_none(tmp_path):
    text = OPTIONS.replace("days: 2\n", "", 1)

    assert "days is required" in problems_of(tmp_path, text)


def test_options_and_top_level_items_are_mutually_exclusive(tmp_path):
    problems = problems_of(tmp_path, OPTIONS + "items:\n  - id: van\n")

    assert any("options" in p and "items" in p for p in problems)


def test_options_and_top_level_extras_are_mutually_exclusive(tmp_path):
    problems = problems_of(
        tmp_path, OPTIONS + "extras:\n  - label: X\n    items:\n      - id: horse\n"
    )

    assert any("options" in p and "extras" in p for p in problems)


def test_neither_items_nor_options_is_a_problem(tmp_path):
    text = MINIMAL.replace("items:\n  - id: van\n", "")

    problems = problems_of(tmp_path, text)

    assert "items is required" in problems
    assert any("options" in p and "items" in p for p in problems)


def test_options_must_be_a_non_empty_list(tmp_path):
    base = MINIMAL.replace("items:\n  - id: van\n", "")

    assert "options must be a list" in problems_of(tmp_path, base + "options: nope\n")
    assert "options needs at least one option" in problems_of(tmp_path, base + "options: []\n")


def test_option_labels_must_be_present_non_empty_and_unique(tmp_path):
    text = OPTIONS.replace("label: Option 2", "label: ' Option 1 '")
    assert any("options[1].label" in p and "unique" in p for p in problems_of(tmp_path, text))

    text = OPTIONS.replace("label: Option 2", "label: '  '")
    assert "options[1].label must be non-empty text" in problems_of(tmp_path, text)

    text = OPTIONS.replace("  - label: Option 2\n", "  - days: 3\n")
    assert "options[1].label is required" in problems_of(tmp_path, text)


def test_option_problems_are_reported_together_with_their_paths(tmp_path):
    text = (
        OPTIONS.replace("days: 3", "days: many")
        .replace("subtitle: Ends in Puno", "subtitle: 5\n    colour: red")
        .replace("      - id: hotel\n", "      - quantity: 2\n")
    )

    problems = problems_of(tmp_path, text)

    assert "options[1].days must be a whole number" in problems
    assert "options[0].subtitle must be non-empty text" in problems
    assert any("options[0]: unknown key 'colour'" in p for p in problems)
    assert "options[1].items[1].id is required" in problems


def test_option_extras_use_their_own_path(tmp_path):
    text = OPTIONS.replace("- label: Horse", "- name: Horse")

    problems = problems_of(tmp_path, text)

    assert any(p.startswith("options[0].extras[0]") for p in problems)


def test_an_unknown_option_key_gets_a_hint(tmp_path):
    problems = problems_of(tmp_path, OPTIONS.replace("subtitle:", "subtile:"))

    assert any("unknown key 'subtile'" in p and "did you mean 'subtitle'" in p for p in problems)


def test_option_values_are_never_echoed(tmp_path):
    text = OPTIONS.replace("margin_rate: 0.25", "margin_rate: 7.31x")

    problems = problems_of(tmp_path, text)

    assert problems
    assert all("7.31" not in p for p in problems)


def test_the_example_file_documents_options_as_a_comment():
    text = EXAMPLE.read_text(encoding="utf-8")

    assert "options:" in text
    assert isinstance(read_quote_request(EXAMPLE).options[0], QuoteOption)


# --- items assigned to days ---

PLACED = """\
client: Ana
title: Trip
signed_by: Team
days: 3
travelers:
  adults: 2
pricing:
  margin_rate: 0.25
itinerary:
  - day: 1
    title: Arequipa - Chivay
  - day: 3
    title: Back to Arequipa
items:
  - id: van
    on_days: [2, 1]
  - id: hotel
extras:
  - label: Horse
    items:
      - id: horse
"""

PLACED_OPTIONS = """\
client: Ana
title: Trip
signed_by: Team
days: 3
travelers:
  adults: 2
pricing:
  margin_rate: 0.25
options:
  - label: Option 1
    itinerary:
      - day: 2
        title: Chivay
    items:
      - id: van
      - id: hotel
        on_days: [1, 3]
  - label: Option 2
    days: 2
    items:
      - id: van
"""


def test_a_plain_request_reads_on_days_and_the_itinerary(tmp_path):
    (only,) = read_quote_request(write(tmp_path, PLACED)).options

    assert only.request.items[0] == RequestedItem("van", on_days=(1, 2))
    assert only.request.items[1].on_days == ()
    assert only.itinerary == (
        ItineraryDay(1, "Arequipa - Chivay"),
        ItineraryDay(3, "Back to Arequipa"),
    )


def test_an_options_request_reads_on_days_and_the_itinerary_per_option(tmp_path):
    first, second = read_quote_request(write(tmp_path, PLACED_OPTIONS)).options

    assert first.request.items[1].on_days == (1, 3)
    assert first.itinerary == (ItineraryDay(2, "Chivay"),)
    assert second.itinerary == ()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("[0]", "items[0].on_days[0] must be at least 1"),
        ("[4]", "items[0].on_days[0] must not exceed the 3 days of the quote"),
        ("[1, 1]", "items[0].on_days must not repeat day 1"),
        ("[1.5]", "items[0].on_days[0] must be a whole number"),
        ("[true]", "items[0].on_days[0] must be a whole number"),
        ("2", "items[0].on_days must be a list"),
    ],
)
def test_invalid_on_days_are_reported_with_their_path(tmp_path, value, message):
    text = PLACED.replace("[2, 1]", value)

    assert message in problems_of(tmp_path, text)


def test_on_days_problems_in_an_option_use_the_option_path(tmp_path):
    text = PLACED_OPTIONS.replace("[1, 3]", "[1, 3, 3]")

    assert "options[0].items[1].on_days must not repeat day 3" in problems_of(tmp_path, text)


def test_on_days_are_checked_against_the_days_of_their_own_option(tmp_path):
    # The last item belongs to Option 2, which has 2 days while the request default is 3.
    problems = problems_of(tmp_path, PLACED_OPTIONS + "        on_days: [3]\n")

    assert "options[1].items[0].on_days[0] must not exceed the 2 days of the quote" in problems


def test_on_days_are_not_allowed_on_extra_items(tmp_path):
    text = PLACED.replace("      - id: horse\n", "      - id: horse\n        on_days: [1]\n")

    assert "extras[0].items[0].on_days is not allowed on optional extras" in problems_of(
        tmp_path, text
    )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("day: 1\n", "day: 0\n", "itinerary[0].day must be at least 1"),
        ("day: 3\n", "day: 4\n", "itinerary[1].day must not exceed the 3 days of the quote"),
        ("day: 3\n", "day: 1\n", "itinerary[1].day repeats itinerary[0].day"),
        ("day: 1\n", "day: one\n", "itinerary[0].day must be a whole number"),
        ("title: Back to Arequipa", "title: ''", "itinerary[1].title must be non-empty text"),
    ],
)
def test_itinerary_problems_are_reported_with_their_path(tmp_path, old, new, message):
    assert message in problems_of(tmp_path, PLACED.replace(old, new))


def test_an_unknown_itinerary_key_gets_a_hint(tmp_path):
    problems = problems_of(tmp_path, PLACED.replace("title: Arequipa", "titel: Arequipa"))

    assert any(
        "itinerary[0]: unknown key 'titel'" in p and "did you mean 'title'" in p for p in problems
    )


def test_the_itinerary_must_be_a_list(tmp_path):
    head, _, tail = PLACED.partition("itinerary:\n")
    text = head + "itinerary: soon\n" + tail[tail.index("items:") :]

    assert "itinerary must be a list" in problems_of(tmp_path, text)


def test_an_option_itinerary_uses_the_option_path(tmp_path):
    text = PLACED_OPTIONS.replace("day: 2\n", "day: 5\n")

    assert "options[0].itinerary[0].day must not exceed the 3 days of the quote" in problems_of(
        tmp_path, text
    )


def test_options_cannot_be_combined_with_a_top_level_itinerary(tmp_path):
    text = PLACED_OPTIONS.replace(
        "options:\n", "itinerary:\n  - day: 1\n    title: X\noptions:\n", 1
    )

    problems = problems_of(tmp_path, text)

    assert any("top-level" in p and "itinerary" in p for p in problems)


def test_the_example_file_shows_on_days_and_an_itinerary():
    (only,) = read_quote_request(EXAMPLE).options

    assert any(item.on_days for item in only.request.items)
    assert only.itinerary


# --- parsing loaded data, and the review gate ---

DRAFT = {
    "client": "Ana",
    "title": "Trip",
    "signed_by": "Team",
    "days": 3,
    "travelers": {"adults": 2, "child_ages": [8]},
    "pricing": {"margin_rate": "0.25", "fx_rate": "3.5", "usd_rounding_step": "5"},
    "paid_locally": ["ticket"],
    "options": [
        {
            "label": "Option 1",
            "subtitle": "Ends in Puno",
            "items": [{"id": "van"}, {"id": "guide", "days": 1, "on_days": [1, 2]}],
            "extras": [{"label": "Horse", "items": [{"id": "horse"}]}],
            "itinerary": [{"day": 1, "title": "Arrival"}, {"day": 2, "title": "Canyon"}],
        },
        {"label": "Option 2", "days": 2, "items": [{"id": "van", "quantity": 2}]},
    ],
    "needs_review": False,
}


def test_parse_from_data_equals_read_from_file(tmp_path):
    assert parse_quote_request(yaml.load(MINIMAL, _NoFloatLoader)) == read_quote_request(
        write(tmp_path, MINIMAL)
    )


def test_parse_reports_the_same_problems_as_the_file_reader(tmp_path):
    with pytest.raises(InvalidRequestFile) as caught:
        parse_quote_request({"client": "A", "items": "van"})
    assert "items must be a list" in caught.value.problems
    assert "title is required" in caught.value.problems


def test_parse_rejects_data_that_is_not_a_mapping():
    with pytest.raises(InvalidRequestFile) as caught:
        parse_quote_request(["x"])
    assert caught.value.problems == ("request file must be a mapping",)


def test_needs_review_true_raises_with_the_hints():
    data = {"needs_review": True, "review_hints": ["Check the hotel", "Confirm ages"]}
    with pytest.raises(RequestNeedsReview) as caught:
        parse_quote_request(data)
    assert caught.value.hints == ("Check the hotel", "Confirm ages")
    assert not isinstance(caught.value, InvalidRequestFile)


def test_needs_review_true_is_reported_alone_even_if_the_rest_is_broken():
    with pytest.raises(RequestNeedsReview) as caught:
        parse_quote_request({"needs_review": True})
    assert caught.value.hints == ()


def test_needs_review_true_from_a_file_raises(tmp_path):
    with pytest.raises(RequestNeedsReview):
        read_quote_request(write(tmp_path, MINIMAL + "needs_review: true\n"))


@pytest.mark.parametrize("flag", ["false", ""])
def test_needs_review_false_or_absent_parses_normally(tmp_path, flag):
    text = MINIMAL + (f"needs_review: {flag}\n" if flag else "")
    assert read_quote_request(write(tmp_path, text)).request.days == 2


@pytest.mark.parametrize("flag", ['"yes"', "1", "null_text", "[true]"])
def test_needs_review_must_be_a_bool(tmp_path, flag):
    assert "needs_review must be true or false" in problems_of(
        tmp_path, MINIMAL + f"needs_review: {flag}\n"
    )


def test_a_non_bool_flag_is_not_mistaken_for_the_gate(tmp_path):
    with pytest.raises(InvalidRequestFile):
        read_quote_request(write(tmp_path, MINIMAL + "needs_review: 'true'\n"))


@pytest.mark.parametrize(
    ("hints", "message"),
    [
        ("x", "review_hints must be a list"),
        ("[a, '']", "review_hints[1] must be non-empty text"),
        ("[3]", "review_hints[0] must be non-empty text"),
    ],
)
def test_bad_review_hints_are_problems(tmp_path, hints, message):
    assert message in problems_of(tmp_path, MINIMAL + f"review_hints: {hints}\n")


def test_hints_are_ignored_when_the_request_is_reviewed(tmp_path):
    text = MINIMAL + "needs_review: false\nreview_hints: [Check the dates]\n"
    assert read_quote_request(write(tmp_path, text)).request.days == 2


@pytest.mark.parametrize(
    "pricing", ["pricing:\n  margin_rate: null\n", "pricing:\n  fx_rate: '3'\n"]
)
def test_a_missing_or_null_margin_asks_the_owner_to_set_it(tmp_path, pricing):
    text = MINIMAL.replace("pricing:\n  margin_rate: 0.25\n", pricing)
    assert "pricing.margin_rate: set the margin for this quote" in problems_of(tmp_path, text)


# --- writing a draft ---


def test_dump_starts_with_the_header_and_lists_the_review_steps():
    text = dump_quote_request(DRAFT)
    assert text.startswith(HEADER)
    assert text.startswith("# Draft quote request written by the planner")
    for word in ("services", "travelers", "margin", "review_hints", "needs_review: false"):
        assert word in HEADER


def test_dump_quotes_money_and_never_emits_a_float():
    text = dump_quote_request(
        {**DRAFT, "pricing": {"margin_rate": "0.25", "fx_rate": Decimal("3.5")}}
    )
    body = yaml.safe_load(text)
    assert body["pricing"] == {"margin_rate": "0.25", "fx_rate": "3.5"}
    assert 'margin_rate: "0.25"' in text or "margin_rate: '0.25'" in text


def test_dump_keeps_an_unset_margin_null():
    text = dump_quote_request({"pricing": {"margin_rate": None}})
    assert yaml.safe_load(text)["pricing"] == {"margin_rate": None}


@pytest.mark.parametrize(
    "data",
    [
        {"pricing": {"margin_rate": 0.25}},
        {"travelers": {"adults": 2.0}},
        {"options": [{"items": [{"id": "van", "quantity": 1.5}]}]},
    ],
)
def test_dump_refuses_a_float_anywhere(data):
    with pytest.raises(ValueError, match="float"):
        dump_quote_request(data)


def test_a_draft_round_trips_through_dump_and_the_no_float_loader():
    loaded = yaml.load(dump_quote_request(DRAFT), _NoFloatLoader)
    assert parse_quote_request(loaded) == parse_quote_request(DRAFT)
    assert len(parse_quote_request(loaded).options) == 2


def test_a_dumped_draft_marked_for_review_is_refused():
    draft = {**DRAFT, "needs_review": True, "review_hints": ["Check the hotel"]}
    loaded = yaml.load(dump_quote_request(draft), _NoFloatLoader)
    with pytest.raises(RequestNeedsReview) as caught:
        parse_quote_request(loaded)
    assert caught.value.hints == ("Check the hotel",)


DAY_TEXT = PLACED.replace(
    "    title: Arequipa - Chivay\n", "    title: Arequipa - Chivay\n    text: A calm first day.\n"
)


def test_an_itinerary_entry_may_carry_a_text(tmp_path):
    (only,) = read_quote_request(write(tmp_path, DAY_TEXT)).options
    assert only.itinerary[0] == ItineraryDay(1, "Arequipa - Chivay", "A calm first day.")
    assert only.itinerary[1].text is None


@pytest.mark.parametrize("value", ['""', '"   "', "5"])
def test_a_blank_or_non_text_day_text_is_refused_with_its_path(tmp_path, value):
    content = DAY_TEXT.replace("A calm first day.", value)
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(write(tmp_path, content))
    assert "itinerary[0].text must be non-empty text" in caught.value.problems


def test_an_unknown_itinerary_key_is_still_refused(tmp_path):
    content = DAY_TEXT.replace("text: A calm", "notes: A calm")
    with pytest.raises(InvalidRequestFile) as caught:
        read_quote_request(write(tmp_path, content))
    assert any("notes" in problem for problem in caught.value.problems)


def test_day_text_round_trips_through_dump(tmp_path):
    loaded = yaml.load(DAY_TEXT, _NoFloatLoader)
    again = yaml.load(dump_quote_request(loaded), _NoFloatLoader)
    assert parse_quote_request(again) == parse_quote_request(loaded)
    assert again["itinerary"][0]["text"] == "A calm first day."
