import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quotes.infrastructure.latex import EXAMPLE_COMPANY_PATH, STYLE_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_COMPANY_PATH = REPO_ROOT / "data" / "private" / "branding" / "company.tex"

# Names the style provides itself; everything else must come from the company file.
STYLE_OWNED = {"CoLang", "CoAssetsDir", "CoGraphicsPath"}

DEFINITION = re.compile(r"\\(?:new|renew|provide)command\*?\{\\(Co[A-Za-z]+)\}")
USAGE = re.compile(r"\\(Co[A-Za-z]+)")


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


DOCUMENT = r"""
\documentclass[11pt,a4paper]{article}
\newif\ifdraft
\draftfalse
\newcommand{\CoLang}{%(lang)s}
\newcommand{\CoAssetsDir}{assets/}
\input{%(company)s}
\input{%(style)s}
\begin{document}
\letterhead
\sect{Itinerario}
\dayhead{Día 1}{Arequipa -- Chivay}
Señor viajero: ¿listo para el cañón? ¡Sí! Niño, pingüino, 3.800~m.
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
\end{document}
"""


@pytest.mark.skipif(shutil.which("tectonic") is None, reason="tectonic is not installed")
@pytest.mark.parametrize("lang", ["es", "en"])
def test_minimal_document_compiles_with_the_example_company(tmp_path, lang):
    source = tmp_path / "doc.tex"
    source.write_text(
        DOCUMENT
        % {
            "lang": lang,
            "company": EXAMPLE_COMPANY_PATH.as_posix(),
            "style": STYLE_PATH.as_posix(),
        },
        encoding="utf-8",
    )

    result = subprocess.run(
        ["tectonic", "--outdir", str(tmp_path), str(source)],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "doc.pdf").stat().st_size > 0
