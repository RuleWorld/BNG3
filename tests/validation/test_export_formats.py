"""Export-format validity (WO-5): one writer set, all formats valid."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.validation import compare, corpus, runner
from tests.validation.strict import require_oracle

EXPORT_MODELS = [
    m
    for m in ("Motivating_example", "egfr_net", "gene_expr", "Repressilator")
    if corpus.resolve(m) is not None
]

# The writers that had no coverage anywhere in tests/ before this file. They are
# action-level: the Python `Model` API exposes only write_xml/bngl/net/sbml/
# matlab/latex (python/bionetgen/model.py:573-620), so SSC, MDL and MEX are
# reachable only through the engine's action dispatch
# (cpp/actions/ActionDispatch.cpp:3553, :3666, :3848, :3866).
WRITE_ACTIONS = (
    "writeSSC()",
    "writeSSCcfg()",
    "writeMDL()",
    "writeMfile()",
    "writeMexfile()",
    "writeLatex()",
)


def _model_definition(text: str) -> str:
    """Return the model's block section with its own action list removed.

    Corpus models carry heavy action blocks -- gene_expr alone runs two 5e7 s
    stochastic simulations -- which is pure noise for a writer smoke gate. The
    `begin model`/`end model` form and the bare form both appear in the corpus
    (Repressilator has no `end model`), so cut at the first top-level line that
    is neither a comment nor a `begin`/`end` block delimiter, rather than
    searching for a terminator that may not exist.
    """
    kept: list[str] = []
    depth = 0
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if depth == 0 and stripped and not re.match(r"^(begin|end)\b", stripped):
            break
        kept.append(line)
        if re.match(r"^begin\b", stripped):
            depth += 1
        elif re.match(r"^end\b", stripped):
            depth -= 1
    return "\n".join(kept)


@pytest.fixture(scope="session")
def written_exports(bng_cpp, tmp_path_factory) -> dict[str, Path]:
    """Run the engine once per model with every write action, in isolation.

    One run per model rather than one per format, so that all six artifacts are
    known to come from a single consistent model state -- and so the two SSC
    artifacts are exercised together, which is the case that regressed.
    """
    produced: dict[str, Path] = {}
    for name in EXPORT_MODELS:
        source_dir = tmp_path_factory.mktemp(f"exportsrc_{name}")
        run_dir = tmp_path_factory.mktemp(f"exportrun_{name}")
        source = source_dir / f"{name}.bngl"
        source.write_text(
            _model_definition(corpus.resolve(name).read_text(encoding="utf-8"))
            + "\n\n"
            + "\n".join(WRITE_ACTIONS)
            + "\n",
            encoding="utf-8",
        )
        net, _, err = runner.run_cli_path(bng_cpp, source, run_dir)
        assert net is not None, f"export generation failed [{name}]: {err}"
        produced[name] = run_dir
    return produced


def _artifact(run_dir: Path, model_name: str, suffix: str) -> str:
    """Presence + non-emptiness check; returns the decoded artifact text."""
    path = run_dir / f"{model_name}{suffix}"
    assert path.is_file(), f"writer produced no {suffix} artifact [{model_name}]"
    text = path.read_text(encoding="utf-8", errors="replace")
    assert text.strip(), f"{suffix} artifact is empty [{model_name}]"
    return text


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_xml_wellformed(model_name, api, work_dir):
    out = runner.export(model_name, "xml", work_dir / f"{model_name}.xml")
    ok, msg = compare.check_xml_wellformed(out)
    assert ok, f"BNG-XML not well-formed [{model_name}]: {msg}"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_sbml_valid(model_name, api, work_dir):
    out = runner.export(model_name, "sbml", work_dir / f"{model_name}.xml")
    ok, msg = compare.check_sbml(out)
    assert ok, f"SBML invalid [{model_name}]: {msg}"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_net_roundtrip_idempotent(model_name, bng_cpp, work_dir):
    """write -> read -> write produces an identical network."""
    net1, _, err = runner.run_cli(bng_cpp, model_name, work_dir / "pass1")
    assert net1 is not None, f"first generation failed: {err}"

    # Follow BNG2's michment/michment_cont contract: the second pass must read
    # the first pass's .net file, not regenerate the BNGL model.
    roundtrip_source = work_dir / f"{model_name}_roundtrip.bngl"
    roundtrip_source.write_text(
        f'readFile({{file=>"{net1.as_posix()}"}})\nwriteNetwork({{overwrite=>1}})\n',
        encoding="utf-8",
    )
    net2, _, err2 = runner.run_cli_path(bng_cpp, roundtrip_source, work_dir / "pass2")
    assert net2 is not None, f"second generation failed: {err2}"
    n1, n2 = compare.parse_net(net1), compare.parse_net(net2)
    diff = compare.compare_net(n1, n2)
    assert diff.ok, f"net not idempotent [{model_name}]:\n{diff.summary()}"


@pytest.mark.export
def test_net_reload_preserves_outer_species_compartment(bng_cpp, work_dir):
    """A canonical @comp:: NET species keeps its compartment on rewrite."""
    net_input = work_dir / "compartmented.net"
    net_input.write_text(
        """begin species
    1 @cyto::A() 7
