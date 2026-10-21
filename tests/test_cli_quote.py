import io
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from quotes.application.catalog import (
    Catalog,
    CatalogEntry,
    CatalogIssue,
    LocalPaymentEntry,
)
from quotes.cli import main
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.local_payment import LocalPaymentInfo, LocalPrice, VisitorCategory
from quotes.domain.money import Currency, Money
from quotes.infrastructure.in_memory_catalog import InMemoryCatalogRepository
from quotes.infrastructure.latex import EXAMPLE_COMPANY_PATH
from quotes.infrastructure.latex.pdf import PdfResult, TectonicFailed, TectonicNotFound, compile_pdf
from quotes.infrastructure.output_file import OutputExists

# Synthetic numbers chosen so they cannot appear in the output by accident.
PRICE = "777.77"
MARGIN = "0.31"
FX = "3.45"
TICKET = "888.88"

REQUEST = f"""\
client: Smith family
title: Colca Canyon, 2 days
language: en
date: 2026-10-14
signed_by: Sales team
days: 2
travelers:
  adults: 2
  child_ages: [8]
pricing:
  margin_rate: {MARGIN}
  fx_rate: "{FX}"
items:
  - id: van
  - id: guide
    days: 1
  - id: bus-seat
    quantity: 3
extras:
  - label: Horseback ride
    items:
      - id: horse
paid_locally: [colca-ticket]
"""


def pen(amount: str) -> Money:
    return Money(Decimal(amount), Currency.PEN)


def entry(item_id: str, unit: PricingUnit) -> CatalogEntry:
    item = CatalogItem(item_id, item_id, pen(PRICE), unit)
    return CatalogEntry(item, "tour", item_id, item_id)


def catalog() -> Catalog:
    items = [
        entry("van", PricingUnit.PER_GROUP),
        entry("guide", PricingUnit.PER_DAY),
        entry("bus-seat", PricingUnit.PER_UNIT),
        entry("horse", PricingUnit.PER_PERSON),
    ]
    prices = tuple(LocalPrice(c, pen(TICKET)) for c in VisitorCategory)
    ticket = LocalPaymentEntry(
        "colca-ticket", LocalPaymentInfo("Ticket", prices), "Boleto", "Ticket"
    )
    return Catalog(items, [ticket])


class FakeCompile:
    """Stands in for ``compile_pdf``: records the LaTeX and writes a fake PDF."""

    def __init__(self, missing=(), raises=None):
        self.missing, self.raises = tuple(missing), raises
        self.tex = None
        self.force = None

    def __call__(self, tex, output_path, *, force=False):
        if self.raises is not None:
            raise self.raises
        if Path(output_path).exists() and not force:
            raise OutputExists(f"{output_path} already exists; pass --force to overwrite it")
        self.tex, self.force = tex, force
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        return PdfResult(Path(output_path), self.missing)


@pytest.fixture
def files(tmp_path):
    request = tmp_path / "smith.yaml"
    request.write_text(REQUEST, encoding="utf-8")
    company = tmp_path / "company.tex"
    company.write_text("% fake company\n", encoding="utf-8")
    return request, company, tmp_path / "smith.pdf"


