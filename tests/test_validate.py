"""Tests for the standalone validation harness."""

from __future__ import annotations

from pathlib import Path

from scripts.cross_validate import _stage_model
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


def test_validation_harness_copies_tfun_table_from_either_argument_position(tmp_path):
    validate_dir = tmp_path / "Validate"
    dat_dir = validate_dir / "DAT_validate"
    dat_dir.mkdir(parents=True)
    model = validate_dir / "model.bngl"
    model.write_text(
        "f_bng3() = tfun('tables/increase.tfun', nested(time, 2))\n"
        'f_bng2() = TFUN(nested(time, 2), "tables/increase.tfun")\n',
        encoding="utf-8",
    )
    source = dat_dir / "tables" / "increase.tfun"
    source.parent.mkdir()
    source.write_text("0 1\n1 2\n", encoding="utf-8")
    work_dir = tmp_path / "work"

    copied = copy_referenced_support_files(model, validate_dir, dat_dir, work_dir)

    staged = work_dir / "tables" / "increase.tfun"
    assert copied == [staged]
    assert staged.read_text(encoding="utf-8") == "0 1\n1 2\n"


def test_cross_validation_stages_the_tfun_corpus_sidecar(tmp_path):
    models_dir = Path(__file__).resolve().parents[1] / "models"
    model = models_dir / "test_tfun_file.bngl"

    staged_model = _stage_model(model, models_dir, tmp_path / "reference")

    staged_table = staged_model.parent / "test_data.tfun"
    assert staged_table.read_bytes() == (models_dir / "test_data.tfun").read_bytes()
