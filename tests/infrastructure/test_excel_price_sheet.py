import zipfile
from pathlib import Path

import openpyxl
import pytest

from quotes.infrastructure.excel_price_sheet import SheetError, _price, read_price_rows


def workbook(path: Path, data_rows, sheet="PRECIOS GENERAL", header_row=3, extra_empty=0):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.cell(row=1, column=3, value="LISTA")
    ws.cell(row=header_row, column=2, value="ITEM")
    ws.cell(row=header_row, column=3, value="NOMBRE")
    ws.cell(row=header_row, column=4, value="PRECIO( SOLES)")
    for offset, (name, price) in enumerate(data_rows, start=1):
        ws.cell(row=header_row + offset, column=3, value=name)
        ws.cell(row=header_row + offset, column=4, value=price)
    last = header_row + len(data_rows) + extra_empty
    for r in range(header_row + len(data_rows) + 1, last + 1):
        ws.cell(row=r, column=3).number_format = "General"  # formatted but empty
    wb.save(path)
    return path


def test_reads_rows_skips_blank_separators_and_trailing_empties(tmp_path):
    path = workbook(
        tmp_path / "w.xlsx",
        [("  TICKETS  CITY TOUR ", 7391.46), (None, None), ("GUIA OFICIAL X", 5528.5)],
        extra_empty=500,
    )
    result = read_price_rows(path)
    assert [(r.name, str(r.price), r.row) for r in result.rows] == [
        ("TICKETS CITY TOUR", "7391.46", 4),
        ("GUIA OFICIAL X", "5528.50", 6),
    ]
    assert result.skipped_rows == ()


def test_rows_without_a_usable_price_are_skipped_and_reported(tmp_path):
    path = workbook(
        tmp_path / "w.xlsx", [("A", None), ("B", "n/a"), (None, 5), ("C", -1), ("D", 3)]
    )
    result = read_price_rows(path)
    assert [r.name for r in result.rows] == ["D"]
    assert result.skipped_rows == (4, 5, 6, 7)


def test_header_is_located_even_when_not_on_row_three(tmp_path):
    path = workbook(tmp_path / "w.xlsx", [("A", 1.5)], header_row=5)
    assert [r.row for r in read_price_rows(path).rows] == [6]


def test_custom_sheet_name(tmp_path):
    path = workbook(tmp_path / "w.xlsx", [("A", 1.5)], sheet="OTRA")
    assert len(read_price_rows(path, "OTRA").rows) == 1


def test_missing_file(tmp_path):
    with pytest.raises(SheetError, match="not found"):
        read_price_rows(tmp_path / "nope.xlsx")


def test_not_a_workbook(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not a workbook")
    with pytest.raises(SheetError, match="Cannot read"):
        read_price_rows(bad)


def test_missing_sheet_lists_available(tmp_path):
    path = workbook(tmp_path / "w.xlsx", [("A", 1)], sheet="OTRA")
    with pytest.raises(SheetError, match="PRECIOS GENERAL.*OTRA"):
        read_price_rows(path)


def test_missing_header(tmp_path):
    path = tmp_path / "w.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "PRECIOS GENERAL"
    wb.active["C3"] = "ALGO"
    wb.save(path)
    with pytest.raises(SheetError, match="Header"):
        read_price_rows(path)


def test_unusable_cell_values_are_skipped_and_reported_without_crashing(tmp_path):
    path = workbook(
        tmp_path / "w.xlsx",
        [
            ("HUGE", 1e30),
            ("NAN", float("nan")),
            ("INF", float("inf")),
            ("NEGINF", float("-inf")),
            ("BOOL", True),
            ("NEG", -4.5),
            ("OVER", 100000000),
            ("TEXT", "1e999999999"),
            ("OK", 4.5),
        ],
    )
    result = read_price_rows(path)
    assert [r.name for r in result.rows] == ["OK"]
    assert result.skipped_rows == tuple(range(4, 12))


def test_maximum_price_is_accepted_and_rounding_is_half_up(tmp_path):
    path = workbook(tmp_path / "w.xlsx", [("MAX", "99999999.99"), ("ROUND", "2.345")])
    assert [str(r.price) for r in read_price_rows(path).rows] == ["99999999.99", "2.35"]


def _corrupt_sheet(path: Path, payload: bytes) -> None:
    rewritten = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(rewritten, "w") as target:
        for item in source.infolist():
            data = payload if item.filename == "xl/worksheets/sheet1.xml" else source.read(item)
            target.writestr(item, data)
    rewritten.replace(path)


_HEAD = (
    b'<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/'
    b'main"><dimension ref="A1:D5"/><sheetData><row r="1"><c r="C1" t="n"><v>1</v></c></row>'
)
_TAIL = b"</sheetData></worksheet>"


# The workbook opens (the sheet XML is read lazily) and then fails while iterating.
@pytest.mark.parametrize(
    "payload",
    [
        _HEAD + b"<row r=2><c",  # truncated / malformed XML
        _HEAD + b"</oops></worksheet>",  # mismatched tags
        _HEAD + b'<row r="2"><c r="C2" t="n"><v>abc</v></c></row>' + _TAIL,  # bad number
        _HEAD + b'<row r="2"><c r="C2" t="s"><v>99</v></c></row>' + _TAIL,  # dangling string ref
    ],
    ids=["truncated", "mismatched", "bad-number", "dangling-string"],
)
def test_damaged_sheet_part_is_a_sheet_error_not_a_library_traceback(tmp_path, payload):
    path = workbook(tmp_path / "w.xlsx", [("A", 1.5)])
    _corrupt_sheet(path, payload)
    with pytest.raises(SheetError, match="Cannot read"):
        read_price_rows(path)


def test_price_helper_rejects_astronomical_values_without_raising():
    for value in (10**5000, 10**30, "1E+30", float("nan"), object()):
        assert _price(value) is None
