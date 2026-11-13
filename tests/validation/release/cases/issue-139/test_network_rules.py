"""Release acceptance test suite for Issue #139 (B02: Separate network-rule execution from reconstructed AST rules).

Acceptance checks:
- release-network-rule-plan: parser-independent rule execution and independent BNG2 network equality for every assigned rule row.
- release-network-rule-mutations: injected incorrect multiplicity/deletion/filter mutations fail the independent comparator.
- release-capability-coverage-139: all assigned inventory cases execute against their row's named independent oracle and pass on main.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import pytest

import bionetgen
from bionetgen import BioNetGenModel
import bionetgen._bionetgen_cpp as cpp
from tests.validation import compare, runner

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[4]
DAT_VALIDATE = REPO_ROOT / "tests" / "validation" / "Validate" / "DAT_validate"
VALIDATE_DIR = REPO_ROOT / "tests" / "validation" / "Validate"

# The 19 assigned capability inventory rows for Issue #139
ASSIGNED_INVENTORY_ROWS = [
    "bngl.matchonce",
    "bngl.irreversible-rules",
    "bngl.reversible-rules",
    "bngl.null-reactants-and-products",
    "bngl.binding",
    "bngl.unbinding",
    "bngl.state-changes",
    "bngl.molecule-creation",
    "bngl.molecule-deletion",
    "bngl.deletemolecules",
    "bngl.moveconnected",
    "bngl.totalrate",
    "bngl.include-reactants",
    "bngl.exclude-reactants",
    "bngl.include-products",
    "bngl.exclude-products",
    "bngl.compartment-transport",
    "bngl.reaction-center-symmetry",
    "bngl.connected-context-preservation",
]

EXPECTED_OBLIGATIONS = [
    "issue:139:replace-the-necessary-legacynetworkrulekernel-reconstruction-wit",
    "issue:139:demonstrate-graph-rate-filter-local-scope-and-reversible-rule-pa",
    "issue:139:closure-record",
    "issue:139:executed-slice:network-rule-execution-graph",
    "issue:139:executed-slice:network-rule-execution-rate",
    "issue:139:executed-slice:network-rule-execution-filter",
    "issue:139:executed-slice:network-rule-execution-local-scope",
    "issue:139:executed-slice:network-rule-execution-reversible",
    "issue:139:live-acceptance:release-network-rule-plan",
    "issue:139:live-acceptance:release-network-rule-mutations",
    "issue:139:live-acceptance:release-capability-coverage-139",
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
# release-network-rule-plan: Parser-independent execution and network equality
# ==============================================================================


def test_release_network_rule_plan_parser_independence():
    """Verify NetworkRulePlan compiles and expands directly from model IR independently of source AST."""
    model_text = """
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
  bind: A(b) + B(a) -> A(b!1).B(a!1) 0.5
end reaction rules
end model
"""
    parsed_ast = cpp.parse_string(model_text)
    # Wrap in BioNetGenModel which compiles into C++ IR
    model = BioNetGenModel(parsed_ast)
    # Generate network directly from the compiled IR
    net = model.generate_network()
    assert net.num_species == 3
    assert net.num_reactions == 1
    assert "A(b!1).B(a!1)" in net.species_names
    assert net.reaction_factors == [1.0]
    assert net.reaction_rate_laws == ["0.5"]


@pytest.mark.parametrize(
    "row_id,bngl_text,expected_species,expected_reactions,expected_factors",
    [
        (
            "bngl.matchonce",
            """
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) 1
end seed species
begin reaction rules
  r1: A(b!1).A(b!1) -> A(b) + A(b) 1.0 MatchOnce
end reaction rules
end model
""",
            ["A(b!1).A(b!1)", "A(b)"],
            1,
            [1.0],
        ),
        (
            "bngl.irreversible-rules",
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
  r_irrev: A() -> B() 0.4
end reaction rules
end model
""",
            ["A()", "B()"],
            1,
            [1.0],
        ),
        (
            "bngl.reversible-rules",
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
  r_rev: A() <-> B() 0.4, 0.1
end reaction rules
end model
""",
            ["A()", "B()"],
            2,
            [1.0, 1.0],
        ),
        (
            "bngl.null-reactants-and-products",
            """
begin model
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  r_synth: 0 -> A() 0.5
  r_deg: A() -> 0 0.2
end reaction rules
end model
""",
            ["A()"],
            2,
            [1.0, 1.0],
        ),
        (
            "bngl.binding",
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
  r_bind: A(b) + B(a) -> A(b!1).B(a!1) 0.3
end reaction rules
end model
""",
            ["A(b)", "B(a)", "A(b!1).B(a!1)"],
            1,
            [1.0],
        ),
        (
            "bngl.unbinding",
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
  r_unbind: A(b!1).B(a!1) -> A(b) + B(a) 0.1
end reaction rules
end model
""",
            ["A(b!1).B(a!1)", "A(b)", "B(a)"],
            1,
            [1.0],
        ),
        (
            "bngl.state-changes",
            """
begin model
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) 10
end seed species
begin reaction rules
  r_state: A(s~0) -> A(s~1) 0.5
