from pathlib import Path
import json
from scripts.nf_energy_statistical_parity import Thresholds

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "fixtures/energy/validation_policy.json").read_text())


def test_policy_matches_statistical_harness_defaults():
    t = Thresholds()
    s = POLICY["stochastic"]
    assert t.mean_z == s["mean_z_max"]
    assert t.variance_ratio_low == s["variance_ratio_low"]
    assert t.variance_ratio_high == s["variance_ratio_high"]
    assert t.tv == s["small_support_tv_max"]
    assert t.ks == s["broad_support_ks_max"]
    assert t.max_tv_support == s["max_tv_support"]


def test_policy_has_stricter_large_context_performance_gate_than_disabled_overhead():
    p = POLICY["performance"]
    assert p["predicate_count_for_class_gate"] >= 6
    assert p["min_reaction_class_reduction"] >= 16
    assert p["disabled_runtime_ratio_max"] <= 1.02