end species
begin reactions
end reactions
""",
        encoding="utf-8",
    )
    source = work_dir / "compartment_roundtrip.bngl"
    source.write_text(
        f"""begin compartments
    cyto 3 1.0
end compartments
begin molecule types
    A()
end molecule types
begin actions
    readFile({{file=>\"{net_input.as_posix()}\"}})
    writeNetwork({{overwrite=>1}})
end actions
""",
        encoding="utf-8",
    )

    net, _, err = runner.run_cli_path(bng_cpp, source, work_dir / "roundtrip")
    assert net is not None, f"NET compartment reload failed: {err}"
    parsed = compare.parse_net(net)
    assert parsed.species_by_index == {1: "@cyto::A()"}


@pytest.mark.export
@pytest.mark.parametrize("load_action", ["readFile", "include_network"])
def test_imported_net_simulation_preserves_compartment_rate_conversion(
    bng_cpp, tmp_path, load_action
):
    """Imported NET rates already include the source compartment conversion."""
    source = tmp_path / "compartment_synthesis.bngl"
    source.write_text(
        """begin model
begin parameters
    k 0.1
end parameters
begin compartments
    cell 3 2
end compartments
begin molecule types
    A()
end molecule types
begin observables
    Molecules A_total A@cell()
end observables
begin reaction rules
    synthesis: 0 -> A@cell() k
end reaction rules
end model
begin actions
    generate_network({overwrite=>1})
    simulate_ode({prefix=>"source",t_start=>0,t_end=>1,n_steps=>10})
end actions
""",
        encoding="utf-8",
    )
    source_dir = tmp_path / "source-run"
    net, source_gdat, err = runner.run_cli_path(bng_cpp, source, source_dir)
    assert net is not None, f"source network generation failed: {err}"
    assert source_gdat is not None, f"source simulation failed: {err}"

    reload_dir = tmp_path / f"reload-{load_action}"
    reload_dir.mkdir()
    shutil.copy2(net, reload_dir / "input.net")
    reload = tmp_path / f"reload-{load_action}.bngl"
    reload.write_text(
        f"""begin model
begin parameters
    k 0.1
end parameters
begin compartments
    cell 3 2
end compartments
end model
begin actions
    {load_action}({{file=>"input.net"}})
    simulate_ode({{prefix=>"reload",t_start=>0,t_end=>1,n_steps=>10}})
end actions
""",
        encoding="utf-8",
    )
    _, reload_gdat, err = runner.run_cli_path(bng_cpp, reload, reload_dir)
    assert reload_gdat is not None, f"{load_action} NET simulation failed: {err}"

    source_data, source_columns = compare.parse_gdat(source_gdat)
    reload_data, reload_columns = compare.parse_gdat(reload_gdat)
    assert source_data is not None and reload_data is not None
    diff = compare.compare_trajectories(
        source_data,
        source_columns,
        reload_data,
        reload_columns,
        rtol=1e-10,
        atol=1e-12,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, (
        f"{load_action} changed compartment-scaled imported NET dynamics: "
        f"{diff.summary()}"
    )


@pytest.mark.export
def test_net_reload_indexes_group_weights_by_species_row(bng_cpp, work_dir):
    """A numeric NET group selects its exact species row, not graph matches."""
    net_input = work_dir / "indexed_group.net"
    net_input.write_text(
        """begin species
    1 A() 3
    2 A().B() 5
end species
begin reactions
end reactions
begin groups
    1 only_singleton 2*1
end groups
""",
        encoding="utf-8",
    )
    source = work_dir / "indexed_group_roundtrip.bngl"
    source.write_text(
        f"""begin molecule types
    A()
    B()
end molecule types
begin actions
    readFile({{file=>\"{net_input.as_posix()}\"}})
    simulate({{method=>\"ode\",t_end=>1,n_steps=>1,prefix=>\"trajectory\"}})
    writeNetwork({{overwrite=>1}})
end actions
""",
        encoding="utf-8",
    )

    net, _, err = runner.run_cli_path(bng_cpp, source, work_dir / "roundtrip")
    assert net is not None, f"NET indexed-group simulation failed: {err}"
    gdat = work_dir / "roundtrip" / "trajectory.gdat"
    assert gdat.is_file(), f"NET indexed-group simulation produced no gdat: {err}"
    lines = [line.strip() for line in gdat.read_text(encoding="utf-8").splitlines()]
    header = next(line.lstrip("# ").split() for line in lines if line.startswith("#"))
    assert header == ["time", "only_singleton"]
    rows = [line.split() for line in lines if line and not line.startswith("#")]
    assert rows, "NET indexed-group simulation produced no data rows"
    assert float(rows[0][1]) == pytest.approx(6.0)


def _network3_executable() -> Path | None:
    """Return only the Network3 executable rooted at the pinned BNG2 checkout.

    The parity workflow sets BNGPATH to the checkout produced by
    scripts/ci/checkout_oracle.py and adds its bin directory to PATH. Requiring
    those paths to agree prevents an unrelated run_network earlier on PATH
    from silently becoming the consumer oracle.
    """
    bngpath = os.environ.get("BNGPATH")
    if not bngpath:
        return None

    expected = (Path(bngpath).expanduser() / "bin" / "run_network").resolve()
    on_path = shutil.which("run_network")
    if on_path and Path(on_path).resolve() != expected:
        return None
    if not expected.is_file() or not os.access(expected, os.X_OK):
        return None
    return expected


@pytest.mark.export
def test_bng2_network3_consumes_exported_net_ode(bng_cpp, tmp_path):
    """The pinned downstream reader executes this .net against its analytic solution."""
    run_network = _network3_executable()
    require_oracle(
        run_network is not None,
        "pinned Network3 run_network not found (set BNGPATH to the locked BNG2 checkout)",
    )
    assert run_network is not None

    source = tmp_path / "irreversible_conversion.bngl"
    source.write_text(
        """begin model
  begin parameters
    k 0.2
  end parameters
  begin molecule types
    A()
    B()
  end molecule types
  begin seed species
    A() 10
    B() 0
  end seed species
  begin reaction_rules
    convert: A() -> B() k
  end reaction_rules
end model

generate_network({overwrite=>1})
""",
        encoding="utf-8",
    )
    net_path, _, err = runner.run_cli_path(bng_cpp, source, tmp_path / "bng3")
    assert net_path is not None, f"BNG3 failed to write the .net: {err}"

    network = compare.parse_net(net_path)
    assert network is not None
    assert network.species_by_index == {1: "A()", 2: "B()"}

    output_prefix = tmp_path / "network3_consumed"
    proc = subprocess.run(
        [
            str(run_network),
            "-o",
            str(output_prefix),
            str(net_path),
            "0",
            "0.5",
            "1",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        "pinned Network3 could not consume the BNG3 .net:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    cdat_path = output_prefix.with_suffix(".cdat")
    observed, columns = compare.parse_gdat(cdat_path)
    assert observed is not None, f"Network3 produced no readable {cdat_path.name}"
    assert columns == ["time", "S1", "S2"]

    times = np.asarray([0.0, 0.5, 1.0])
    a = 10.0 * np.exp(-0.2 * times)
    expected = np.column_stack((times, a, 10.0 - a))
    assert np.array_equal(observed[:, 0], times)
    diff = compare.compare_trajectories(
        expected,
        ["time", "S1", "S2"],
        observed,
        columns,
        rtol=1e-6,
        atol=1e-9,
        columns=compare.COLUMNS_EXACT,
    )
    assert diff.ok, (
        "Network3 trajectory disagrees with analytic A -> B solution: "
        f"{diff.summary()}"
    )


def _locked_bng2_script() -> Path | None:
    """Return BNG2.pl only when it belongs to the locked checkout in BNGPATH."""
    script_text = os.environ.get("BNG2_PERL")
    bngpath_text = os.environ.get("BNGPATH")
    if not script_text or not bngpath_text:
        return None

    script = Path(script_text).expanduser().resolve()
    bngpath = Path(bngpath_text).expanduser().resolve()
    if script.parent != bngpath or script.name != "BNG2.pl" or not script.is_file():
        return None

    lock = json.loads(
        (corpus.REPO / "provenance" / "upstreams.lock.yml").read_text(encoding="utf-8")
    )
    oracle_evidence = json.loads(
        (
            corpus.REPO
            / "tests"
            / "validation"
            / "evidence"
            / "bng2-ssa-ensembles"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )["oracle"]
    expected_revision = lock["sources"]["bionetgen"]["revision"]
    checkout_root = bngpath.parent
    revision = subprocess.run(
        ["git", "-C", str(checkout_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if revision.returncode != 0 or revision.stdout.strip() != expected_revision:
        return None
    if oracle_evidence.get("revision") != expected_revision:
        return None
    if hashlib.sha256(script.read_bytes()).hexdigest() != oracle_evidence.get(
        "sha256", {}
    ).get("BNG2.pl"):
        return None

    tracked_clean = subprocess.run(
        ["git", "-C", str(checkout_root), "diff-index", "--quiet", "HEAD", "--"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if tracked_clean.returncode != 0:
        return None
    index_flags = subprocess.run(
        ["git", "-C", str(checkout_root), "ls-files", "-v"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if index_flags.returncode != 0 or any(
        line and (line[0] == "S" or line[0].islower())
        for line in index_flags.stdout.splitlines()
    ):
        return None
    return script


def _counting_fixture(
    molecules_mode: str, species_mode: str, qualify_molecules: bool = False
) -> str:
    molecule_pattern = "A(b!1).A(b!1)>5" if qualify_molecules else "A(b!1).A(b!1)"
    return f"""begin model
setOption("MoleculesObservables","{molecules_mode}")
setOption("SpeciesObservables","{species_mode}")
begin parameters
  n 1
  k 1
end parameters
begin molecule types
  A(b)
end molecule types
begin seed species
  A(b!1).A(b!1) n
  A(b) n
end seed species
begin observables
  Molecules Dimer {molecule_pattern}
  Species Both A(), A(b!1).A(b!1)
end observables
begin reaction rules
  dissociate: A(b!1).A(b!1) -> A(b) + A(b) k
end reaction rules
end model
"""


def _compartment_prefix_fixture() -> str:
    """Graph-scope prefix remains distinct from molecule-local qualifiers."""
    return """begin model
begin parameters
  n_pm 5
  n_cp 7
  k 1
end parameters
begin molecule types
  L(x)
  R(y)
  Z()
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @PM:L(x!1)@CP.R(y!1) n_pm
  @CP:L(x!1).R(y!1) n_cp
end seed species
begin observables
  Molecules PrefixAndNode @PM:L(x!1)@CP.R(y!1)
  Molecules NodeOnly L(x!1)@CP.R(y!1)
  Molecules MixedTerms @PM:L(x!1)@CP.R(y!1), L(x!1)@CP.R(y!1)
end observables
begin reaction rules
  source: 0 -> @PM:Z() k
end reaction rules
end model
"""


def _all_explicit_compartment_prefix_fixture() -> str:
    """A valid prefix plus local compartment constraints on every molecule."""
    return """begin model
begin parameters
  n 5
  k 1
end parameters
begin molecule types
  L(x)
  R(y)
  Z()
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @PM:L@CP(x!1).R@PM(y!1) n
end seed species
begin observables
  Molecules AllExplicitPrefix @PM:L@CP(x!1).R@PM(y!1)
end observables
begin reaction rules
  source: 0 -> @PM:Z() k
end reaction rules
end model
"""


def _species_countunique_qualified_fixture() -> str:
    """CountUnique stops after the first quantified Species term, even false."""
    return """begin model
setOption("SpeciesObservables", "CountUnique")
begin parameters
  n 5
  k 1
end parameters
begin molecule types
  A(s~0~1)
end molecule types
begin seed species
  A(s~0) n
end seed species
begin observables
  Species FalseThenTrue A(s~1)>0, A(s~0)>0
end observables
begin reaction rules
  change: A(s~0) -> A(s~1) k
end reaction rules
end model
"""


@pytest.mark.export
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "mixed",
            {
                "PrefixAndNode": {1: 1},
                "NodeOnly": {1: 1, 2: 1},
                "MixedTerms": {1: 2, 2: 1},
            },
        ),
        ("all-explicit", {"AllExplicitPrefix": {1: 1}}),
        ("species-countunique-qualified", {"FalseThenTrue": {2: 1}}),
    ],
)
def test_compartment_prefix_observables_match_locked_bng2(
    fixture, expected, bng_cpp, tmp_path
):
    """The .net groups and C++ weights preserve graph and node compartments."""
    bng2 = _locked_bng2_script()
    require_oracle(
        bng2 is not None,
        "locked BNG2.pl not found at BNG2_PERL/BNGPATH or its source revision "
        "does not match provenance/upstreams.lock.yml",
    )
    assert bng2 is not None
    perl = shutil.which(os.environ.get("PERL", "perl"))
    require_oracle(perl is not None, "Perl is required to run the locked BNG2 oracle")
    assert perl is not None

    model = {
        "mixed": _compartment_prefix_fixture,
        "all-explicit": _all_explicit_compartment_prefix_fixture,
        "species-countunique-qualified": _species_countunique_qualified_fixture,
    }[fixture]()
    source = tmp_path / f"compartment_{fixture}.bngl"
    source.write_text(
        model + "\ngenerate_network({overwrite=>1})\nwriteCPPfile()\n",
        encoding="utf-8",
    )
    bng3_dir = tmp_path / "bng3"
    net_path, _, err = runner.run_cli_path(bng_cpp, source, bng3_dir)
    assert net_path is not None, f"BNG3 C++ export failed: {err}"
    header_path = bng3_dir / f"compartment_{fixture}_cvode.h"
    assert header_path.is_file(), "writeCPPfile produced no CVODE header"

    oracle_source = tmp_path / f"compartment_{fixture}_bng2.bngl"
    oracle_source.write_text(
        model + "\ngenerate_network({overwrite=>1})\n", encoding="utf-8"
    )
    bng2_dir = tmp_path / "bng2"
    bng2_dir.mkdir()
    oracle_env = os.environ.copy()
    oracle_env["BNGPATH"] = str(bng2.parent)
    proc = subprocess.run(
        [
            perl,
            str(bng2),
            "--outdir",
            str(bng2_dir),
            "--check",
            "--netgen",
            str(oracle_source),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=oracle_env,
    )
    assert proc.returncode == 0, (
        "locked BNG2 could not generate compartment observable groups:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    oracle_net = compare.parse_net(bng2_dir / f"compartment_{fixture}_bng2.net")
    bng3_net = compare.parse_net(net_path)
    assert oracle_net is not None, "locked BNG2 produced no parseable .net"
    assert bng3_net is not None, "BNG3 produced no parseable .net"
    assert bng3_net.species_by_index == oracle_net.species_by_index, (
        "compartment observable fixture species identities/order differ between "
        f"BNG3 and locked BNG2: {bng3_net.species_by_index!r} vs "
        f"{oracle_net.species_by_index!r}"
    )

    oracle_groups = {name: entries for name, entries in oracle_net.groups.values()}
    bng3_groups = {name: entries for name, entries in bng3_net.groups.values()}
    assert oracle_groups == expected, "locked BNG2 did not exercise the expected groups"
    assert bng3_groups == expected, (
        f"BNG3 .net groups disagree with locked BNG2 for {fixture}: "
        f"{bng3_groups!r} vs {expected!r}"
    )
    assert (
        _cpp_observable_weights(header_path.read_text(encoding="utf-8")) == expected
    ), f"C++ export observable weights disagree with locked BNG2 for {fixture}"


@pytest.mark.export
def test_locked_bng2_prefix_miss_still_evaluates_zero_count_relation(tmp_path):
    """Pin the BNG2 contract for a prefix miss followed by a zero-count test."""
    bng2 = _locked_bng2_script()
    require_oracle(
        bng2 is not None,
        "locked BNG2.pl not found at BNG2_PERL/BNGPATH or its source revision "
        "does not match provenance/upstreams.lock.yml",
    )
    assert bng2 is not None
    perl = shutil.which(os.environ.get("PERL", "perl"))
    require_oracle(perl is not None, "Perl is required to run the locked BNG2 oracle")
    assert perl is not None

    model = """begin model
begin parameters
  n 1
end parameters
begin molecule types
  A()
  Z()
end molecule types
begin compartments
  PM 2 1
  CP 3 1 PM
end compartments
begin seed species
  @CP:A() n
end seed species
begin observables
  Species PrefixZero @PM:A()<1
end observables
begin reaction rules
  source: 0 -> @PM:Z() 1
end reaction rules
end model
generate_network({overwrite=>1})
"""
    source = tmp_path / "prefix_zero_bng2.bngl"
    source.write_text(model, encoding="utf-8")
    output = tmp_path / "bng2"
    output.mkdir()
    oracle_env = os.environ.copy()
    oracle_env["BNGPATH"] = str(bng2.parent)
    proc = subprocess.run(
        [perl, str(bng2), "--outdir", str(output), "--check", "--netgen", str(source)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=oracle_env,
    )
    assert proc.returncode == 0, (
        "locked BNG2 could not generate the zero-count relation fixture:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    oracle_net = compare.parse_net(output / "prefix_zero_bng2.net")
    assert oracle_net is not None, "locked BNG2 produced no parseable .net"
    assert oracle_net.species_by_index == {
        1: "@CP::A()",
        2: "@PM::Z()",
    }
    assert {name: entries for name, entries in oracle_net.groups.values()} == {
        "PrefixZero": {1: 1, 2: 1}
    }


def _cpp_observable_weights(header: str) -> dict[str, dict[int, int]]:
    """Read emitted species coefficients by observable and 1-based species id."""
    result: dict[str, dict[int, int]] = {}
    assignment = re.compile(
        r"NV_Ith_S\(observables,(\d+)\)\s*=\s*(.*?);\s*/\*\s*([^*]+?)\s*\*/"
    )
    term = re.compile(r"(?:(\d+)\s*\*\s*)?NV_Ith_S\(species,(\d+)\)")
    for _, expression, name in assignment.findall(header):
        weights: dict[int, int] = {}
        if expression.strip() != "0":
            parsed_terms = []
            for item in expression.split("+"):
                match = term.fullmatch(item.strip())
                assert (
                    match is not None
                ), f"unexpected C++ observable term for {name}: {item!r}"
                weight = int(match.group(1) or "1")
                species_index = int(match.group(2)) + 1
                weights[species_index] = weights.get(species_index, 0) + weight
                parsed_terms.append(item)
            assert parsed_terms, f"no C++ observable terms parsed for {name}"
        result[name.strip()] = weights
    return result


@pytest.mark.export
@pytest.mark.parametrize(
    ("molecules_mode", "species_mode"),
    [
        ("CountAll", "CountAll"),
        ("CountUnique", "CountAll"),
        ("CountAll", "CountUnique"),
        ("CountUnique", "CountUnique"),
    ],
)
@pytest.mark.parametrize("qualify_molecules", (False, True))
def test_cpp_export_observable_modes_match_locked_bng2(
    molecules_mode, species_mode, qualify_molecules, bng_cpp, tmp_path
):
    """CVODE coefficients preserve BNG2 counting and qualifier semantics."""
    bng2 = _locked_bng2_script()
    require_oracle(
        bng2 is not None,
        "locked BNG2.pl not found at BNG2_PERL/BNGPATH or its source revision "
        "does not match provenance/upstreams.lock.yml",
    )
    assert bng2 is not None
    perl = shutil.which(os.environ.get("PERL", "perl"))
    require_oracle(perl is not None, "Perl is required to run the locked BNG2 oracle")
    assert perl is not None

    model = _counting_fixture(molecules_mode, species_mode, qualify_molecules)
    source = tmp_path / "observable_counting.bngl"
    source.write_text(
        model + "\ngenerate_network({overwrite=>1})\nwriteCPPfile()\n",
        encoding="utf-8",
    )
    bng3_dir = tmp_path / "bng3"
    net_path, _, err = runner.run_cli_path(bng_cpp, source, bng3_dir)
    assert net_path is not None, f"BNG3 C++ export failed: {err}"
    header_path = bng3_dir / "observable_counting_cvode.h"
    assert header_path.is_file(), "writeCPPfile produced no CVODE header"

    oracle_source = tmp_path / "observable_counting_bng2.bngl"
    oracle_source.write_text(
        model + "\ngenerate_network({overwrite=>1})\n", encoding="utf-8"
    )
    bng2_dir = tmp_path / "bng2"
    bng2_dir.mkdir()
    oracle_env = os.environ.copy()
    oracle_env["BNGPATH"] = str(bng2.parent)
    proc = subprocess.run(
        [
            perl,
            str(bng2),
            "--outdir",
            str(bng2_dir),
            "--check",
            "--netgen",
            str(oracle_source),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=oracle_env,
    )
    assert proc.returncode == 0, (
        "locked BNG2 could not generate observable groups:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    oracle_net = compare.parse_net(bng2_dir / "observable_counting_bng2.net")
    bng3_net = compare.parse_net(net_path)
    assert oracle_net is not None, "locked BNG2 produced no parseable .net"
    assert bng3_net is not None, "BNG3 produced no parseable .net"
    assert bng3_net.species_by_index == oracle_net.species_by_index, (
        "simple observable fixture species identities/order differ between "
        f"BNG3 and locked BNG2: {bng3_net.species_by_index!r} vs "
        f"{oracle_net.species_by_index!r}"
    )

    expected = {name: entries for name, entries in oracle_net.groups.values()}
    emitted = _cpp_observable_weights(header_path.read_text(encoding="utf-8"))
    assert set(emitted) == {"Dimer", "Both"}
    assert set(expected) == {"Dimer", "Both"}
    assert expected == {
        "Dimer": {1: 2.0 if molecules_mode == "CountAll" else 1.0},
        "Both": {
            1: 2.0 if species_mode == "CountAll" else 1.0,
            2: 1.0,
        },
    }, "locked BNG2 did not exercise both observable counting modes"
    for name in sorted(expected):
        assert emitted[name] == expected[name], (
            f"C++ export observable {name} disagrees with locked BNG2 "
            f"(MoleculesObservables={molecules_mode}, "
            f"SpeciesObservables={species_mode}): "
            f"emitted={emitted[name]!r}, expected={expected[name]!r}"
        )


@pytest.mark.export
@pytest.mark.parametrize("option", ("MoleculesObservables", "SpeciesObservables"))
def test_cpp_export_rejects_unknown_observable_mode(option, bng_cpp, tmp_path):
    """An invalid count mode must fail before export instead of defaulting."""
    molecules_mode = "CountEvery" if option == "MoleculesObservables" else "CountAll"
    species_mode = "CountEvery" if option == "SpeciesObservables" else "CountAll"
    source = tmp_path / "invalid_observable_mode.bngl"
    source.write_text(
        _counting_fixture(molecules_mode, species_mode)
        + "\ngenerate_network({overwrite=>1})\nwriteCPPfile()\n",
        encoding="utf-8",
    )
    net_path, _, err = runner.run_cli_path(bng_cpp, source, tmp_path / "bng3")
    assert net_path is None, "invalid observable count mode was accepted"
    assert f"invalid {option} value 'CountEvery'" in err
    assert "expected 'CountUnique' or 'CountAll'" in err


# --------------------------------------------------------------------------- #
# SSC: two actions, two different artifacts.
#
# BNG2 writes a full reaction program to .rxn (BNGOutput.pm:1288-1369) and a
# parameter-only block to .cfg (:1371-1397). A build in which both actions emit
# the full program is a user-facing bug that a "a file appeared" check cannot
# see, so the assertions below are on content, not presence.
# --------------------------------------------------------------------------- #


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_ssc_rxn_is_a_full_program(model_name, written_exports):
    rxn = _artifact(written_exports[model_name], model_name, ".rxn")
    for section in ("// Parameters", "// Species", "// Reactions"):
        assert section in rxn, f"SSC .rxn missing {section} section [{model_name}]"
    # A species declaration and a reaction rule, not just the three headings.
    assert re.search(
        r"^new \w+\(", rxn, re.M
    ), f"SSC .rxn declares no species [{model_name}]"
    assert re.search(
        r"^[^/\s]\S*\s*->.*;\s*$", rxn, re.M
    ), f"SSC .rxn declares no reaction rule [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_ssc_cfg_is_parameters_only(model_name, written_exports):
    cfg = _artifact(written_exports[model_name], model_name, ".cfg")
    assert "const " in cfg, f"SSC .cfg has no parameter block [{model_name}]"
    for forbidden in ("// Species", "// Reactions"):
        assert forbidden not in cfg, (
            f"SSC .cfg carries the {forbidden} section of a full program "
            f"[{model_name}] -- writeSSCcfg must not re-emit writeSSC's output"
        )
    assert not re.search(
        r"^new \w+\(", cfg, re.M
    ), f"SSC .cfg declares species [{model_name}]"
    assert "->" not in cfg, f"SSC .cfg declares reaction rules [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_ssc_cfg_and_rxn_are_different_artifacts(model_name, written_exports):
    """The regression: .cfg is the .rxn parameter block and nothing else."""
    run_dir = written_exports[model_name]
    rxn = _artifact(run_dir, model_name, ".rxn")
    cfg = _artifact(run_dir, model_name, ".cfg")
    assert cfg != rxn, f"SSC .cfg and .rxn are the same artifact [{model_name}]"

    rxn_params = {ln for ln in rxn.splitlines() if ln.startswith("const ")}
    cfg_params = {ln for ln in cfg.splitlines() if ln.startswith("const ")}
    assert cfg_params, f"SSC .cfg has no parameter block [{model_name}]"
    assert (
        cfg_params <= rxn_params
    ), f"SSC .cfg parameters are not the .rxn parameter block [{model_name}]"
    # The two blocks are *meant* to agree on parameters; what must not survive
    # into .cfg is everything after them, which the section assertions in
    # test_ssc_cfg_is_parameters_only cover.
    assert len(cfg.splitlines()) < len(
        rxn.splitlines()
    ), f"SSC .cfg is at least as large as the full program [{model_name}]"


# --------------------------------------------------------------------------- #
# MDL / MATLAB / MEX / LaTeX.
#
# These are smoke gates, not goldens: each asserts the file exists, is
# non-empty, and carries the section markers that make it that format rather
# than a differently-named copy of something else. They do NOT check numeric
# values, so a writer that emitted structurally valid but wrong numbers would
# still pass.
# --------------------------------------------------------------------------- #


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_mdl_written(model_name, written_exports):
    mdl = _artifact(written_exports[model_name], model_name, ".mdl")
    for marker in ("ITERATIONS", "DEFINE_MOLECULES", "DEFINE_REACTIONS"):
        assert marker in mdl, f"MDL missing {marker} [{model_name}]"
    assert re.search(
        r"^\s*\w+ \{ DIFFUSION_CONSTANT_3D", mdl, re.M
    ), f"MDL declares no molecule with a diffusion coefficient [{model_name}]"
    assert "INSTANTIATE" in mdl, f"MDL never instantiates the world [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_matlab_mfile_written(model_name, written_exports):
    m = _artifact(written_exports[model_name], model_name, ".m")
    assert (
        "function [err, timepoints" in m
    ), f"MATLAB .m is not the documented 4-output entry point [{model_name}]"
    for helper in ("getDefaultParameters", "getInitialSpecies"):
        assert helper in m, f"MATLAB .m missing {helper}() [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_mex_c_written(model_name, written_exports):
    # MexWriter appends a "_mex" tag to the output stem (ActionDispatch.cpp:3686).
    mex = _artifact(written_exports[model_name], model_name, "_mex.c")
    assert '#include "mex.h"' in mex, f"MEX file does not include mex.h [{model_name}]"
    assert "mexFunction" in mex, f"MEX file defines no mexFunction [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_latex_written(model_name, written_exports):
    tex = _artifact(written_exports[model_name], model_name, ".tex")
    assert "\\documentclass" in tex, f"LaTeX has no documentclass [{model_name}]"
    assert "\\begin{document}" in tex, f"LaTeX never begins the document [{model_name}]"
    assert "\\end{document}" in tex, f"LaTeX document is unterminated [{model_name}]"
    for section in ("\\section{Parameters}", "\\section{Reactions}"):
        assert section in tex, f"LaTeX missing {section} [{model_name}]"
