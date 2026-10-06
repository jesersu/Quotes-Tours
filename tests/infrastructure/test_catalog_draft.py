import pytest
import yaml

from quotes.infrastructure.catalog_draft import OutputExists, dump_draft, write_new_file

DRAFT = {
    "pricing_items": [
        {
            "id": "a-b",
            "name_es": "Campiña tour",
            "name_en": 'It\'s "quoted": yes',
            "price_pen": "7391.46",
            "child_price_pen": None,
            "active": True,
            "needs_review": True,
        }
    ],
    "local_payments": [],
}


def test_round_trips_through_safe_load_preserving_unicode_and_strings():
    text = dump_draft(DRAFT)
    assert "Campiña" in text
    assert yaml.safe_load(text) == DRAFT
    assert "!!python" not in text


def test_header_comment_explains_review():
    text = dump_draft(DRAFT)
    header = text.split("\n\n")[0]
    assert header.startswith("#")
    assert "needs_review" in header


def test_key_order_is_stable():
    text = dump_draft(DRAFT)
    assert text.index("id:") < text.index("name_es:") < text.index("price_pen:")


def test_write_refuses_to_overwrite_without_force(tmp_path):
    target = tmp_path / "sub" / "out.yaml"
    write_new_file(target, "one", force=False)
    with pytest.raises(OutputExists):
        write_new_file(target, "two", force=False)
    assert target.read_text() == "one"
    write_new_file(target, "two", force=True)
    assert target.read_text() == "two"
