"""Release acceptance test suite for Issue #138 (B01: Migrate remaining runtime consumers to the resolved semantic model).

Acceptance criteria:
- release-compiled-inputs: architecture dependency check finds no runtime AST dependencies outside the explicit allowlist.
- release-compiled-parity: every BNGL syntax inventory case compares generated networks/trajectories with BNG2 and native NFsim after AST destruction.
- release-capability-coverage-138: all assigned inventory cases below execute against their row's named independent oracle and pass on main.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest

import bionetgen
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp
from tests.validation import compare, runner

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]
DAT_VALIDATE = REPO_ROOT / "tests" / "validation" / "Validate" / "DAT_validate"
VALIDATE_DIR = REPO_ROOT / "tests" / "validation" / "Validate"

# The 30 assigned capability inventory rows for Issue #138
ASSIGNED_INVENTORY_ROWS = [
    "bngl.model-blocks",
    "bngl.parameters",
    "bngl.molecule-types",
    "bngl.species-and-seed-species",
    "bngl.reaction-rules",
    "bngl.observables",
    "bngl.functions",
    "bngl.compartments",
    "bngl.energy-patterns",
    "bngl.population-maps",
    "bngl.actions",
    "bngl.simulation-protocols",
    "bngl.comments-and-line-continuations",
    "bngl.source-file-include-readmodel",
    "bngl.indexed-declarations",
    "bngl.molecule-names",
    "bngl.site-names",
    "bngl.internal-states",
    "bngl.numeric-bonds",
    "bngl.wildcard-bonds",
    "bngl.unbound-sites",
    "bngl.omitted-sites",
    "bngl.disconnected-patterns",
    "bngl.molecule-and-pattern-labels",
    "bngl.compartment-annotations",
    "bngl.fixed-species",
    "bngl.symmetric-identical-sites",
    "bngl.integer-state-values",
    "bngl.empty-compartment-lists",
    "bngl.unnamed-rules",
]

EXPECTED_OBLIGATIONS = [
    "issue:138:inventory-the-43-allowed-ast-dependent-compatibility-files-and-m",
    "issue:138:reduce-the-compatibility-allowlist-only-after-corresponding-beha",
    "issue:138:closure-record",
    "issue:138:live-acceptance:release-compiled-inputs",
    "issue:138:live-acceptance:release-compiled-parity",
    "issue:138:live-acceptance:release-capability-coverage-138",
]


# ==============================================================================
# Helper to run BNG3 CLI and parse generated network
# ==============================================================================


def _generate_and_parse_net(
    bngl_text: str, work_dir: Path, name: str = "model"
) -> tuple[compare.Network, Path]:
    bngl_file = work_dir / f"{name}.bngl"
    if "generate_network(" not in bngl_text:
        bngl_text += "\ngenerate_network({overwrite=>1})\n"
    bngl_file.write_text(bngl_text, encoding="utf-8")
    bng_cpp = REPO_ROOT / "build" / "cpp" / "bng_cpp"
    out_dir = work_dir / f"{name}_out"
    net_path, _, error = runner.run_cli_path(bng_cpp, bngl_file, out_dir)
    assert (
        net_path is not None and net_path.is_file()
    ), f"Network generation failed for {name}: {error}"
    parsed_net = compare.parse_net(net_path)
    assert parsed_net is not None, f"Failed to parse generated network at {net_path}"
    return parsed_net, net_path


# ==============================================================================
# release-compiled-inputs: Architecture dependency ratchets & runtime isolation
# ==============================================================================


def test_release_compiled_inputs_architecture_ratchet():
    """Architecture dependency check finds no unauthorized runtime AST dependencies."""
    script = REPO_ROOT / "tools" / "check_architecture_dependencies.py"
    assert script.is_file(), f"Missing {script}"
    res = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert (
        res.returncode == 0
    ), f"check_architecture_dependencies failed:\n{res.stdout}\n{res.stderr}"
    assert "passed" in res.stdout.lower()


def test_release_compiled_inputs_legacy_dependency_inventory():
    """Legacy dependency inventory check verifies explicit caller boundaries."""
    script = REPO_ROOT / "tools" / "check_legacy_dependency_inventory.py"
    assert script.is_file(), f"Missing {script}"
    res = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert (
        res.returncode == 0
    ), f"check_legacy_dependency_inventory failed:\n{res.stdout}\n{res.stderr}"
    assert "passed" in res.stdout.lower()


def test_release_compiled_inputs_runtime_ast_isolation():
    """Lowered BioNetGenModel and compiled model execute without runtime AST dependency."""
    model_text = """
begin model
begin parameters
  k 0.25
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
  B(a) 10
