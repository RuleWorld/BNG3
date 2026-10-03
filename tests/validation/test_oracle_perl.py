"""Strict artifact selection and network-only mode for the BNG2 oracle."""

from __future__ import annotations

import subprocess

from tests.validation import oracle_perl


def test_artifact_selection_prefers_exact_model_stem(tmp_path):
    exact = tmp_path / "model.net"
    exact.write_text("exact", encoding="utf-8")
    (tmp_path / "model_burnin.net").write_text("phase", encoding="utf-8")

    selected = oracle_perl._select_artifact(tmp_path, "model", ".net")

    assert selected == exact


def test_artifact_selection_allows_one_unambiguous_variant(tmp_path):
    only = tmp_path / "model_cont.net"
    only.write_text("phase", encoding="utf-8")

    selected = oracle_perl._select_artifact(tmp_path, "model", ".net")

    assert selected == only


def test_artifact_selection_rejects_ambiguous_variants(tmp_path):
    (tmp_path / "model_burnin.net").write_text("phase 1", encoding="utf-8")
    (tmp_path / "model_cont.net").write_text("phase 2", encoding="utf-8")

    selected = oracle_perl._select_artifact(tmp_path, "model", ".net")

    assert selected is None


def test_network_oracle_can_skip_nf_simulation(monkeypatch, tmp_path):
    model = tmp_path / "source.bngl"
    model.write_text("", encoding="utf-8")
    output = tmp_path / "output"
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        (output / "source.net").write_text("network", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(oracle_perl, "_bng2_path", lambda: tmp_path / "BNG2.pl")
    monkeypatch.setattr(oracle_perl, "perl_available", lambda: True)
    monkeypatch.setattr(oracle_perl.corpus, "resolve", lambda _name: model)
    monkeypatch.setattr(oracle_perl.subprocess, "run", run)

    net, _, _ = oracle_perl.run_perl(
        "source", output, skip_nfsim=True, network_only=True
    )

    assert net == output / "source.net"
    assert "--no-nfsim" in captured["command"]
    assert "--check" in captured["command"]
    assert "--netgen" in captured["command"]


def test_explicit_staged_source_bypasses_golden_network(monkeypatch, tmp_path):
    staged = tmp_path / "staged" / "model.bngl"
    staged.parent.mkdir()
    staged.write_text("begin model\nend model\n", encoding="utf-8")
    golden = tmp_path / "model.net"
    golden.write_text("golden", encoding="utf-8")
    live = tmp_path / "live.net"
    captured = {}

    def run_perl(model_name, work_dir, **kwargs):
        captured.update(model_name=model_name, work_dir=work_dir, **kwargs)
        return live, None, ""

    monkeypatch.setattr(oracle_perl, "golden_net", lambda _name: golden)
    monkeypatch.setattr(oracle_perl, "perl_available", lambda: True)
    monkeypatch.setattr(oracle_perl, "run_perl", run_perl)

    result = oracle_perl.net("model", tmp_path / "output", source_path=staged)

    assert result == (live, "perl")
    assert captured["source_path"] == staged


def test_explicit_staged_source_never_falls_back_to_golden(monkeypatch, tmp_path):
    staged = tmp_path / "model.bngl"
    staged.write_text("begin model\nend model\n", encoding="utf-8")
    golden = tmp_path / "model.net"
    golden.write_text("golden", encoding="utf-8")

    monkeypatch.setattr(oracle_perl, "golden_net", lambda _name: golden)
    monkeypatch.setattr(oracle_perl, "perl_available", lambda: False)

    result = oracle_perl.net("model", tmp_path / "output", source_path=staged)

    assert result == (None, "explicit source requires a live Perl oracle")
