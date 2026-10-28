from pathlib import Path

from scripts.regen_golden import ensemble_model_source


def test_ensemble_model_source_uses_clean_definition_and_fixed_seed_actions():
    original = """begin model
begin parameters
    k 1
end parameters
end model

## actions ##
simulate_ssa({t_end=>999,n_steps=>1})
"""

    generated = ensemble_model_source(original, seeds=range(1, 3), t_end=10, n_steps=50)

    assert generated.startswith("begin model\n")
    assert "k 1" in generated
    assert "t_end=>999" not in generated
    assert generated.count("resetConcentrations()") == 2
    assert 'suffix=>"seed_0001",seed=>1' in generated
    assert 'suffix=>"seed_0002",seed=>2' in generated
    assert generated.count("t_end=>10,n_steps=>50") == 2


def test_ensemble_model_source_supports_models_without_outer_end_model():
    original = """begin parameters
    k 1
end parameters
begin reaction rules
    A() -> B() k
end reaction rules
simulate_ode({t_end=>1})
"""

    generated = ensemble_model_source(original, seeds=range(1, 2), t_end=10, n_steps=50)

    assert "A() -> B() k" in generated
    assert "simulate_ode" not in generated
    assert 'suffix=>"seed_0001",seed=>1' in generated


def test_ensemble_seed_schedule_is_the_frozen_contract():
    from scripts import regen_golden

    # tests/test_ci_contract.py and the committed manifest pin seeds 1..200.
    assert regen_golden.ensemble_seeds(200) == list(range(1, 201))
    assert regen_golden.ensemble_seeds(1) == [1]


def test_first_draw_check_rejects_a_lehmer_c_library():
    import pytest
    from scripts import regen_golden

    seeds = regen_golden.ensemble_seeds(200)
    # macOS libc's first rand() after srand(seed) is (16807 * seed) mod (2**31-1),
    # so seeds 1..200 all give a first uniform below 0.002.
    lehmer = [(16807 * seed) % (2**31 - 1) / (2**31 - 1) for seed in seeds]
    with pytest.raises(RuntimeError, match="not uniform over seeds 1..200"):
        regen_golden.check_seed_first_draws(seeds, draws=lehmer)


def test_first_draw_check_accepts_uniform_first_draws():
    from scripts import regen_golden

    seeds = regen_golden.ensemble_seeds(200)
    # A fixed, evenly spread set of uniforms (the midpoints of 200 bins).
    draws = [(index + 0.5) / 200 for index in range(200)]
    summary = regen_golden.check_seed_first_draws(seeds, draws=draws)
    assert summary["seed_count"] == 200
    assert summary["ks_pvalue"] > 0.99


def test_uniform_ks_test_matches_the_exact_statistic():
    from scripts import regen_golden

    statistic, pvalue = regen_golden._uniform_ks_test([0.1, 0.2, 0.9])
    # D = max(i/n - x_(i), x_(i) - (i-1)/n) = 2/3 - 0.2 = 0.4666...
    assert abs(statistic - (2 / 3 - 0.2)) < 1e-12
    assert 0.0 < pvalue < 1.0


def test_manifest_records_the_frozen_seed_range(tmp_path, monkeypatch):
    from scripts import regen_golden
    import json

    monkeypatch.setattr(regen_golden, "ENSEMBLE_EVIDENCE", tmp_path)
    regen_golden._write_ensemble_manifest(
        {}, {}, 200, {"c_library": "supplied", "ks_pvalue": 0.5}
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    generation = manifest["generation"]
    assert manifest["schema_version"] == 1
    assert generation["seed_range"] == [1, 200]
    assert "seeds" not in generation and "seed_schedule" not in generation
    assert generation["c_library_first_draws"]["c_library"] == "supplied"


def test_regeneration_refuses_a_biased_c_library(monkeypatch, capsys, tmp_path):
    from scripts import regen_golden

    monkeypatch.setattr(regen_golden, "_bng2_oracle_identity", lambda **_: {})
    monkeypatch.setattr(regen_golden.oracle_perl, "perl_available", lambda: True)
    monkeypatch.setattr(regen_golden, "GOLDEN", tmp_path / "golden")

    def biased(seeds):
        return [(16807 * seed) % (2**31 - 1) / (2**31 - 1) for seed in seeds], "lehmer"

    monkeypatch.setattr(regen_golden, "_c_library_first_draws", biased)
    assert regen_golden.regen(["simple_system"], 200) == 2
    assert "not uniform" in capsys.readouterr().err
    assert not (tmp_path / "golden").exists()


def test_golden_regeneration_rejects_unpinned_bng2(monkeypatch, tmp_path, capsys):
    from scripts import regen_golden

    monkeypatch.setattr(
        regen_golden,
        "_bng2_oracle_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("BNG2 revision is not locked")),
    )
    monkeypatch.setattr(regen_golden, "GOLDEN", tmp_path / "golden")

    assert regen_golden.regen(["simple_system"], 0) == 2
    assert "revision is not locked" in capsys.readouterr().err
    assert not (tmp_path / "golden").exists()


def test_live_ensemble_uses_the_fingerprinted_bng2_root(tmp_path, monkeypatch):
    import numpy as np
    from scripts import regen_golden
    from tests.validation import compare, corpus

    bng2 = tmp_path / "pinned-bng2" / "BNG2.pl"
    wrong_root = tmp_path / "other-bng2"
    monkeypatch.setenv("BNGPATH", str(wrong_root))
    captured = {}

    def run_oracle(command, **kwargs):
        captured.update(command=command, **kwargs)
        output_dir = Path(command[command.index("--outdir") + 1])
        stem = Path(command[-1]).stem
        for seed in regen_golden.ensemble_seeds(2):
            (output_dir / f"{stem}_seed_{seed:04d}.gdat").write_text("stub")
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(regen_golden.subprocess, "run", run_oracle)
    monkeypatch.setattr(
        compare,
        "parse_gdat",
        lambda path: (
            np.zeros((regen_golden.ENSEMBLE_N_STEPS + 1, 2)),
            ["time", "A"],
        ),
    )
    source = corpus.resolve("simple_system")
    assert source is not None

    regen_golden._generate_ensemble(
        "simple_system",
        2,
        {"BNG2_PERL": str(bng2)},
        destination_root=tmp_path / "scratch",
    )

    assert captured["env"]["BNGPATH"] == str(bng2.parent)
