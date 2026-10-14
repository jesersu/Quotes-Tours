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
from quotes.infrastructure.latex import EXAMPLE_COMPANY_PATH, STYLE_PATH
from quotes.infrastructure.latex import pdf as pdf_module
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
CLEAN_LOG = "This is XeTeX, fake run\nOutput written on doc.pdf\n"


class FakeTectonic:
    """A stand-in for ``subprocess.run`` that mimics what tectonic leaves in ``--outdir``."""

    def __init__(self, *, pdf=PDF_BYTES, log=CLEAN_LOG, returncode=0, stderr="", raises=None):
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
        if self.log is not None:
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


def marker(name: str) -> str:
    return f"BRANDING-MISSING-IMAGE: {name} :END-BRANDING-MISSING-IMAGE"


def wrap(text: str, width: int = 79) -> str:
    """Break lines the way TeX does: at a fixed column, adding no characters."""
    return "\n".join(text[i : i + width] for i in range(0, len(text), width))


LONG_NAME = "a-very-long-brand-image-file-name-for-the-certificate-of-the-company-2026-final-v2.png"


def test_missing_images_come_from_the_log_in_order_without_duplicates(tmp_path):
    log = (
        "noise\n"
        f"{marker('example-logo.png')}\n"
        f"{marker('not_there_a.jpeg')}\n"
        f"{marker('example-logo.png')}\n"
        "BRANDING-MISSING-IMAGE:   spaced.png   :END-BRANDING-MISSING-IMAGE\n"
    )
    result = compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=FakeTectonic(log=log))
    assert result.missing_images == ("example-logo.png", "not_there_a.jpeg", "spaced.png")


def test_a_missing_name_wrapped_across_log_lines_is_rejoined(tmp_path):
    name = f"{LONG_NAME[:-4]}-{LONG_NAME}"
    wrapped = wrap(marker(name))
    assert len(wrapped.splitlines()) == 3
    log = f"noise\n{wrapped}\nlater noise\n{marker('after.png')}\n"

    result = compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=FakeTectonic(log=log))

    assert result.missing_images == (name, "after.png")


def test_a_name_without_the_end_token_keeps_what_was_collected(tmp_path):
    log = "BRANDING-MISSING-IMAGE: cut-off-na\nme.png\n"

    result = compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=FakeTectonic(log=log))

    assert result.missing_images == ("cut-off-name.png",)


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


def test_a_missing_binary_says_how_to_install_it(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_module.shutil, "which", lambda _name: None)
    original = FileNotFoundError("tectonic")
    fake = FakeTectonic(raises=original)

    with pytest.raises(TectonicNotFound, match="brew install tectonic") as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    assert info.value.__cause__ is original
    assert not (tmp_path / "q.pdf").exists()


def test_a_file_not_found_with_the_binary_present_is_not_reported_as_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_module.shutil, "which", lambda _name: "/usr/bin/tectonic")
    original = FileNotFoundError(2, "No such file or directory")
    fake = FakeTectonic(raises=original)

    with pytest.raises(PdfCompilationError) as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    assert not isinstance(info.value, TectonicNotFound)
    assert "could not start tectonic" in str(info.value)
    assert info.value.__cause__ is original


def test_a_timeout_is_reported(tmp_path):
    original = subprocess.TimeoutExpired("tectonic", 3)
    fake = FakeTectonic(raises=original)

    with pytest.raises(TectonicTimedOut) as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake, timeout=3)

    assert "3" in str(info.value) and "Secreto" not in str(info.value)
    assert info.value.__cause__ is original


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


def test_the_error_message_never_holds_document_text_even_when_the_log_does(tmp_path):
    # LaTeX echoes source lines into the log, so log_tail may hold document text. The message
    # (what a traceback or a log line shows) must not. No RED applies: this pins existing behavior.
    log = "! Undefined control sequence.\nl.7 Cliente Secreto\n"
    fake = FakeTectonic(log=log, returncode=1, pdf=None)

    with pytest.raises(TectonicFailed) as info:
        compile_pdf(SECRET_TEX, tmp_path / "q.pdf", runner=fake)

    assert "Secreto" not in str(info.value)
    assert "Secreto" in info.value.log_tail


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


@pytest.mark.parametrize("log", [None, "", "  \n"])
def test_a_successful_compile_without_a_log_fails_instead_of_reporting_no_missing_images(
    tmp_path, log
):
    # Missing images are read from the log; without it "none missing" would be a guess.
    fake = FakeTectonic(log=log, stderr="tectonic said something")
    target = tmp_path / "q.pdf"

    with pytest.raises(TectonicFailed, match="no log") as caught:
        compile_pdf(SECRET_TEX, target, runner=fake)

    assert not target.exists()
    assert "tectonic said something" in caught.value.log_tail
    assert not fake.outdir.exists()


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


@needs_tectonic
def test_a_long_missing_image_name_is_reported_intact(tmp_path):
    company = f"\\input{{{EXAMPLE_COMPANY_PATH.as_posix()}}}"
    style = f"\\input{{{STYLE_PATH.as_posix()}}}"
    tex = "\n".join(
        [
            r"\documentclass[11pt,a4paper]{article}",
            company,
            rf"\renewcommand{{\CoVehicleFileA}}{{{LONG_NAME}}}",
            style,
            r"\begin{document}",
            r"\safeimg{\CoVehicleFileA}{2cm}",
            r"\end{document}",
        ]
    )

    result = compile_pdf(tex, tmp_path / "long.pdf", timeout=300)

    assert LONG_NAME in result.missing_images
