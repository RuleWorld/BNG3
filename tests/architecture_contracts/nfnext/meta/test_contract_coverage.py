#!/usr/bin/env python3
"""Meta-test: every proposed NFnext architecture area has substantial RED contracts."""
from __future__ import annotations
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1] / "future_contract"
MIN_CASES_PER_FILE = 10
REQUIRED = {
    "test_nfir_canonicalization_contract.cpp": "canonical NFIR",
    "test_rule_family_contract.cpp": "rule-family collapse",
    "test_dependency_scheduler_contract.cpp": "dependency DAG/scheduler",
    "test_generic_matcher_contract.cpp": "generic graph matcher",
    "test_transformations_contract.cpp": "transformations",
    "test_lattice_interval_contract.cpp": "lattice/interval genome",
    "test_population_hybrid_contract.cpp": "population/hybrid",
    "test_observable_function_contract.cpp": "observables/functions",
    "test_xml_adapter_contract.cpp": "XML adapter",
    "test_cache_contract.cpp": "cache",
    "test_rng_replay_concurrency_contract.cpp": "RNG/replay/concurrency",
    "test_differential_oracle_contract.cpp": "legacy differential oracle",
    "test_compartment_rate_contract.cpp": "compartments/rate laws",
    "test_backend_equivalence_contract.cpp": "backend equivalence",
    "test_memory_arena_contract.cpp": "SoA arena/allocation",
    "test_scaling_stress_contract.cpp": "scaling stress",
    "test_fuzz_metamorphic_contract.cpp": "fuzz/metamorphic",
    "test_codegen_accelerator_contract.cpp": "native/SIMD/GPU",
    "test_rasi_translation_contract.cpp": "Rasi translation",
}


def main() -> int:
    failures = []
    total = 0
    for filename, area in REQUIRED.items():
        p = ROOT / filename
        if not p.exists():
            failures.append(f"missing {filename} ({area})")
            continue
        text = p.read_text(errors="replace")
        cases = len(re.findall(r"\bCONTRACT_CASE\s*\(", text))
        total += cases
        print(f"{filename}: {cases} cases [{area}]")
        if cases < MIN_CASES_PER_FILE:
            failures.append(f"{filename}: only {cases} cases; require >= {MIN_CASES_PER_FILE}")
        if "#error \"RED CONTRACT:" not in text:
            failures.append(f"{filename}: missing explicit RED-contract error for absent API")
    print(f"total_future_contract_cases={total}")
    if failures:
        print("FAIL:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
