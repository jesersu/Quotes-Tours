import io

import yaml

from quotes.cli import main
from quotes.infrastructure.catalog_draft import dump_draft
from tests.support.draft_fixture import mutate, valid_draft


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    return main(argv, out=out, err=err), out.getvalue(), err.getvalue()


def write(path, draft):
    path.write_text(dump_draft(draft), encoding="utf-8")
    return path


def test_sql_writes_file_and_prints_counts_only(tmp_path):
    src, dest = write(tmp_path / "d.yaml", valid_draft()), tmp_path / "o" / "import.sql"
    code, out, err = run(["catalog", "sql", str(src), "-o", str(dest)])
    assert code == 0, err
    assert "pricing items: 2" in out and "local payment items: 1" in out
    assert "local payment prices: 3" in out and str(dest) in out
    assert dest.read_text(encoding="utf-8").lstrip().startswith("--")
    for price in ("12.34", "310", "55.5", "7.50"):
        assert price not in out + err


def test_sql_refuses_while_needs_review_and_writes_nothing(tmp_path):
    src = write(tmp_path / "d.yaml", mutate(needs_review=True))
    dest = tmp_path / "import.sql"
    code, out, err = run(["catalog", "sql", str(src), "-o", str(dest)])
    assert code == 1
    assert "alpha-tour" in err and "needs_review" in err
    assert not dest.exists()
    assert "12.34" not in out + err


def test_sql_refuses_null_local_price_and_invalid_value(tmp_path):
    draft = valid_draft()
    draft["local_payments"][0]["prices"]["foreign_adult"] = None
    draft["pricing_items"][1]["unit"] = "weekly"
    code, _, err = run(
        ["catalog", "sql", str(write(tmp_path / "d.yaml", draft)), "-o", str(tmp_path / "o.sql")]
    )
    assert code == 1 and "foreign_adult" in err and "weekly" in err


def test_sql_overwrite_requires_force(tmp_path):
    src, dest = write(tmp_path / "d.yaml", valid_draft()), tmp_path / "o.sql"
    assert run(["catalog", "sql", str(src), "-o", str(dest)])[0] == 0
    code, _, err = run(["catalog", "sql", str(src), "-o", str(dest)])
    assert code == 2 and "--force" in err
    assert run(["catalog", "sql", str(src), "-o", str(dest), "--force"])[0] == 0


def test_sql_missing_or_malformed_draft_exits_two(tmp_path):
    code, _, err = run(["catalog", "sql", str(tmp_path / "none.yaml")])
    assert code == 2 and "not found" in err
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed", encoding="utf-8")
    code, _, err = run(["catalog", "sql", str(bad), "-o", str(tmp_path / "o.sql")])
    assert code == 2 and "YAML" in err


def test_python_tags_in_a_draft_are_refused(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("pricing_items: !!python/object/apply:os.system ['echo hi']\n", encoding="utf-8")
    code, _, _ = run(["catalog", "sql", str(bad), "-o", str(tmp_path / "o.sql")])
    assert code == 2
    assert yaml.safe_load("a: 1") == {"a": 1}