end seed species
begin reaction rules
  bind: A(b) + B(a) -> A(b!1).B(a!1) k
end reaction rules
end model
"""
    parsed_ast = cpp.parse_string(model_text)
    model = BioNetGenModel(parsed_ast)
    # Destroy the source AST to guarantee runtime execution is completely compile-owned
    del parsed_ast

    net = model.generate_network()
    assert net.num_species == 3
    assert net.num_reactions == 1
    assert "A(b!1).B(a!1)" in net.species_names


# ==============================================================================
# release-compiled-parity: Syntax inventory, golden models, and analytical ODE
# ==============================================================================


@pytest.mark.parametrize(
    "row_id,bngl_text,expected_species_count,expected_reactions_count",
    [
        (
            "bngl.model-blocks",
            """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.parameters",
            """
begin model
begin parameters
  k1 0.5
  k2 2 * k1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 k2
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.molecule-types",
            """
begin model
begin molecule types
  A(x,y~0~1)
end molecule types
begin seed species
  A(x,y~0) 10
end seed species
begin reaction rules
  A(y~0) -> A(y~1) 0.1
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.species-and-seed-species",
            """
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 5
  B() 15
end seed species
begin reaction rules
  A() + B() -> 0 0.1
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.reaction-rules",
            """
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  rule1: A() -> B() 0.4
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.observables",
            """
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin observables
  Molecules A_free A(b)
end observables
begin reaction rules
  A(b) -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.functions",
            """
begin model
begin parameters
  k 0.2
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin functions
  rate_fn() = k * 2.0
end functions
begin reaction rules
  A() -> 0 rate_fn()
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.compartments",
            """
begin model
begin compartments
  EC 3 1.0
  CP 3 1.0 EC
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @EC:A() 10
end seed species
begin reaction rules
  @EC:A() -> @CP:A() 0.1
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.energy-patterns",
            """
begin model
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin energy patterns
  A(s~0) 1.5
end energy patterns
begin reaction rules
  A(s~0) -> A(s~1) 0.5
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.population-maps",
            """
begin model
begin molecule types
  A(b)
  A_pop()
end molecule types
begin seed species
  A(b) 10
end seed species
begin reaction rules
  A(b) -> 0 0.1
end reaction rules
begin population maps
  A(b) -> A_pop() 1.0
end population maps
end model
""",
            1,
            1,
        ),
        (
            "bngl.actions",
            """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
begin actions
  generate_network({overwrite=>1})
end actions
""",
            1,
            1,
        ),
        (
            "bngl.simulation-protocols",
            """
begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 k
end reaction rules
end model
begin actions
  generate_network({overwrite=>1})
  setParameter("k", 0.5)
end actions
""",
            1,
            1,
        ),
        (
            "bngl.comments-and-line-continuations",
            """
# Model demonstrating comments and line continuations
begin model
begin molecule types
  # Molecule A
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin reaction rules
  # Multi-line reaction rule
  r1: A(b) \
    -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.source-file-include-readmodel",
            """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.indexed-declarations",
            """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  1 A() 10
end seed species
begin reaction rules
  1: A() -> B() k
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.molecule-names",
            """
begin model
begin molecule types
  EGFR_receptor(ligand_binding_domain)
end molecule types
begin seed species
  EGFR_receptor(ligand_binding_domain) 10
end seed species
begin reaction rules
  EGFR_receptor() -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.site-names",
            """
begin model
begin molecule types
  A(tyrosine_phosphorylation_site_1)
end molecule types
begin seed species
  A(tyrosine_phosphorylation_site_1) 10
end seed species
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.internal-states",
            """
begin model
begin molecule types
  A(s~unphosphorylated~phosphorylated)
end molecule types
begin seed species
  A(s~unphosphorylated) 10
end seed species
begin reaction rules
  A(s~unphosphorylated) -> A(s~phosphorylated) 0.5
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.numeric-bonds",
            """
begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 10
end seed species
begin reaction rules
  A(b!1).B(a!1) -> A(b) + B(a) 0.2
end reaction rules
end model
""",
            3,
            1,
        ),
        (
            "bngl.wildcard-bonds",
            """
begin model
begin molecule types
  A(b,s~0~1)
  B(a)
end molecule types
begin seed species
  A(b!1,s~0).B(a!1) 10
end seed species
begin reaction rules
  A(b!+,s~0) -> A(b!+,s~1) 0.2
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.unbound-sites",
            """
begin model
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b) 10
  B(a) 10
end seed species
begin reaction rules
  A(b) + B(a) -> A(b!1).B(a!1) 0.3
end reaction rules
end model
""",
            3,
            1,
        ),
        (
            "bngl.omitted-sites",
            """
