"""Compile LaTeX text to a PDF file with ``tectonic``."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from quotes.infrastructure.output_file import OutputExists, write_new_bytes

_LOG_TAIL_LINES = 40
# Both ends of the line that \safeimg and \cologo in colcastar_style.tex write to the log:
#   BRANDING-MISSING-IMAGE: <name> :END-BRANDING-MISSING-IMAGE
# TeX wraps log lines at about 79 columns, so the end token tells where a wrapped name stops.
_MISSING_IMAGE_MARKER = "BRANDING-MISSING-IMAGE:"
_MISSING_IMAGE_END = ":END-BRANDING-MISSING-IMAGE"


class PdfCompilationError(Exception):
    """The PDF could not be produced."""


class TectonicNotFound(PdfCompilationError):
    """The ``tectonic`` binary is not installed or not on PATH."""


class TectonicFailed(PdfCompilationError):
    """``tectonic`` ran but produced no usable PDF.

    ``str(error)`` never contains the document text. ``log_tail`` is the end of the LaTeX log or
    of stderr and may contain fragments of the document (LaTeX echoes source lines into its
    log), including client names. Show it only on the operator's own terminal; never send it to
    shared logs or to the client.
    """

    def __init__(self, message: str, log_tail: str) -> None:
        super().__init__(message)
        self.log_tail = log_tail


class TectonicTimedOut(PdfCompilationError):
    """``tectonic`` did not finish within the allowed time."""


@dataclass(frozen=True)
class PdfResult:
    path: Path
    # File names the style replaced with a placeholder box, in log order, without repeats.
    missing_images: tuple[str, ...]


def _tail(text: str) -> str:
    return "\n".join(text.splitlines()[-_LOG_TAIL_LINES:])


def _missing_images(log: str) -> tuple[str, ...]:
    names: dict[str, None] = {}
    lines = log.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.startswith(_MISSING_IMAGE_MARKER):
            continue
        # TeX breaks long lines without adding characters, so join until the end token shows up.
        joined = line
        while _MISSING_IMAGE_END not in joined and index < len(lines):
            joined += lines[index]
            index += 1
        name = joined[len(_MISSING_IMAGE_MARKER) :].split(_MISSING_IMAGE_END, 1)[0].strip()
        if name:
            names.setdefault(name)
    return tuple(names)


def compile_pdf(
    tex: str,
    output_path: Path,
    *,
    force: bool = False,
    timeout: float = 300,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    tectonic: str = "tectonic",
) -> PdfResult:
    """Compile ``tex`` and write the PDF to ``output_path`` (owner-only, never overwritten
    without ``force``).

    Refusal is checked before compiling so no work is wasted; the final write still goes through
    ``write_new_bytes``, which is race-safe. No error message contains the source text.
    ``TectonicFailed.log_tail`` is the end of the LaTeX log or tectonic's stderr; it can echo
    fragments of the document (client names included), so it is for the operator's terminal only.
    """
    output_path = Path(output_path)
    if output_path.exists() and not force:
        raise OutputExists(f"{output_path} already exists; pass --force to overwrite it")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "doc.tex").write_text(tex, encoding="utf-8")
        command = [tectonic, "--keep-logs", "--outdir", str(work), "doc.tex"]
        try:
            completed = runner(
                command, cwd=work, capture_output=True, text=True, timeout=timeout, check=False
            )
        except FileNotFoundError as exc:
            if shutil.which(tectonic) is None:
                raise TectonicNotFound(
                    f"{tectonic!r} was not found; install it with `brew install tectonic`"
                ) from exc
            raise PdfCompilationError(f"could not start tectonic: {exc.strerror or exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise TectonicTimedOut(f"tectonic did not finish within {timeout:g} seconds") from exc

        log_path = work / "doc.log"
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        pdf_path = work / "doc.pdf"
        pdf = pdf_path.read_bytes() if pdf_path.exists() else b""
        if completed.returncode != 0 or not pdf:
            reason = (
                f"tectonic exited with code {completed.returncode}"
                if completed.returncode != 0
                else "tectonic finished but produced no PDF"
            )
            raise TectonicFailed(reason, _tail(log if log.strip() else completed.stderr or ""))
        if not log.strip():
            # Missing images are read from the log; without it "none missing" would be a guess.
            raise TectonicFailed(
                "tectonic produced no log, so missing brand images cannot be checked",
                _tail(completed.stderr or ""),
            )

    write_new_bytes(output_path, pdf, force=force)
    return PdfResult(output_path, _missing_images(log))