def run(argv, *, repository=None, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    if repository is None:
        repository = InMemoryCatalogRepository(catalog())
    code = main(argv, repository=repository, out=out, err=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


def build(files, *extra, **kwargs):
    request, company, output = files
    argv = ["quote", "build", str(request), "-o", str(output), "--company", str(company), *extra]
    return run(argv, **kwargs)


def test_success_writes_the_pdf_and_prints_path_and_counts(files):
    _, _, output = files
    fake = FakeCompile()
    code, out, err = build(files, compile=fake)
    assert code == 0
    assert output.read_bytes() == b"%PDF-fake"
    assert str(output) in out
    assert "services: 3" in out
    assert "optional extras: 1" in out
    assert "paid locally: 1" in out
    assert "language: en" in out
    assert err == ""


def test_output_never_shows_money(files):
    _, out, err = build(files, compile=FakeCompile())
    for secret in (PRICE, MARGIN, FX, TICKET, "margin", "total"):
        assert secret not in out.lower()
        assert secret not in err.lower()


def test_output_never_shows_money_with_warnings_either(files):
    fake = FakeCompile(missing=("logo.png",))
    _, out, err = build(files, compile=fake)
    for secret in (PRICE, MARGIN, FX, TICKET):
        assert secret not in out + err


def test_language_reaches_the_renderer(files):
    fake = FakeCompile()
    build(files, compile=fake)
    assert "\\newcommand{\\CoLang}{en}" in fake.tex


def test_spanish_is_the_default_language(files):
    request, _, _ = files
    request.write_text(REQUEST.replace("language: en\n", ""), encoding="utf-8")
    fake = FakeCompile()
    code, out, _ = build(files, compile=fake)
    assert code == 0
    assert "language: es" in out
    assert "\\newcommand{\\CoLang}{es}" in fake.tex


def test_request_date_is_used_when_given(files):
    fake = FakeCompile()
    build(files, compile=fake, today=lambda: date(2000, 1, 2))
    assert "2026" in fake.tex
    assert "2000" not in fake.tex


def test_today_is_used_when_the_request_has_no_date(files):
    request, _, _ = files
    request.write_text(REQUEST.replace("date: 2026-10-14\n", ""), encoding="utf-8")
    fake = FakeCompile()
    build(files, compile=fake, today=lambda: date(2031, 3, 4))
    assert "2031" in fake.tex
    assert "2026" not in fake.tex


def test_default_output_comes_from_the_request_stem(files, tmp_path, monkeypatch):
    request, company, _ = files
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(
        ["quote", "build", str(request), "--company", str(company)], compile=FakeCompile()
    )
    assert code == 0
    assert (tmp_path / "data/private/quotes/smith.pdf").read_bytes() == b"%PDF-fake"
    assert "smith.pdf" in out


def test_default_company_path_is_used(files, tmp_path, monkeypatch):
    request, company, output = files
    default = tmp_path / "data/private/branding/company.tex"
    default.parent.mkdir(parents=True)
    shutil.copy(company, default)
    monkeypatch.chdir(tmp_path)
    fake = FakeCompile()
    code, _, _ = run(["quote", "build", "smith.yaml", "-o", str(output)], compile=fake)
    assert code == 0
    assert str(default.resolve().as_posix()) in fake.tex


def test_assets_folder_is_passed_only_when_it_exists(files, tmp_path):
    fake = FakeCompile()
    assets = tmp_path / "assets"
    assets.mkdir()
    code, _, _ = build(files, "--assets", str(assets), compile=fake)
    assert code == 0
    assert assets.as_posix() in fake.tex


def test_missing_default_assets_folder_is_not_an_error(files, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no data/private/branding/assets here
    assert build(files, compile=FakeCompile())[0] == 0


def test_relative_paths_are_made_absolute_for_latex(files, tmp_path, monkeypatch):
    request, company, _ = files
    monkeypatch.chdir(tmp_path)
    fake = FakeCompile()
    code, _, _ = run(
        ["quote", "build", "smith.yaml", "-o", "out.pdf", "--company", "company.tex"],
        compile=fake,
    )
    assert code == 0
    assert company.resolve().as_posix() in fake.tex


def test_existing_output_is_refused_without_force(files):
    _, _, output = files
    output.write_bytes(b"old")
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert "--force" in err
    assert output.read_bytes() == b"old"


def test_force_overwrites(files):
    _, _, output = files
    output.write_bytes(b"old")
    fake = FakeCompile()
    code, _, _ = build(files, "--force", compile=fake)
    assert code == 0
    assert fake.force is True
    assert output.read_bytes() == b"%PDF-fake"


def test_missing_images_warn_and_still_exit_zero(files):
    code, out, err = build(files, compile=FakeCompile(missing=("logo.png", "cover.jpg")))
    assert code == 0
    assert "warning: missing image logo.png" in err
    assert "warning: missing image cover.jpg" in err
    assert "placeholder" in err
    assert "logo.png" not in out


def test_catalog_issues_give_a_one_line_warning_with_a_count(files):
    issues = (
        CatalogIssue("warning", "x", "a", "secret-detail-1"),
        CatalogIssue("error", "y", "b", "secret-detail-2"),
    )
    repo = InMemoryCatalogRepository(catalog(), issues=issues)
    code, _, err = build(files, repository=repo, compile=FakeCompile())
    assert code == 0
    assert "warning: the catalog reported 2 issue(s)" in err
    assert "secret-detail" not in err


def test_unknown_catalog_id_exits_two(files):
    request, _, _ = files
    request.write_text(REQUEST.replace("id: horse", "id: nope"), encoding="utf-8")
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert "nope" in err


def test_unknown_local_payment_exits_two(files):
    request, _, _ = files
    request.write_text(REQUEST.replace("[colca-ticket]", "[ghost]"), encoding="utf-8")
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert "ghost" in err


def test_per_unit_item_without_quantity_exits_two(files):
    request, _, _ = files
    request.write_text(REQUEST.replace("    quantity: 3\n", ""), encoding="utf-8")
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert err.startswith("error:")


def test_invalid_request_file_lists_every_problem(files):
    request, _, output = files
    request.write_text("client: A\nitems: van\n", encoding="utf-8")
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert "items must be a list" in err
    assert "title is required" in err
    assert not output.exists()


def test_missing_request_file_exits_two(files):
    request, _, _ = files
    request.unlink()
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert "not found" in err


def test_missing_company_file_exits_two(files):
    _, company, _ = files
    company.unlink()
    code, _, err = build(files, compile=FakeCompile())
    assert code == 2
    assert "company" in err


def test_unsafe_company_path_exits_two(files, tmp_path):
    bad = tmp_path / "my company.tex"
    bad.write_text("%", encoding="utf-8")
    request, _, output = files
    code, _, err = run(
        ["quote", "build", str(request), "-o", str(output), "--company", str(bad)],
        compile=FakeCompile(),
    )
    assert code == 2
    assert err.startswith("error:")


def test_missing_database_url_exits_two(files):
    out, err = io.StringIO(), io.StringIO()
    request, company, output = files
    argv = ["quote", "build", str(request), "-o", str(output), "--company", str(company)]
    code = main(argv, env={}, out=out, err=err, compile=FakeCompile())
    assert code == 2
    assert "DATABASE_URL" in err.getvalue()


def test_database_errors_exit_two_without_the_driver_message(files):
    class Broken:
        def load(self):
            raise psycopg.OperationalError("postgresql://user:hunter2@host/db")

    code, _, err = build(files, repository=Broken(), compile=FakeCompile())
    assert code == 2
    assert "hunter2" not in err
    assert "OperationalError" in err


def test_tectonic_not_found_exits_two(files):
    fake = FakeCompile(raises=TectonicNotFound("'tectonic' was not found; brew install tectonic"))
    code, _, err = build(files, compile=fake)
    assert code == 2
    assert "brew install tectonic" in err


def test_tectonic_failure_prints_the_log_under_a_heading(files):
    fake = FakeCompile(raises=TectonicFailed("tectonic exited with code 1", "line about Smith"))
    code, _, err = build(files, compile=fake)
    assert code == 2
    assert "tectonic exited with code 1" in err
    assert "LaTeX log (may contain document text)" in err
    assert err.index("LaTeX log") < err.index("line about Smith")


def test_catalog_commands_are_unchanged():
    code, out, _ = run(["catalog", "check"])
    assert code == 0
    assert "pricing items: 4" in out


needs_tectonic = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic is not installed"
)


@needs_tectonic
def test_end_to_end_with_the_real_compiler(files):
    request, _, output = files
    code, out, err = build((request, EXAMPLE_COMPANY_PATH, output), compile=compile_pdf)
    assert code == 0
    assert output.read_bytes().startswith(b"%PDF")
    assert "warning: missing image" in err
    assert PRICE not in out + err


# --- several options ---

OPTIONS_REQUEST = f"""\
client: Smith family
title: Colca Canyon
language: en
date: 2026-10-14
signed_by: Sales team
days: 2
travelers:
  adults: 2
pricing:
  margin_rate: {MARGIN}
  fx_rate: "{FX}"
paid_locally: [colca-ticket]
options:
  - label: Option 1
    subtitle: Ends in Puno
    items:
      - id: van
    extras:
      - label: Horseback ride
        items:
          - id: horse
  - label: Option 2
    days: 3
    items:
      - id: van
      - id: guide
"""


def test_options_request_builds_one_document_with_counts_only(files):
    request, _, output = files
    request.write_text(OPTIONS_REQUEST, encoding="utf-8")
    fake = FakeCompile()

    code, out, err = build(files, compile=fake)

    assert code == 0
    assert output.read_bytes() == b"%PDF-fake"
    assert "options: 2" in out
    assert "services: 3" in out
    assert "optional extras: 1" in out
    assert "paid locally: 1" in out
    assert fake.tex.count("\\opthead{") == 2
    assert err == ""
    for secret in (PRICE, MARGIN, FX, TICKET, "margin", "total"):
        assert secret not in (out + err).lower()


def test_a_single_option_request_reports_one_option(files):
    code, out, _ = build(files, compile=FakeCompile())

    assert code == 0
    assert "options: 1" in out


def test_options_request_problems_exit_2_with_paths_and_no_money(files):
    request, _, _ = files
    request.write_text(
        OPTIONS_REQUEST.replace("label: Option 2", "label: Option 1"), encoding="utf-8"
    )

    code, out, err = build(files, compile=FakeCompile())

    assert code == 2
    assert out == ""
    assert "options[1].label" in err
    assert MARGIN not in err


def test_an_unknown_id_in_an_option_exits_2(files):
    request, _, _ = files
    request.write_text(OPTIONS_REQUEST.replace("id: guide", "id: ghost"), encoding="utf-8")

    code, _, err = build(files, compile=FakeCompile())

    assert code == 2
    assert "ghost" in err