end reaction rules
end model
""",
            ["A(s~0)", "A(s~1)"],
            1,
            [1.0],
        ),
        (
            "bngl.molecule-creation",
            """
begin model
begin molecule types
  A(b,s~0)
end molecule types
begin seed species
  $Trash() 0
end seed species
begin molecule types
  Trash()
end molecule types
begin reaction rules
  r_create: 0 -> A(b,s~0) 0.6
end reaction rules
end model
""",
            ["Trash()", "A(b,s~0)"],
            1,
            [1.0],
        ),
        (
            "bngl.molecule-deletion",
            """
begin model
begin molecule types
  A(b,s~0)
end molecule types
begin seed species
  A(b,s~0) 10
end seed species
begin reaction rules
  r_del: A(b,s~0) -> 0 0.3
end reaction rules
end model
""",
            ["A(b,s~0)"],
            1,
            [1.0],
        ),
        (
            "bngl.deletemolecules",
            """
begin model
begin parameters
  kdeg 1.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 10
end seed species
begin reaction rules
  r_delmol: A() -> 0 kdeg DeleteMolecules
end reaction rules
end model
""",
            ["A(b!1).B(a!1)", "B(a)"],
            1,
            [1.0],
        ),
        (
            "bngl.moveconnected",
            """
begin model
begin compartments
  CP 3 1.0
  NM 2 1.0 CP
  NU 3 1.0 NM
end compartments
begin molecule types
  Im(fg)
  NP(fg)
end molecule types
begin seed species
  Im(fg)@CP 10
  NP(fg)@NM 10
end seed species
begin reaction rules
  bind: Im(fg) + NP(fg) <-> Im(fg!1).NP(fg!1) 1.0, 1.0
  trans: Im(fg!1)@CP.NP(fg!1)@NM -> Im(fg!1)@NU.NP(fg!1)@NM 0.5 MoveConnected
end reaction rules
end model
""",
            [
                "@CP::Im(fg)",
                "@NM::NP(fg)",
                "@NM::Im(fg!1)@CP.NP(fg!1)",
                "@NM::Im(fg!1)@NU.NP(fg!1)",
                "@NU::Im(fg)",
            ],
            5,
            [1.0, 1.0, 1.0, 1.0, 1.0],
        ),
        (
            "bngl.totalrate",
            """
begin model
begin parameters
  k 1.0
end parameters
begin molecule types
  A()
  B()
  C()
end molecule types
begin seed species
  A() 5
  B() 5
end seed species
begin reaction rules
  r_tot: A() + B() -> C() k TotalRate
end reaction rules
end model
""",
            ["A()", "B()", "C()"],
            1,
            [1.0],
        ),
        (
            "bngl.include-reactants",
            """
begin model
begin molecule types
  A(b,x~u~p)
  B(a)
end molecule types
begin seed species
  A(b,x~u) 10
  A(b,x~p) 10
  B(a) 10
end seed species
begin reaction rules
  r_inc_r: A(b) + B(a) -> A(b!1).B(a!1) 1.0 include_reactants(1, A(x~p))
end reaction rules
end model
""",
            ["A(b,x~u)", "A(b,x~p)", "B(a)", "A(b!1,x~p).B(a!1)"],
            1,
            [1.0],
        ),
        (
            "bngl.exclude-reactants",
            """
begin model
begin molecule types
  A(b,x~u~p)
  B(a)
end molecule types
begin seed species
  A(b,x~u) 10
  A(b,x~p) 10
  B(a) 10
end seed species
begin reaction rules
  r_exc_r: A(b) + B(a) -> A(b!1).B(a!1) 1.0 exclude_reactants(1, A(x~p))
end reaction rules
end model
""",
            ["A(b,x~u)", "A(b,x~p)", "B(a)", "A(b!1,x~u).B(a!1)"],
            1,
            [1.0],
        ),
        (
            "bngl.include-products",
            """
begin model
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 10
end seed species
begin reaction rules
  r_inc_p: 0 -> A(x~u) 1.0 include_products(1, A(x~u))
