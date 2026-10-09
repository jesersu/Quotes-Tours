import re
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from quotes.infrastructure.latex import EXAMPLE_COMPANY_PATH, STYLE_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_COMPANY_PATH = REPO_ROOT / "data" / "private" / "branding" / "company.tex"

# Names the style provides itself; everything else must come from the company file.
STYLE_OWNED = {"CoLang", "CoAssetsDir", "CoGraphicsPath"}

DEFINITION = re.compile(r"\\(?:new|renew|provide)command\*?\{\\(Co[A-Za-z]+)\}")
USAGE = re.compile(r"\\(Co[A-Za-z]+)")

needs_tectonic = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic is not installed"
)


def defined_fields(path: Path) -> set[str]:
    return set(DEFINITION.findall(path.read_text(encoding="utf-8")))


def fields_required_by_style() -> set[str]:
    return set(USAGE.findall(STYLE_PATH.read_text(encoding="utf-8"))) - STYLE_OWNED


def test_style_defines_no_company_data():
    assert defined_fields(STYLE_PATH) <= STYLE_OWNED


def test_example_company_defines_every_field_the_style_uses():
    assert fields_required_by_style() <= defined_fields(EXAMPLE_COMPANY_PATH)


def test_example_company_is_synthetic():
    text = EXAMPLE_COMPANY_PATH.read_text(encoding="utf-8")
    assert "example.com" in text
    assert "visitcolca" not in text.lower()
    assert "colca star" not in text.lower()


def test_private_company_defines_every_field_the_style_uses():
    if not PRIVATE_COMPANY_PATH.exists():
        pytest.skip("no private company data on this machine")
    assert fields_required_by_style() <= defined_fields(PRIVATE_COMPANY_PATH)


COMPANY = rf"\input{{{EXAMPLE_COMPANY_PATH.as_posix()}}}"
STYLE = rf"\input{{{STYLE_PATH.as_posix()}}}"

# The document reports what the style resolved through the log, so the tests
# can assert on behaviour without reading the PDF.
PROBES = r"""
\typeout{LANG=\ifcoEnglish en\else es\fi}
\typeout{DRAFT=\ifdraft yes\else no\fi}
"""

BODY = r"""
\letterhead
\sect{Itinerario}
\dayhead{Día 1}{Arequipa -- Chivay}
Señor viajero: ¿listo para el cañón? ¡Sí! Niño, pingüino, 3.800~m. \TODO{pendiente}
\daymeta{Almuerzo}{Hotel}
\opthead{Opción A}{Dos días}
\notebox{Nota de prueba.}
\sect{Vehículo}
\vehicletable{Siete viajeros.}{Guía bilingüe.}
\sect{Credenciales}
\credentials
\sect{Confirmar}
\confirmblock{Por favor confirme.}
\signature{Equipo de ventas}
"""


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\xff\xff")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def compile_document(tmp_path: Path, preamble: str, body: str = BODY):
    source = tmp_path / "doc.tex"
    source.write_text(
        "\\documentclass[11pt,a4paper]{article}\n"
        + preamble
        + "\n\\begin{document}\n"
        + body
        + "\n\\end{document}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["tectonic", "--keep-logs", "--outdir", str(tmp_path), source.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    log_path = tmp_path / "doc.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return result, log


def assert_compiled(tmp_path: Path, result) -> None:
    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "doc.pdf").stat().st_size > 0


@needs_tectonic
@pytest.mark.parametrize("lang", ["es", "en"])
def test_declared_language_is_the_one_the_style_resolves(tmp_path, lang):
    preamble = "\n".join([rf"\newcommand{{\CoLang}}{{{lang}}}", COMPANY, STYLE, PROBES])

    result, log = compile_document(tmp_path, preamble)

    assert_compiled(tmp_path, result)
    assert f"LANG={lang}" in log


@needs_tectonic
def test_document_without_declarations_is_spanish_and_final(tmp_path):
    preamble = "\n".join([COMPANY, STYLE, PROBES])

    result, log = compile_document(tmp_path, preamble)

    assert_compiled(tmp_path, result)
    assert "LANG=es" in log
    assert "DRAFT=no" in log


@needs_tectonic
def test_declared_draft_switch_is_respected(tmp_path):
    preamble = "\n".join([r"\newif\ifdraft", r"\drafttrue", COMPANY, STYLE, PROBES])

    result, log = compile_document(tmp_path, preamble)

    assert_compiled(tmp_path, result)
    assert "DRAFT=yes" in log


@needs_tectonic
def test_style_refuses_to_load_without_the_company_file(tmp_path):
    result, log = compile_document(tmp_path, STYLE, body="Hola")

    assert result.returncode != 0
    assert "Load the company data file" in result.stdout + result.stderr + log


@needs_tectonic
def test_missing_image_with_an_underscore_in_its_name_becomes_a_placeholder(tmp_path):
    preamble = "\n".join(
        [
            COMPANY,
            r"\renewcommand{\CoVehicleFileA}{not_there_a.jpeg}",
            r"\renewcommand{\CoConstanciaFile}{not_there_b.png}",
            STYLE,
        ]
    )

    result, _ = compile_document(tmp_path, preamble)

    assert_compiled(tmp_path, result)


@needs_tectonic
def test_diagnostics_look_where_the_images_are_actually_loaded_from(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "example-logo.png").write_bytes(tiny_png())
    (tmp_path / "brand_assets").mkdir()
    (tmp_path / "brand_assets" / "example-certificate.png").write_bytes(tiny_png())
    preamble = "\n".join(
        [
            r"\newcommand{\CoAssetsDir}{brand_assets/}",
            COMPANY,
            STYLE,
            r"\coimgstatus{\CoLogoFile}{\typeout{LOGO=found}}{\typeout{LOGO=missing}}",
            r"\coimgstatus{\CoConstanciaFile}{\typeout{CERT=found}}{\typeout{CERT=missing}}",
            r"\coimgstatus{\CoVehicleFileA}{\typeout{VEHICLE=found}}{\typeout{VEHICLE=missing}}",
        ]
    )

    result, log = compile_document(tmp_path, preamble, body=r"\letterhead \brandingdiag")

    assert_compiled(tmp_path, result)
    assert "LOGO=found" in log  # only in the document's own assets/ folder
    assert "CERT=found" in log  # only in the company folder
    assert "VEHICLE=missing" in log
