import os
import stat

import pytest

from quotes.infrastructure import output_file
from quotes.infrastructure.output_file import OutputExists, write_new_file


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def siblings(path):
    return sorted(p.name for p in path.parent.iterdir())


def test_new_file_is_owner_only_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "sub" / "out.txt"
    write_new_file(target, "hello", force=False)
    assert target.read_text() == "hello" and mode(target) == 0o600
    assert siblings(target) == ["out.txt"]


def test_forced_overwrite_tightens_permissions_of_a_wider_existing_file(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old")
    target.chmod(0o644)
    write_new_file(target, "new", force=True)
    assert target.read_text() == "new" and mode(target) == 0o600
    assert siblings(target) == ["out.txt"]


def test_refusal_without_force_leaves_the_file_untouched(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old")
    target.chmod(0o644)
    with pytest.raises(OutputExists, match="--force"):
        write_new_file(target, "new", force=False)
    assert target.read_text() == "old" and mode(target) == 0o644
    assert siblings(target) == ["out.txt"]


@pytest.mark.parametrize("force", [True, False])
def test_failed_write_keeps_previous_content_and_removes_the_temp_file(
    tmp_path, monkeypatch, force
):
    target = tmp_path / "out.txt"
    if force:
        target.write_text("previous")

    def boom(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(output_file.os, "fsync", boom)
    with pytest.raises(OSError, match="disk full"):
        write_new_file(target, "new", force=force)
    assert (target.read_text() == "previous") if force else not target.exists()
    assert siblings(target) == (["out.txt"] if force else [])


def test_failed_replace_keeps_previous_content_and_removes_the_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "out.txt"
    target.write_text("previous")

    def boom(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr(output_file.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        write_new_file(target, "new", force=True)
    assert target.read_text() == "previous" and siblings(target) == ["out.txt"]