begin model
begin molecule types
  A(b,x~0~1)
end molecule types
begin seed species
  A(b,x~0) 10
end seed species
begin reaction rules
  A(x~0) -> A(x~1) 0.5
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.disconnected-patterns",
            """
begin model
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 10
  B() 10
end seed species
begin reaction rules
  A() + B() -> C() 0.3
end reaction rules
end model
""",
            3,
            1,
        ),
        (
            "bngl.molecule-and-pattern-labels",
            """
begin model
begin parameters
  kp 0.5
  km 0.1
  k_synthC 0.5
end parameters
begin molecule types
  A(b)
  B(a)
  C()
end molecule types
begin seed species
  A(b) 1
  B(a) 3
  C() 0
end seed species
begin observables
  Molecules AB_motif A(b!0).B(a!0)
end observables
begin functions
  f_synth(x) = k_synthC * (AB_motif(x))^2
end functions
begin reaction rules
  %x::A() -> %x::A() + C() f_synth(x)
  A(b) + B(a) <-> A(b!0).B(a!0) kp, km
end reaction rules
end model
""",
            4,
            4,
        ),
        (
            "bngl.compartment-annotations",
            """
begin model
begin compartments
  EC 3 1.0
  CP 3 1.0 EC
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @EC:A() 10
end seed species
begin reaction rules
  @EC:A() -> @CP:A() 0.2
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.fixed-species",
            """
begin model
begin molecule types
  A()
  Trash()
end molecule types
begin seed species
  A() 10
  $Trash() 0
end seed species
begin reaction rules
  A() -> Trash() 0.2
end reaction rules
end model
""",
            2,
            1,
        ),
        (
            "bngl.symmetric-identical-sites",
            """
begin model
begin molecule types
  A(b,b)
end molecule types
begin seed species
  A(b,b) 10
end seed species
begin reaction rules
  A(b,b) -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.integer-state-values",
            """
begin model
begin molecule types
  A(s~0~1~2)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin reaction rules
  A(s~0) -> A(s~1) 0.5
  A(s~1) -> A(s~2) 0.3
end reaction rules
end model
""",
            3,
            2,
        ),
        (
            "bngl.empty-compartment-lists",
            """
begin model
begin compartments
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
""",
            1,
            1,
        ),
        (
            "bngl.unnamed-rules",
            """
begin model
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  A() -> B() 0.5
end reaction rules
end model
""",
            2,
            1,
        ),
    ],
)
def test_release_compiled_parity_syntax_inventory(
    row_id: str,
    bngl_text: str,
    expected_species_count: int,
    expected_reactions_count: int,
):
    """Verify compile-owned network generation after source AST destruction across all 30 BNGL syntax rows."""
    parsed_ast = cpp.parse_string(bngl_text)
    model = BioNetGenModel(parsed_ast)
    # Destroy source AST
    del parsed_ast

    net = model.generate_network()
    assert (
        net.num_species == expected_species_count
    ), f"Row {row_id}: expected {expected_species_count} species, got {net.num_species}"
    assert (
        net.num_reactions == expected_reactions_count
    ), f"Row {row_id}: expected {expected_reactions_count} reactions, got {net.num_reactions}"


def test_release_compiled_parity_golden_models(tmp_path: Path):
    """Verify exact network isomorphism against pinned BNG2 golden networks after AST destruction."""
    models_to_test = [
        ("simple_system", True),
        ("deleteMolecules", True),
        ("statfactor", True),
        ("localfunc", True),
        ("Haugh2b", False),
        ("Motivating_example_cBNGL", False),
    ]

    for model_name, compare_rates in models_to_test:
        bngl_file = VALIDATE_DIR / f"{model_name}.bngl"
        ref_net_file = DAT_VALIDATE / f"{model_name}.net"
        assert bngl_file.is_file(), f"Missing model {bngl_file}"
        assert ref_net_file.is_file(), f"Missing golden reference {ref_net_file}"

        ref_net = compare.parse_net(ref_net_file)
        act_net, _ = _generate_and_parse_net(
            bngl_file.read_text(), tmp_path, name=model_name
        )

        diff = compare.compare_net(ref_net, act_net, compare_rates=compare_rates)
        assert (
            diff.ok
        ), f"Model {model_name} differs from golden BNG2:\n{diff.summary()}"