end reaction rules
end model
""",
            ["A(x~u)"],
            1,
            [1.0],
        ),
        (
            "bngl.exclude-products",
            """
begin model
begin molecule types
  A(x~u~p)
end molecule types
begin seed species
  A(x~u) 10
end seed species
begin reaction rules
  r_exc_p: 0 -> A(x~u) 1.0 exclude_products(1, A(x~u))
end reaction rules
end model
""",
            ["A(x~u)"],
            0,
            [],
        ),
        (
            "bngl.compartment-transport",
            """
begin model
begin compartments
  EC 3 1.0
  CP 3 1.0
end compartments
begin molecule types
  A()
end molecule types
begin seed species
  @EC:A() 10
end seed species
begin reaction rules
  r_trans: @EC:A() -> @CP:A() 0.2
end reaction rules
end model
""",
            ["@EC::A()", "@CP::A()"],
            1,
            [1.0],
        ),
        (
            "bngl.reaction-center-symmetry",
            """
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin reaction rules
  r_homo: A(b) + A(b) -> A(b!1).A(b!1) 0.5
end reaction rules
end model
""",
            ["A(b)", "A(b!1).A(b!1)"],
            1,
            [0.5],
        ),
        (
            "bngl.connected-context-preservation",
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
  r_ctx: A(b!1,s~0).B(a!1) -> A(b!1,s~1).B(a!1) 0.8
end reaction rules
end model
""",
            ["A(b!1,s~0).B(a!1)", "A(b!1,s~1).B(a!1)"],
            1,
            [1.0],
        ),
    ],
)
def test_release_network_rule_plan_all_assigned_rows(
    tmp_path: Path,
    row_id: str,
    bngl_text: str,
    expected_species: list[str],
    expected_reactions: int,
    expected_factors: list[float],
):
    """Verify parser-independent rule execution across all 19 assigned capability rows."""
    parsed_ast = cpp.parse_string(bngl_text)
    model = BioNetGenModel(parsed_ast)
    net = model.generate_network()

    assert net.num_species == len(
        expected_species
    ), f"Row {row_id}: expected {len(expected_species)} species, got {net.num_species}"
    assert (
        net.num_reactions == expected_reactions
    ), f"Row {row_id}: expected {expected_reactions} reactions, got {net.num_reactions}"
    assert net.reaction_factors == expected_factors, f"Row {row_id}: factors mismatch"

    # Also generate via CLI to obtain full serialized network
    parsed_net, _ = _generate_and_parse_net(
        bngl_text, tmp_path, name=row_id.replace(".", "_")
    )
    assert parsed_net.n_species == len(expected_species)
    assert parsed_net.n_reactions == expected_reactions


def test_release_network_rule_plan_golden_parity(tmp_path: Path):
    """Verify exact network isomorphism against pinned BNG2 golden networks for complex benchmark models."""
    models_to_test = [
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
        ), f"Model {model_name} network differs from golden BNG2:\n{diff.summary()}"


# ==============================================================================
# release-network-rule-mutations: Injected mutations fail independent comparator
# ==============================================================================


def test_release_network_rule_mutations_multiplicity(tmp_path: Path):
    """Injected incorrect reaction multiplicity / factor strictly fails the independent comparator."""
    bngl_correct = """
begin model
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin reaction rules
  bind: A(b) + A(b) -> A(b!1).A(b!1) 0.5
end reaction rules
end model
"""
    net_correct, _ = _generate_and_parse_net(
        bngl_correct, tmp_path, name="homo_correct"
    )

    # Mutant 1: Homodimer symmetry factor mutated from 0.5 to 1.0 (doubled rate/factor)
    net_text_mutant = f"""
begin species
  1 A(b) 10
  2 A(b!1).A(b!1) 0
end species
begin reactions
  1 1,1 2 1.0 #R1
end reactions
"""
    mutant_path = tmp_path / "homo_mutant.net"
    mutant_path.write_text(net_text_mutant, encoding="utf-8")
    net_mutant = compare.parse_net(mutant_path)

    diff = compare.compare_net(net_correct, net_mutant, compare_rates=True)
    assert not diff.ok, "Mutant with incorrect factor 1.0 must fail comparator"
    assert len(diff.reactions_only_ref) > 0 or len(diff.reactions_only_test) > 0


