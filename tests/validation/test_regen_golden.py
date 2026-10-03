import hashlib
import json
from pathlib import Path

from scripts.regen_golden import ENSEMBLE_EVIDENCE, GOLDEN, ensemble_model_source
from tests.validation import corpus


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


def test_committed_ensemble_members_match_the_pinned_manifest():
    manifest = json.loads((ENSEMBLE_EVIDENCE / "manifest.json").read_text())
    generation = manifest["generation"]
    run_count = generation["seed_range"][1]

    assert generation["seed_range"] == [1, 200]
    assert generation["reset_before_each_member"] is True
    assert set(manifest["models"]) == {"gene_expr", "michment", "simple_system"}

    for model_name, model in manifest["models"].items():
        source = corpus.resolve(model_name)
        assert source is not None
        source = Path(source).resolve()
        assert source.relative_to(corpus.REPO).as_posix() == model["source_path"]
        assert _sha256(source) == model["source_sha256"]
        wrapper = ensemble_model_source(
            source.read_text(encoding="utf-8"),
            seeds=range(1, run_count + 1),
            t_end=generation["t_end"],
            n_steps=generation["n_steps"],
        )
        assert (
            hashlib.sha256(wrapper.encode("utf-8")).hexdigest()
            == model["wrapper_sha256"]
        )
        assert model["member_count"] == run_count
        assert [member["seed"] for member in model["members"]] == list(
            range(1, run_count + 1)
        )

        aggregate = hashlib.sha256()
        reference_dir = GOLDEN / f"{model_name}.ens"
        for member in model["members"]:
            relative = Path(member["path"])
            assert relative.name == member["path"]
            artifact = reference_dir / relative
            data = artifact.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            assert len(data) == member["bytes"]
            assert digest == member["sha256"]
            aggregate.update(f"{member['path']}\t{digest}\n".encode("utf-8"))
        assert aggregate.hexdigest() == model["aggregate_sha256"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
