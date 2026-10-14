import os
import shutil
import stat
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quotes.application.catalog import Catalog, CatalogEntry
from quotes.application.quote import QuoteRequest, RequestedItem, build_quote
from quotes.application.quote_rendering import QuoteDocument
from quotes.domain.catalog import CatalogItem, PricingUnit
from quotes.domain.money import Currency, Money
from quotes.domain.pricing import PricingPolicy
from quotes.domain.travelers import Travelers
from quotes.infrastructure.latex import EXAMPLE_COMPANY_PATH
from quotes.infrastructure.latex.pdf import (
    PdfCompilationError,
    PdfResult,
    TectonicFailed,
    TectonicNotFound,
    TectonicTimedOut,
    compile_pdf,
)
from quotes.infrastructure.latex.quote_renderer import LatexQuoteRenderer
from quotes.infrastructure.output_file import OutputExists

needs_tectonic = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic is not installed"
)

SECRET_TEX = r"\documentclass{article}\begin{document}Cliente Secreto\end{document}"
PDF_BYTES = b"%PDF-1.5\nfake"


class FakeTectonic:
    """A stand-in for ``subprocess.run`` that mimics what tectonic leaves in ``--outdir``."""

    def __init__(self, *, pdf=PDF_BYTES, log="", returncode=0, stderr="", raises=None):
        self.pdf, self.log, self.returncode = pdf, log, returncode
        self.stderr, self.raises = stderr, raises
        self.calls = []
        self.outdir = None

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self.raises is not None:
            raise self.raises
        self.outdir = Path(command[command.index("--outdir") + 1])
        if self.pdf is not None:
            (self.outdir / "doc.pdf").write_bytes(self.pdf)
        (self.outdir / "doc.log").write_text(self.log, encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, "", self.stderr)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_success_writes_the_pdf_owner_only_and_removes_the_temp_directory(tmp_path):
    fake = FakeTectonic()
    target = tmp_path / "out" / "quote.pdf"

    result = compile_pdf(SECRET_TEX, target, runner=fake)

    assert result == PdfResult(target, ())
    assert target.read_bytes() == PDF_BYTES and mode(target) == 0o600
    assert not fake.outdir.exists()
    command, kwargs = fake.calls[0]
    assert command[0] == "tectonic" and "--keep-logs" in command and command[-1] == "doc.tex"
    assert kwargs["cwd"] == fake.outdir.as_posix() or Path(kwargs["cwd"]) == fake.outdir
    assert kwargs["capture_output"] is True and kwargs["text"] is True
    assert kwargs["check"] is False and kwargs["timeout"] == 300


def test_the_tectonic_binary_and_timeout_are_configurable(tmp_path):
    fake = FakeTectonic()
    compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake, tectonic="/opt/tectonic", timeout=5)
    command, kwargs = fake.calls[0]
    assert command[0] == "/opt/tectonic" and kwargs["timeout"] == 5


def test_missing_images_come_from_the_log_in_order_without_duplicates(tmp_path):
    log = (
        "noise\n"
        "BRANDING-MISSING-IMAGE: example-logo.png\n"
        "BRANDING-MISSING-IMAGE: not_there_a.jpeg\n"
        "BRANDING-MISSING-IMAGE: example-logo.png\n"
        "BRANDING-MISSING-IMAGE:   spaced.png  \n"
    )
    result = compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=FakeTectonic(log=log))
    assert result.missing_images == ("example-logo.png", "not_there_a.jpeg", "spaced.png")


def test_existing_output_is_refused_before_compiling(tmp_path):
    target = tmp_path / "q.pdf"
    target.write_bytes(b"old")
    fake = FakeTectonic()

    with pytest.raises(OutputExists, match="--force"):
        compile_pdf(SECRET_TEX, target, runner=fake)

    assert fake.calls == [] and target.read_bytes() == b"old"


def test_force_overwrites_an_existing_output(tmp_path):
    target = tmp_path / "q.pdf"
    target.write_bytes(b"old")

    compile_pdf(SECRET_TEX, target, force=True, runner=FakeTectonic())

    assert target.read_bytes() == PDF_BYTES


def test_a_missing_binary_says_how_to_install_it(tmp_path):
    fake = FakeTectonic(raises=FileNotFoundError("tectonic"))

    with pytest.raises(TectonicNotFound, match="brew install tectonic"):
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    assert not (tmp_path / "q.pdf").exists()


def test_a_timeout_is_reported(tmp_path):
    fake = FakeTectonic(raises=subprocess.TimeoutExpired("tectonic", 3))

    with pytest.raises(TectonicTimedOut) as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake, timeout=3)

    assert "3" in str(info.value) and "Secreto" not in str(info.value)


def test_a_failed_compile_carries_the_log_tail_but_not_the_source(tmp_path):
    log = "\n".join(f"line {n}" for n in range(100)) + "\n! Undefined control sequence.\n"
    fake = FakeTectonic(log=log, returncode=1, pdf=None)

    with pytest.raises(TectonicFailed) as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    error = info.value
    assert "! Undefined control sequence." in error.log_tail
    assert "line 99" in error.log_tail and "line 10\n" not in error.log_tail
    assert len(error.log_tail.splitlines()) <= 40
    assert "Secreto" not in error.log_tail and "Secreto" not in str(error)
    assert not fake.outdir.exists() and not (tmp_path / "q.pdf").exists()


def test_a_failed_compile_without_a_log_falls_back_to_stderr(tmp_path):
    fake = FakeTectonic(log="", returncode=1, pdf=None, stderr="error: boom")

    with pytest.raises(TectonicFailed) as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    assert "error: boom" in info.value.log_tail


@pytest.mark.parametrize("pdf", [None, b""])
def test_exit_zero_without_a_usable_pdf_is_a_failure(tmp_path, pdf):
    fake = FakeTectonic(pdf=pdf, log="! Emergency stop.")

    with pytest.raises(TectonicFailed, match="PDF") as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    assert "Emergency stop" in info.value.log_tail
    assert not fake.outdir.exists() and not (tmp_path / "q.pdf").exists()


def test_every_error_is_a_pdf_compilation_error():
    for error in (TectonicNotFound, TectonicFailed, TectonicTimedOut):
        assert issubclass(error, PdfCompilationError)


# --- real compile -----------------------------------------------------------


def example_quote_tex() -> str:
    item = CatalogItem(
        "van", "Item van", Money(Decimal("100.00"), Currency.PEN), PricingUnit.PER_GROUP
    )
    catalog = Catalog([CatalogEntry(item, "transport", "Van privada", "Private van")], [])
    request = QuoteRequest(2, Travelers(2), (RequestedItem("van"),), (), ())
    quote = build_quote(request, catalog, PricingPolicy(margin_rate=Decimal("0.25")))
    document = QuoteDocument(
        quote=quote,
        client_name="Ana Pérez",
        title="Cañón del Colca",
        issued_on=date(2026, 10, 13),
        signed_by="Equipo de ventas",
    )
    return LatexQuoteRenderer(EXAMPLE_COMPANY_PATH).render(document)


@needs_tectonic
def test_a_real_quote_compiles_and_reports_the_missing_company_images(tmp_path):
    target = tmp_path / "quote.pdf"

    result = compile_pdf(example_quote_tex(), target, timeout=300)

    assert target.read_bytes().startswith(b"%PDF")
    assert result.path == target
    assert "example-logo.png" in result.missing_images
    assert "example-certificate.png" in result.missing_images