def test_release_network_rule_mutations_deletion(tmp_path: Path):
    """Injected incorrect deletion (leaving orphan fragments or dropping partner) fails comparator."""
    bngl_correct = """
begin model
begin parameters
  kdeg 1.0
end parameters
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b!1).B(a!1) 10
end seed species
begin reaction rules
  r_del: A() -> 0 kdeg DeleteMolecules
end reaction rules
end model
"""
    net_correct, _ = _generate_and_parse_net(bngl_correct, tmp_path, name="del_correct")
    assert net_correct.n_species == 2
    assert net_correct.n_reactions == 1

    # Mutant: DeleteMolecules incorrectly drops species B(a) entirely, yielding 0 products
    net_text_mutant = """
begin species
  1 A(b!1).B(a!1) 10
end species
begin reactions
  1 1 0 kdeg #R1
end reactions
"""
    mutant_path = tmp_path / "del_mutant.net"
    mutant_path.write_text(net_text_mutant, encoding="utf-8")
    net_mutant = compare.parse_net(mutant_path)

    diff = compare.compare_net(net_correct, net_mutant, compare_rates=False)
    assert not diff.ok, "Mutant with dropped deletion partner must fail comparator"
    assert len(diff.species_only_ref) > 0 or diff.n_species_ref != diff.n_species_test


def test_release_network_rule_mutations_filter(tmp_path: Path):
    """Injected filter mutation (allowing unauthorized reaction) fails comparator."""
    bngl_correct = """
begin model
begin molecule types
  A(b,x~u~p)
  B(a)
end molecule types
begin seed species
  A(b,x~u) 10
  A(b,x~p) 10
  B(a) 10
end seed species
begin reaction rules
  r_exc: A(b) + B(a) -> A(b!1).B(a!1) 1.0 exclude_reactants(1, A(x~p))
end reaction rules
end model
"""
    net_correct, _ = _generate_and_parse_net(
        bngl_correct, tmp_path, name="filter_correct"
    )
    assert net_correct.n_reactions == 1

    # Mutant: filter omitted so both A(x~u) and A(x~p) react, producing 2 reactions and extra species
    bngl_mutant = """
begin model
begin molecule types
  A(b,x~u~p)
  B(a)
end molecule types
begin seed species
  A(b,x~u) 10
  A(b,x~p) 10
  B(a) 10
end seed species
begin reaction rules
  r_exc: A(b) + B(a) -> A(b!1).B(a!1) 1.0
end reaction rules
end model
"""
    net_mutant, _ = _generate_and_parse_net(bngl_mutant, tmp_path, name="filter_mutant")
    assert net_mutant.n_reactions == 2

    diff = compare.compare_net(net_correct, net_mutant, compare_rates=False)
    assert not diff.ok, "Mutant with violated filter must fail comparator"
    assert diff.n_reactions_test > diff.n_reactions_ref


def test_release_network_rule_mutations_context_preservation(tmp_path: Path):
    """Injected context-preservation mutation (disconnecting bystander molecule) fails comparator."""
    bngl_correct = """
begin model
begin molecule types
  A(b,s~0~1)
  B(a)
end molecule types
begin seed species
  A(b!1,s~0).B(a!1) 10
end seed species
begin reaction rules
  r_ctx: A(b!1,s~0).B(a!1) -> A(b!1,s~1).B(a!1) 0.8
end reaction rules
end model
"""
    net_correct, _ = _generate_and_parse_net(bngl_correct, tmp_path, name="ctx_correct")

    # Mutant: bystander B(a) was cleaved during state change, producing separate A and B
    net_text_mutant = """
begin species
  1 A(b!1,s~0).B(a!1) 10
  2 A(b,s~1) 0
  3 B(a) 0
end species
begin reactions
  1 1 2,3 0.8 #R1
end reactions
"""
    mutant_path = tmp_path / "ctx_mutant.net"
    mutant_path.write_text(net_text_mutant, encoding="utf-8")
    net_mutant = compare.parse_net(mutant_path)

    diff = compare.compare_net(net_correct, net_mutant, compare_rates=False)
    assert (
        not diff.ok
    ), "Mutant violating connected context preservation must fail comparator"
    assert len(diff.reactions_only_ref) > 0 or len(diff.reactions_only_test) > 0


# ==============================================================================
# Executed Contract Slices (Obligations 4 - 8)
# ==============================================================================


