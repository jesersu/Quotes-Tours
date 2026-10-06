from decimal import Decimal

import pytest

from quotes.infrastructure.catalog_draft import validate_draft
from quotes.infrastructure.catalog_sql import (
    SqlLiteralError,
    quote_bool,
    quote_decimal,
    quote_enum,
    quote_int,
    quote_text,
    render_sql,
)
from tests.support.draft_fixture import NASTY, valid_draft


@pytest.mark.parametrize(
    ("raw", "quoted"),
    [
        ("plain", "'plain'"),
        ("O'Brien", "'O''Brien'"),
        ("''", "''''''"),
        ("back\\slash", "'back\\slash'"),
        ("a; drop table x; --", "'a; drop table x; --'"),
        ("line1\nline2", "'line1\nline2'"),
        ("ñ日本", "'ñ日本'"),
        ("100% %s", "'100% %s'"),
        ("", "''"),
    ],
)
def test_quote_text(raw, quoted):
    assert quote_text(raw) == quoted


def test_quote_text_rejects_nul_and_non_text():
    with pytest.raises(SqlLiteralError):
        quote_text("a\x00b")
    with pytest.raises(SqlLiteralError):
        quote_text(5)  # type: ignore[arg-type]


def test_quote_text_cannot_be_broken_out_of():
    quoted = quote_text(NASTY)
    inner = quoted[1:-1].replace("''", "")
    assert "'" not in inner  # every quote in the payload is doubled


def test_quote_decimal_two_places_only():
    assert quote_decimal(Decimal("12.3")) == "12.30"
    assert quote_decimal(Decimal("0")) == "0.00"
    for bad in (Decimal("-1.00"), Decimal("1.234"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(SqlLiteralError):
            quote_decimal(bad)
    with pytest.raises(SqlLiteralError):
        quote_decimal(Decimal("100000000.00"))
    with pytest.raises(SqlLiteralError):
        quote_decimal("1; drop")  # type: ignore[arg-type]
    with pytest.raises(SqlLiteralError):
        quote_decimal(1.5)  # type: ignore[arg-type]


def test_quote_int_bool_enum():
    assert quote_int(3) == "3"
    for bad in (0, -1, True, "1", 2**31):
        with pytest.raises(SqlLiteralError):
            quote_int(bad)  # type: ignore[arg-type]
    assert (quote_bool(True), quote_bool(False)) == ("true", "false")
    with pytest.raises(SqlLiteralError):
        quote_bool("true")  # type: ignore[arg-type]
    assert quote_enum("group", ("group", "day")) == "'group'"
    for bad in ("Group", "group'; --", None):
        with pytest.raises(SqlLiteralError):
            quote_enum(bad, ("group", "day"))  # type: ignore[arg-type]


def render(draft=None):
    result = validate_draft(draft if draft is not None else valid_draft())
    assert not result.problems, result.problems
    return render_sql(result)


def test_script_is_a_transaction_of_upserts_without_deletes_or_ddl():
    sql = render()
    lowered = sql.lower()
    assert sql.index("begin;") < sql.index("commit;")
    assert "on conflict (id) do update set" in lowered
    assert "on conflict (item_id, visitor_category) do update set" in lowered
    for forbidden in ("delete ", "drop ", "truncate", "create ", "alter "):
        # the adversarial name carries a "drop table": it must only appear inside a literal
        assert forbidden not in lowered.replace(quote_text(NASTY).lower(), "")
    assert "standard_conforming_strings = on" in lowered
    for table in ("pricing_items", "local_payment_items", "local_payment_prices"):
        assert f"insert into quotes.{table}" in lowered


def test_literals_and_header_and_verification_query():
    sql = render()
    assert quote_text(NASTY) in sql
    assert "'alpha-tour'" in sql and "310.00" in sql and "55.50" in sql
    assert sql.startswith("-- ")
    assert "do not commit" in sql.splitlines()[1].lower() or "do not commit" in sql[:400].lower()
    assert "SQL Editor" in sql[:600]
    assert "-- select" in sql  # trailing commented verification query
    # no draft text may leak into a comment line (comment injection)
    comments = [ln for ln in sql.splitlines() if ln.startswith("--")]
    assert not any("alpha" in c.lower() or "O'Brien" in c for c in comments)


def test_render_is_deterministic():
    assert render() == render()
