import io

import openpyxl

from quotes.cli import main


def workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PRECIOS GENERAL"
    ws["C3"], ws["D3"] = "NOMBRE", "PRECIO( SOLES)"
    for i, (name, price) in enumerate(
        [
            ("TICKETS  INGRESO COLCA", 310.25),
            ("GUIA OFICIAL  CITY TOUR", 55.5),
            (None, None),
            ("DESAYUNO COLCA BUFFET", 12.34),
        ],
        start=4,
    ):
        ws.cell(row=i, column=3, value=name)
        ws.cell(row=i, column=4, value=price)
    wb.save(path)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    return main(argv, out=out, err=err), out.getvalue(), err.getvalue()


def test_draft_writes_file_and_prints_counts_but_no_prices(tmp_path):
    src, dest = tmp_path / "w.xlsx", tmp_path / "d" / "draft.yaml"
    workbook(src)
    code, out, err = run(["catalog", "draft", str(src), "-o", str(dest)])
    assert code == 0, err
    assert dest.exists()
    assert "pricing items: 2" in out and "local payments: 1" in out
    assert str(dest) in out
    for price in ("310", "55.5", "12.34"):
        assert price not in out + err


def test_draft_refuses_overwrite_unless_forced(tmp_path):
    src, dest = tmp_path / "w.xlsx", tmp_path / "draft.yaml"
    workbook(src)
    assert run(["catalog", "draft", str(src), "-o", str(dest)])[0] == 0
    code, _, err = run(["catalog", "draft", str(src), "-o", str(dest)])
    assert code == 2 and "--force" in err
    assert run(["catalog", "draft", str(src), "-o", str(dest), "--force"])[0] == 0


def test_draft_missing_file_and_sheet_exit_two(tmp_path):
    code, _, err = run(["catalog", "draft", str(tmp_path / "x.xlsx"), "-o", str(tmp_path / "o")])
    assert code == 2 and "not found" in err
    src = tmp_path / "w.xlsx"
    workbook(src)
    code, _, err = run(["catalog", "draft", str(src), "--sheet", "NOPE", "-o", str(tmp_path / "o")])
    assert code == 2 and "NOPE" in err
