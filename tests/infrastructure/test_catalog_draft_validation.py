import copy

from quotes.infrastructure.catalog_draft import dump_draft, load_draft, validate_draft
from tests.support.draft_fixture import mutate, valid_draft


def problems(draft):
    return validate_draft(draft).problems


def test_valid_draft_has_no_problems_and_yields_rows():
    result = validate_draft(valid_draft())
    assert result.problems == ()
    assert [r["id"] for r in result.item_rows] == ["alpha-tour", "beta-transport-2-days"]
    assert len(result.local_rows) == 1 and len(result.price_rows) == 3


def test_survives_yaml_round_trip():
    again = load_draft(dump_draft(valid_draft()))
    assert validate_draft(again).problems == ()


def test_needs_review_blocks_and_names_the_entry():
    found = problems(mutate(needs_review=True))
    assert any("alpha-tour" in p and "needs_review" in p for p in found)


def test_needs_review_missing_or_not_bool_is_a_problem():
    draft = valid_draft()
    del draft["pricing_items"][0]["needs_review"]
    assert any("needs_review" in p for p in problems(draft))
    assert any("needs_review" in p for p in problems(mutate(needs_review="false")))


def test_local_payment_needs_review_and_null_prices_block():
    draft = valid_draft()
    draft["local_payments"][0]["needs_review"] = True
    draft["local_payments"][0]["prices"]["child_6_15"] = None
    found = problems(draft)
    assert any("gamma-ticket" in p and "needs_review" in p for p in found)
    assert any("gamma-ticket" in p and "child_6_15" in p and "null" in p for p in found)


def test_invalid_values_are_listed_with_entry_ids():
    cases = {
        "price_pen": ["-1", "abc", "1.234", "NaN", None, True, "1" + "0" * 9],
        "unit": ["weekly", None, 3],
        "id": ["Bad Id", "UPPER", "a--b", "", None, "-x"],
        "name_en": ["  ", None, 5],
        "category": ["", None],
        "duration_days": [0, -2, "2", True, 1.5],
        "active": ["yes", None],
        "child_price_pen": ["x", "-1"],
    }
    for field, values in cases.items():
        for value in values:
            assert problems(mutate(**{field: value})), (field, value)


def test_child_price_on_non_person_unit_is_rejected_by_the_shared_mapper():
    found = problems(mutate(unit="group"))
    assert any("child_price_pen" in p for p in found)


def test_duplicate_ids_are_reported_not_raised():
    draft = valid_draft()
    draft["pricing_items"][1]["id"] = "alpha-tour"
    assert any("duplicate" in p.lower() and "alpha-tour" in p for p in problems(draft))


def test_structure_errors():
    assert problems("not a mapping")
    assert problems(None)
    assert problems({"pricing_items": "x", "local_payments": []})
    assert problems({"pricing_items": [], "local_payments": []})  # nothing to import
    bad = valid_draft()
    bad["pricing_items"][0] = "oops"
    assert any("pricing_items[0]" in p for p in problems(bad))
    unknown = valid_draft()
    unknown["local_payments"][0]["prices"]["senior"] = "1.00"
    assert any("senior" in p for p in problems(unknown))


def test_unquoted_yaml_numbers_are_accepted_when_exact():
    draft = valid_draft()
    draft["pricing_items"][0]["price_pen"] = 12.34
    assert problems(draft) == ()


def test_validation_does_not_mutate_input():
    draft = valid_draft()
    snapshot = copy.deepcopy(draft)
    validate_draft(draft)
    assert draft == snapshot