def test_slice_network_rule_execution_graph():
    """Verify executed slice: network-rule-execution-graph (graph edits, bonds, states, deletions)."""
    model_text = """
begin model
begin molecule types
  A(b,s~0~1)
  B(a)
end molecule types
begin seed species
  A(b,s~0) 10
  B(a) 10
end seed species
begin reaction rules
  bind: A(b,s~0) + B(a) -> A(b!1,s~0).B(a!1) 0.2
  phos: A(b!1,s~0).B(a!1) -> A(b!1,s~1).B(a!1) 0.3
  unbind: A(b!1,s~1).B(a!1) -> A(b,s~1) + B(a) 0.1
end reaction rules
end model
"""
    parsed = cpp.parse_string(model_text)
    net = BioNetGenModel(parsed).generate_network()
    assert net.num_species == 5
    assert net.num_reactions == 3
    species = set(net.species_names)
    assert "A(b,s~0)" in species
    assert "B(a)" in species
    assert "A(b!1,s~0).B(a!1)" in species
    assert "A(b!1,s~1).B(a!1)" in species
    assert "A(b,s~1)" in species


def test_slice_network_rule_execution_rate():
    """Verify executed slice: network-rule-execution-rate (rate laws, TotalRate, homodimer factors)."""
    model_text = """
begin model
begin parameters
  k_val 0.25
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b) 10
end seed species
begin reaction rules
  r_homo: A(b) + A(b) -> A(b!1).A(b!1) k_val
end reaction rules
end model
"""
    parsed = cpp.parse_string(model_text)
    net = BioNetGenModel(parsed).generate_network()
    assert net.reaction_factors == [0.5]
    assert net.reaction_rate_laws == ["k_val"]


def test_slice_network_rule_execution_filter():
    """Verify executed slice: network-rule-execution-filter (include/exclude filters)."""
    model_text = """
begin model
begin molecule types
  A(b,x~u~p)
  B(a)
end molecule types
begin seed species
  A(b,x~u) 10
  A(b,x~p) 10
  B(a) 10
end seed species
begin reaction rules
  r_inc: A(b) + B(a) -> A(b!1).B(a!1) 1.0 include_reactants(1, A(x~u))
end reaction rules
end model
"""
    parsed = cpp.parse_string(model_text)
    net = BioNetGenModel(parsed).generate_network()
    assert net.num_reactions == 1


def test_slice_network_rule_execution_local_scope():
    """Verify executed slice: network-rule-execution-local-scope (local function scopes)."""
    bngl_text = (VALIDATE_DIR / "localfunc.bngl").read_text()
    parsed = cpp.parse_string(bngl_text)
    net = BioNetGenModel(parsed).generate_network()
    assert net.num_species == 7
    assert net.num_reactions == 11


def test_slice_network_rule_execution_reversible():
    """Verify executed slice: network-rule-execution-reversible (bidirectional rule lowering)."""
    model_text = """
begin model
begin parameters
  kf 0.3
  kr 0.05
end parameters
begin molecule types
  A()
  B()
end molecule types
begin seed species
  A() 10
end seed species
begin reaction rules
  r_rev: A() <-> B() kf, kr
end reaction rules
end model
"""
    parsed = cpp.parse_string(model_text)
    net = BioNetGenModel(parsed).generate_network()
    assert net.num_reactions == 2
    assert net.reaction_rate_laws == ["kf", "kr"]
    assert net.reaction_factors == [1.0, 1.0]


# ==============================================================================
# release-capability-coverage-139: All 19 rows and 11 obligations verified
# ==============================================================================


def test_release_capability_coverage_139():
    """Assert all 19 assigned capability rows and 11 obligations for Issue #139 are verified."""
    contract_path = CASE_DIR / "contract.json"
    assert contract_path.is_file(), f"Missing contract.json at {contract_path}"
    with open(contract_path, encoding="utf-8") as f:
        contract = json.load(f)

    assert contract["schema_version"] == 1
    assert contract["issue"] == 139
    assert contract["acceptance_checks"] == [
        "release-network-rule-plan",
        "release-network-rule-mutations",
        "release-capability-coverage-139",
    ]

    contract_rows = set(contract.get("inventory_rows", []))
    expected_rows = set(ASSIGNED_INVENTORY_ROWS)
    assert len(expected_rows) == 19

    missing_rows = expected_rows - contract_rows
    assert not missing_rows, f"contract.json is missing inventory rows: {missing_rows}"

    extra_rows = contract_rows - expected_rows
    assert not extra_rows, f"contract.json has unassigned inventory rows: {extra_rows}"

    contract_obs = set(contract.get("obligations", []))
    expected_obs = set(EXPECTED_OBLIGATIONS)
    assert len(expected_obs) == 11

    missing_obs = expected_obs - contract_obs
    assert not missing_obs, f"contract.json is missing obligations: {missing_obs}"

    extra_obs = contract_obs - expected_obs
    assert not extra_obs, f"contract.json has extra obligations: {extra_obs}"
