"""Tests for the standalone validation harness."""

from __future__ import annotations

from pathlib import Path

from scripts.validate import copy_referenced_support_files


def test_validation_harness_copies_referenced_net_support_file(tmp_path):
    validate_dir = tmp_path / "Validate"
    dat_dir = validate_dir / "DAT_validate"
    source_dir = validate_dir / "INPUT_FILES"
    dat_dir.mkdir(parents=True)
    source_dir.mkdir()
    model = validate_dir / "model.bngl"
    model.write_text('readFile({file=>"model.net"})\n', encoding="utf-8")
    (dat_dir / "model.net").write_text("begin species\nend species\n", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    copied = copy_referenced_support_files(model, validate_dir, dat_dir, work_dir)

    assert copied == [work_dir / "model.net"]
    assert (work_dir / "model.net").read_text(encoding="utf-8") == (
        "begin species\nend species\n"
    )
