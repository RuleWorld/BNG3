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


def test_ensemble_seed_schedule_spreads_libc_initial_states():
    from scripts import regen_golden

    assert hasattr(
        regen_golden, "ensemble_seeds"
    ), "ensemble seeds need a spread schedule"
    seeds = regen_golden.ensemble_seeds(200)
    assert seeds == regen_golden.ensemble_seeds(200)
    assert len(seeds) == len(set(seeds)) == 200
    assert all(1 <= seed < 2**31 - 1 for seed in seeds)
    # macOS libc's first rand is (16807 * seed) mod (2**31-1).
    # Consecutive seeds 1..200 all produce U<0.002, biasing initial SSA waits.
    uniforms = [(16807 * seed) % (2**31 - 1) / (2**31 - 1) for seed in seeds]
    assert 0.4 < sum(uniforms) / len(uniforms) < 0.6
    assert sum(value < 0.1 for value in uniforms) > 5
    assert sum(value > 0.9 for value in uniforms) > 5


def test_manifest_records_actual_seed_schedule(tmp_path, monkeypatch):
    from scripts import regen_golden
    import json

    monkeypatch.setattr(regen_golden, "ENSEMBLE_EVIDENCE", tmp_path)
    regen_golden._write_ensemble_manifest({}, {}, 200)
    generation = json.loads((tmp_path / "manifest.json").read_text())["generation"]
    assert "seeds" in generation, "a range does not describe the executed spread seeds"
    assert generation["seeds"] == regen_golden.ensemble_seeds(200)
    assert "seed_range" not in generation


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
