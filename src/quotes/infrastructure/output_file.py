"""Private output files: created with owner-only permissions, never overwritten by accident."""

from __future__ import annotations

import os
from pathlib import Path


class OutputExists(Exception):
    """The output file already exists and --force was not given."""


def write_new_file(path: Path, text: str, *, force: bool) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise OutputExists(f"{path} already exists; pass --force to overwrite it") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
