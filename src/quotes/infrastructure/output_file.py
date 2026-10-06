"""Private output files: owner-only permissions, atomic writes, never overwritten by accident."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


class OutputExists(Exception):
    """The output file already exists and --force was not given."""


def write_new_file(path: Path, text: str, *, force: bool) -> None:
    """Write ``text`` to ``path`` atomically with mode 0o600.

    The content goes to a temp file in the same directory (``mkstemp`` creates it 0o600), is
    flushed and fsynced, then moved onto the target. Any failure removes the temp file and leaves
    an existing target untouched. With ``force`` the move is ``os.replace`` (atomic, and the
    resulting file has the temp file's 0o600 mode even over a wider existing file). Without it
    the move is ``os.link``, which fails if the target exists, so refusal is race-safe: a file
    created by someone else after our start is never overwritten.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temp_name, path)
        else:
            try:
                os.link(temp_name, path)
            except FileExistsError:
                raise OutputExists(f"{path} already exists; pass --force to overwrite it") from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
