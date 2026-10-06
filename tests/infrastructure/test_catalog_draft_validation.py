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
    draft["pricing_items"][0]["price_pen"] = 7391.46
    assert problems(draft) == ()


def test_validation_does_not_mutate_input():
    draft = valid_draft()
    snapshot = copy.deepcopy(draft)
    validate_draft(draft)
    assert draft == snapshot


def test_text_with_nul_or_control_characters_is_rejected_with_the_entry_id():
    for bad in ("a\x00b", "bell\x07", "esc\x1b[0m", "del\x7f", "c1\x85x", "lone\ud800"):
        for field in ("name_es", "name_en", "category", "notes"):
            found = problems(mutate(**{field: bad}))
            assert any("alpha-tour" in p and field in p for p in found), (field, bad)
    local = valid_draft()
    local["local_payments"][0]["name_en"] = "nul\x00"
    assert any("gamma-ticket" in p and "name_en" in p for p in problems(local))


def test_ordinary_text_with_newline_tab_and_unicode_is_accepted():
    assert problems(mutate(notes="line1\nline2\tñ 日本\r\n")) == ()


def test_duration_days_is_bounded_between_one_and_365():
    for ok in (1, 365, None):
        assert problems(mutate(unit="group", child_price_pen=None, duration_days=ok)) == ()
    for bad in (0, 366, 2**31, 10**40):
        found = problems(mutate(unit="group", child_price_pen=None, duration_days=bad))
        assert any("alpha-tour" in p and "duration_days" in p for p in found), bad


def test_oversized_and_over_precise_prices_are_listed_with_the_entry_id():
    for bad in ("100000000.00", "1e30", 1e30, "0.001", "7391.456"):
        found = problems(mutate(price_pen=bad))
        assert any("alpha-tour" in p and "price_pen" in p for p in found), bad
    assert problems(mutate(price_pen="99999999.99")) == ()


def test_slug_with_trailing_newline_is_rejected_and_duplicates_still_detected():
    assert any("id must be" in p for p in problems(mutate(id="alpha-tour\n")))
    draft = valid_draft()
    draft["pricing_items"][1]["id"] = "alpha-tour"
    found = problems(draft)
    assert sum("duplicate" in p for p in found) == 1


def test_unknown_keys_are_reported_with_location_and_a_hint():
    typo = problems(mutate(child_price_pn="1.00"))
    assert any("alpha-tour" in p and "child_price_pn" in p and "child_price_pen" in p for p in typo)
    top = valid_draft()
    top["pricing_item"] = []
    assert any("pricing_item" in p and "pricing_items" in p for p in problems(top))
    local = valid_draft()
    local["local_payments"][0]["nmae_en"] = "x"
    assert any("gamma-ticket" in p and "nmae_en" in p for p in problems(local))
    far = problems(mutate(zzz_unrelated=1))
    assert any("zzz_unrelated" in p for p in far)
    assert not any("did you mean" in p for p in far)


def test_keys_written_by_the_tool_remain_allowed():
    draft = valid_draft()
    draft["pricing_items"][0].update(source_name="S", needs_review=False, review_hint="h")
    draft["local_payments"][0].update(source_name="S", review_hint="h")
    assert problems(draft) == ()
