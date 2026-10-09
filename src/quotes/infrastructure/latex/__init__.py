"""LaTeX assets: the public brand style and an invented company to compile it with."""

from pathlib import Path

_HERE = Path(__file__).resolve().parent

STYLE_PATH = _HERE / "colcastar_style.tex"
EXAMPLE_COMPANY_PATH = _HERE / "company.example.tex"