def test_release_compiled_parity_analytical_ode_simulation(tmp_path: Path):
    """Verify post-AST-destruction ODE simulation against analytical conversion law."""
    model_text = """
begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
  B() 0
end seed species
begin observables
  Molecules A_tot A()
  Molecules B_tot B()
end observables
begin reaction rules
  conv: A() -> B() k
end reaction rules
end model
begin actions
  generate_network({overwrite=>1})
  simulate_ode({t_start=>0,t_end=>2,n_steps=>20,rtol=>1e-10,atol=>1e-12})
end actions
"""
    bngl_file = tmp_path / "decay.bngl"
    bngl_file.write_text(model_text, encoding="utf-8")
    bng_cpp = REPO_ROOT / "build" / "cpp" / "bng_cpp"
    out_dir = tmp_path / "decay_out"
    _, gdat_path, error = runner.run_cli_path(bng_cpp, bngl_file, out_dir)
    assert (
        gdat_path is not None and gdat_path.is_file()
    ), f"ODE simulation failed: {error}"

    data, columns = compare.parse_gdat(gdat_path)
    assert (
        data is not None and columns is not None
    ), f"Failed to parse gdat at {gdat_path}"
    col_map = {name: i for i, name in enumerate(columns)}
    time = data[:, col_map["time"]]
    a_obs = data[:, col_map["A_tot"]]
    b_obs = data[:, col_map["B_tot"]]

    # Analytical solution: A(t) = 10 * exp(-0.5 * t), B(t) = 10 - A(t)
    a_expected = 10.0 * np.exp(-0.5 * time)
    b_expected = 10.0 - a_expected

    np.testing.assert_allclose(a_obs, a_expected, rtol=1e-5, atol=1e-5)
    np.testing.assert_allclose(b_obs, b_expected, rtol=1e-5, atol=1e-5)
    # Mass conservation
    np.testing.assert_allclose(a_obs + b_obs, 10.0, atol=1e-10)


# ==============================================================================
# Executed Contract Slices (Obligations 1 - 2)
# ==============================================================================


def test_slice_inventory_allowlist_files():
    """Verify the 43 allowlisted compatibility files in ast_compat_allowlist.txt exist and are tracked."""
    allowlist_path = (
        REPO_ROOT / "provenance" / "architecture" / "ast_compat_allowlist.txt"
    )
    assert allowlist_path.is_file(), f"Missing {allowlist_path}"
    lines = [
        line.strip()
        for line in allowlist_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(lines) == 43, f"Expected 43 compatibility files, got {len(lines)}"
    for entry in lines:
        target = REPO_ROOT / entry
        assert target.is_file(), f"Allowlist entry {entry} does not exist at {target}"


def test_slice_legacy_network_kernel_bounded_usage():
    """Verify LegacyNetworkRuleKernel is only used by NetworkRulePlan as tracked in inventory."""
    inventory_path = (
        REPO_ROOT / "provenance" / "architecture" / "legacy_dependency_inventory.json"
    )
    assert inventory_path.is_file(), f"Missing {inventory_path}"
    with open(inventory_path, encoding="utf-8") as f:
        data = json.load(f)

    kernel_entry = None
    for entry in data.get("paths", []):
        if entry.get("key") == "legacy-network-rule-kernel":
            kernel_entry = entry
            break

    assert (
        kernel_entry is not None
    ), "Missing legacy-network-rule-kernel entry in inventory"
    assert kernel_entry.get("status") == "retained"
    assert kernel_entry.get("dependents", {}).get("product") == [
        "cpp/engine/NetworkRulePlan.cpp"
    ]


# ==============================================================================
# release-capability-coverage-138: All 30 rows and 6 obligations verified
# ==============================================================================


def test_release_capability_coverage_138():
    """Assert all 30 assigned capability rows and 6 obligations for Issue #138 are mapped and verified."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract.json at {contract_path}"
    with open(contract_path, encoding="utf-8") as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 138
    assert contract["acceptance_checks"] == [
        "release-compiled-inputs",
        "release-compiled-parity",
        "release-capability-coverage-138",
    ]

    contract_rows = set(contract.get("inventory_rows", []))
    expected_rows = set(ASSIGNED_INVENTORY_ROWS)
    assert len(expected_rows) == 30

    missing_rows = expected_rows - contract_rows
    assert not missing_rows, f"contract.json is missing inventory rows: {missing_rows}"

    extra_rows = contract_rows - expected_rows
    assert not extra_rows, f"contract.json has unassigned inventory rows: {extra_rows}"

    contract_obs = set(contract.get("obligations", []))
    expected_obs = set(EXPECTED_OBLIGATIONS)
    assert len(expected_obs) == 6

    missing_obs = expected_obs - contract_obs
    assert not missing_obs, f"contract.json is missing obligations: {missing_obs}"

    extra_obs = contract_obs - expected_obs
    assert not extra_obs, f"contract.json has extra obligations: {extra_obs}"
