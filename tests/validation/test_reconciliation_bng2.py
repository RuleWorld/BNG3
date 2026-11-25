"""Differential checks for source changes in the accepted BNG2 range."""

import hashlib
import re
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from tests.validation import compare, oracle_perl, runner
from tests.validation.strict import require_oracle

ROOT = Path(__file__).resolve().parents[2]


def _pinned_model_text(name, record_property):
    upstream_perl = oracle_perl._bng2_path()
    require_oracle(upstream_perl is not None, "set BNG2_PERL to the pinned BNG2.pl")
    assert upstream_perl is not None
    relative_source = Path("bng2/Models2") / f"{name}.bngl"
    upstream_root = upstream_perl.parent.parent
    source_bytes = (upstream_root / relative_source).read_bytes()
    pinned_bytes = subprocess.check_output(
        ["git", "-C", str(upstream_root), "cat-file", "blob", f"HEAD:{relative_source}"]
    )
    assert source_bytes == pinned_bytes, relative_source
    record_property("upstream_fixture", str(relative_source))
    record_property("fixture_sha256", hashlib.sha256(source_bytes).hexdigest())
    model_text = source_bytes.decode("utf-8").replace("\r\n", "\n")
    model, end, _ = model_text.partition("end model")
    assert end
    # This check compares the generated network. The retained interpreter
    # does not carry upstream release metadata for the version() directive.
    if name == "energy_example1":
        assert model.count('version("2.2.4")\n') == 1
        model = model.replace('version("2.2.4")\n', "", 1)
    text = model + end + "\ngenerate_network({overwrite=>1})\n"
    return upstream_perl, text


def _run_perl_network(perl, name, text, work):
    work.mkdir()
    staged = work / f"{name}.bngl"
    staged.write_text(text, encoding="utf-8")
    result = subprocess.run(
        ["perl", str(perl), str(staged)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"{perl}: {result.stdout}\n{result.stderr}"
    return work / f"{name}.net"


@pytest.mark.parametrize(
    "name",
    ["Motivating_example_cBNGL", "energy_example1"],
    ids=["invalid-compartment-product", "shared-arrhenius-normalization"],
)
def test_retained_perl_network_matches_upstream_fix(name, tmp_path, record_property):
    """Reproduce upstream #339 and #340 through BNG3's retained Perl route."""
    upstream_perl, text = _pinned_model_text(name, record_property)
    ref = compare.parse_net(
        _run_perl_network(upstream_perl, name, text, tmp_path / "source")
    )
    retained = compare.parse_net(
        _run_perl_network(
            ROOT / "legacy/perl/BNG2.pl", name, text, tmp_path / "retained"
        )
    )
    assert ref is not None and retained is not None
    diff = compare.compare_net(ref, retained)
    assert diff.ok, diff.summary()


@pytest.mark.parametrize(
    ("product", "species_count", "reaction_count"),
    [("A(x).B(y)", 1, 0), ("A(x) + B(y)", 3, 1)],
    ids=["invalid-dotted-product", "valid-split-product"],
)
def test_native_bridge_bond_break_respects_product_patterns(
    bng_cpp, tmp_path, product, species_count, reaction_count
):
    """Pinned native BNG2 rejects a bridge break specified as one product."""
    model = tmp_path / "bridge.bngl"
    model.write_text(
        f"""begin model
begin molecule types
    A(x)
    B(y)
end molecule types
begin seed species
    A(x!1).B(y!1) 1
end seed species
begin reaction rules
    A(x!1).B(y!1) -> {product} 1
end reaction rules
end model
generate_network({{overwrite=>1}})
""",
        encoding="utf-8",
    )
    net, _, error = runner.run_cli_path(bng_cpp, model, tmp_path / "native")
    assert net is not None, error
    graph = compare.parse_net(net)
    assert graph is not None
    assert graph.n_species == species_count
    assert graph.n_reactions == reaction_count


def test_native_arrhenius_normalization_separates_net_rounding(
    bng_cpp, tmp_path, record_property
):
    name = "energy_example1"
    upstream_perl, text = _pinned_model_text(name, record_property)
    ref = _run_perl_network(upstream_perl, name, text, tmp_path / "source")
    model = tmp_path / f"{name}.bngl"
    model.write_text(text, encoding="utf-8")
    subject, _, error = runner.run_cli_path(bng_cpp, model, tmp_path / "native")
    assert subject is not None, error

    # The fixture gives vol_CP = 4/3 * PI * rad_cell^3. Test the two
    # documented NET spellings of its count-rate conversion independently.
    volume = Decimal(4) / 3 * Decimal("3.1415927") * Decimal("1e-4") ** 3
    factor = 1 / (Decimal("6.0221e23") * volume)
    line = re.compile(
        r"(?m)^(\s*\d+\s+\d+(?:,\d+)*\s+\d+(?:,\d+)*\s+)"
        r"([\d.]+e[+-]\d+)\*([A-Za-z_]\w*\s+#.*unit_conversion=.*)$"
    )
    normalized = []
    for path, significant in ((ref, 8), (subject, 9)):
        serialized = path.read_text(encoding="utf-8")
        coefficients = [Decimal(match[2]) for match in line.finditer(serialized)]
        assert len(coefficients) == 12
        assert coefficients == [Decimal(format(factor, f".{significant}g"))] * 12
        out = path.with_name("unscaled.net")
        out.write_text(line.sub(r"\1\3", serialized), encoding="utf-8")
        parsed = compare.parse_net(out)
        assert parsed is not None
        normalized.append(parsed)
    diff = compare.compare_net(*normalized)
    assert diff.ok, diff.summary()
    assert normalized[0].n_reactions == 24


def _run_native_bngl(bng_cpp, name, text, work):
    work.mkdir(parents=True, exist_ok=True)
    model = work / f"{name}.bngl"
    model.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [str(bng_cpp), str(model)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, work


def _parse_gdat_rows(path):
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    header = lines[0].lstrip("#").split()
    rows = []
    for line in lines[1:]:
        if line.startswith("#"):
            continue
        rows.append(dict(zip(header, (float(tok) for tok in line.split()))))
    return rows


def test_cross_rule_duplicate_reaction_merge(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen 3513bca766 across native C++ and retained Perl."""
    text = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  Mol(state~U~P)
end molecule types
begin seed species
  Mol(state~U) 1000
end seed species
begin reaction rules
  Mol(state~U) -> Mol(state~P) k
  Mol(state)   -> Mol(state~P) k
end reaction rules
end model
generate_network({overwrite=>1})
"""
    res, native_dir = _run_native_bngl(bng_cpp, "cross_rule", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    native_net = (native_dir / "cross_rule.net").read_text(encoding="utf-8")
    native_graph = compare.parse_net(native_dir / "cross_rule.net")
    assert native_graph is not None
    assert native_graph.n_reactions == 1
    assert "2*k" in native_net
    assert "#R1,R2" in native_net

    retained_net_path = _run_perl_network(
        ROOT / "legacy/perl/BNG2.pl", "cross_rule", text, tmp_path / "retained"
    )
    retained_net = retained_net_path.read_text(encoding="utf-8")
    retained_graph = compare.parse_net(retained_net_path)
    assert retained_graph is not None
    assert retained_graph.n_reactions == 1
    assert "2*k" in retained_net
    assert "#_R1,_R2" in retained_net


def test_local_function_xml_export_does_not_crash(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen 78ef08563f (PR #351): local function + generate_network + writeXML."""
    text = """begin model
begin parameters
  Gf_up 0
  Gf_misalign 0.7
  Eact0_flip 1
  phi 0.5
end parameters
begin molecule types
  M(n,s,sp~up~dn)
end molecule types
begin seed species
  M(n!1,s!2,sp~dn).M(n!2,s!1,sp~dn) 1
end seed species
begin observables
  Molecules M_spUp M(sp~up)
  Molecules northUp M(n!0).M(s!0,sp~up)
end observables
begin functions
  rateFlipUp(z) = exp(-(Eact0_flip + phi*(Gf_up + (1 - northUp(z))*Gf_misalign)))
end functions
begin reaction rules
  M%x(sp~dn) -> M%x(sp~up) rateFlipUp(x)
end reaction rules
end model
generate_network({overwrite=>1})
writeXML()
"""
    res, native_dir = _run_native_bngl(bng_cpp, "localfcn_xml", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    xml_text = (native_dir / "localfcn_xml.xml").read_text(encoding="utf-8")
    assert '<Function id="rateFlipUp"' in xml_text
    assert '<Argument id="z"/>' in xml_text

    retained_dir = tmp_path / "retained"
    retained_dir.mkdir()
    staged = retained_dir / "localfcn_xml.bngl"
    staged.write_text(text, encoding="utf-8")
    perl_res = subprocess.run(
        ["perl", str(ROOT / "legacy/perl/BNG2.pl"), str(staged)],
        cwd=retained_dir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert perl_res.returncode == 0, f"{perl_res.stdout}\n{perl_res.stderr}"
    assert (retained_dir / "localfcn_xml.xml").is_file()


def test_retained_perl_multiarg_local_function_arg_elimination(tmp_path):
    """Verify legacy/perl Function::evaluate_local indexes $local_fcn->Args on 2+ arguments."""
    script = """
use strict;
use warnings;
use lib $ARGV[0];
use BNGModel;
use ParamList;
use Function;
use Expression;
my $model = BNGModel->new();
my $plist = ParamList->new();
$model->ParamList($plist);
$plist->set('k', '2');
my $f = Function->new();
my $err = $f->readString('f(x,y)=k+y', $model);
die $err if $err;
my $s1 = '1';
my $s2 = 'y';
my $e1 = Expression->new(); $e1->readString(\\$s1, $plist);
my $e2 = Expression->new(); $e2->readString(\\$s2, $plist);
my ($lf, $bad) = $f->evaluate_local(['f', $e1, $e2], $plist);
die "expected 1 remaining arg, got " . scalar(@{$lf->Args}) unless @{$lf->Args} == 1;
die "expected remaining arg y, got " . $lf->Args->[0] unless $lf->Args->[0] eq 'y';
print "OK\\n";
"""
    res = subprocess.run(
        ["perl", "-e", script, str(ROOT / "legacy/perl/Perl2")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    assert "OK" in res.stdout


def test_issue_341_negative_power_parentheses(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #341: negative number operands stay parenthesized."""
    text = """begin model
begin parameters
  k 2
  pA -2^k
  pB -k^2
  pC (-2)^k
  pD 0-2^k
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  fA() = -2^k
  fB() = -k^2
  fC() = (-2)^k
  fD() = 0-2^k
  gA() = pA
  gB() = pB
  gC() = pC
  gD() = pD
end functions
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
begin actions
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1,n_steps=>1,print_functions=>1})
end actions
"""
    res, native_dir = _run_native_bngl(bng_cpp, "issue_341", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    net_text = (native_dir / "issue_341.net").read_text(encoding="utf-8")
    assert "(-2)" in net_text
    rows = _parse_gdat_rows(native_dir / "issue_341.gdat")
    assert rows
    row = rows[0]
    for key in ("fA", "fB", "fC", "gA", "gB", "gC"):
        assert row[key] == pytest.approx(4.0, abs=1e-9), key
    for key in ("fD", "gD"):
        assert row[key] == pytest.approx(-4.0, abs=1e-9), key


def test_issue_342_if_nonzero_truthiness(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #342: if() treats any nonzero value as true."""
    text = """begin model
begin parameters
  kD 0.7
  kA 2
  kB 3
  pIf if(kD-0.5, kA, kB)
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  fPos()  = if(kD-0.5, kA, kB)
  fNeg()  = if(0.5-kD-0.8, kA, kB)
  fHalf() = if(kD-0.2, kA, kB)
  fZero() = if(kD-0.7, kA, kB)
  fCmp()  = if(kD-0.5 > 0, kA, kB)
  gIf()   = pIf
end functions
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
begin actions
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1,n_steps=>1,print_functions=>1})
end actions
"""
    res, native_dir = _run_native_bngl(bng_cpp, "issue_342", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    rows = _parse_gdat_rows(native_dir / "issue_342.gdat")
    assert rows
    row = rows[0]
    for key in ("fPos", "fNeg", "fHalf", "fCmp", "gIf"):
        assert row[key] == pytest.approx(2.0, abs=1e-9), key
    assert row["fZero"] == pytest.approx(3.0, abs=1e-9)


def test_issue_343_logical_operators_in_xml(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #343: && and || serialized as spaced logical tests in XML."""
    text = """begin model
begin parameters
  kA 2
  kB 0
  kD 0.7
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 1
end seed species
begin observables
  Molecules Atot A()
end observables
begin functions
  fAnd() = kA && kB
  fOr()  = kA || kB
  fObs() = Atot && kA
  fCmp() = if(kD > 0.5 && kA > 1, kA, kB)
end functions
begin reaction rules
  A() -> 0 0.1
end reaction rules
end model
begin actions
writeXML()
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>1,n_steps=>1,print_functions=>1})
end actions
"""
    res, native_dir = _run_native_bngl(bng_cpp, "issue_343", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    xml_text = (native_dir / "issue_343.xml").read_text(encoding="utf-8")
    assert "(kA!=0) and (kB!=0)" in xml_text
    assert "(kA!=0) or (kB!=0)" in xml_text
    assert "(Atot!=0) and (kA!=0)" in xml_text
    assert "&amp;&amp;" not in xml_text
    assert "||" not in xml_text
    rows = _parse_gdat_rows(native_dir / "issue_343.gdat")
    assert rows
    row = rows[0]
    assert row["fAnd"] == pytest.approx(0.0, abs=1e-9)
    assert row["fOr"] == pytest.approx(1.0, abs=1e-9)
    assert row["fObs"] == pytest.approx(1.0, abs=1e-9)
    assert row["fCmp"] == pytest.approx(2.0, abs=1e-9)


def test_issue_348_number_per_quantity_unit_xml(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #348: writeXML emits NumberPerQuantityUnit on <model>."""
    text = """setOption("NumberPerQuantityUnit",2)
begin model
begin parameters
  kf 0.01
  kr 0.1
end parameters
begin compartments
  EC 3 1
end compartments
begin molecule types
  A(b)
  B(a)
end molecule types
begin seed species
  A(b)@EC 300
  B(a)@EC 300
end seed species
begin observables
  Molecules AB A(b!1).B(a!1)
end observables
begin reaction rules
  A(b)@EC + B(a)@EC <-> A(b!1)@EC.B(a!1)@EC kf, kr
end reaction rules
end model
begin actions
generate_network({overwrite=>1})
writeXML()
simulate({method=>"ode",t_end=>5,n_steps=>5})
end actions
"""
    res, native_dir = _run_native_bngl(bng_cpp, "issue_348", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    xml_text = (native_dir / "issue_348.xml").read_text(encoding="utf-8")
    assert 'NumberPerQuantityUnit="2"' in xml_text
    rows = _parse_gdat_rows(native_dir / "issue_348.gdat")
    assert rows[-1]["AB"] == pytest.approx(229.9949864416, rel=1e-4)

    retained_dir = tmp_path / "retained"
    retained_dir.mkdir()
    staged = retained_dir / "issue_348.bngl"
    staged.write_text(text.replace('simulate({method=>"ode",t_end=>5,n_steps=>5})\n', ""), encoding="utf-8")
    perl_res = subprocess.run(
        ["perl", str(ROOT / "legacy/perl/BNG2.pl"), str(staged)],
        cwd=retained_dir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert perl_res.returncode == 0, f"{perl_res.stdout}\n{perl_res.stderr}"
    assert 'NumberPerQuantityUnit="2"' in (retained_dir / "issue_348.xml").read_text(encoding="utf-8")


def test_issue_357_parallel_parameter_scan_short_batch_and_error(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #357: uneven parallel batches match serial scan."""
    base_model = """begin model
begin parameters
  k 0.5
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 100
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  A() -> 0 k
end reaction rules
end model
generate_network({overwrite=>1})
"""
    serial_text = (
        base_model
        + 'parameter_scan({method=>"ode",parameter=>"k",par_min=>0.1,par_max=>1.0,'
        + 'n_scan_pts=>5,t_end=>1,n_steps=>5,reset_conc=>1})\n'
    )
    parallel_text = (
        base_model
        + 'parameter_scan({method=>"ode",parameter=>"k",par_min=>0.1,par_max=>1.0,'
        + 'n_scan_pts=>5,t_end=>1,n_steps=>5,reset_conc=>1,parallel=>1,num_cores=>3})\n'
    )
    s_res, s_dir = _run_native_bngl(bng_cpp, "scan_serial", serial_text, tmp_path / "serial")
    p_res, p_dir = _run_native_bngl(bng_cpp, "scan_parallel", parallel_text, tmp_path / "parallel")
    assert s_res.returncode == 0, f"{s_res.stdout}\n{s_res.stderr}"
    assert p_res.returncode == 0, f"{p_res.stdout}\n{p_res.stderr}"
    s_lines = [l.strip() for l in (s_dir / "scan_serial_k.scan").read_text(encoding="utf-8").splitlines() if l.strip()]
    p_lines = [l.strip() for l in (p_dir / "scan_parallel_k.scan").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(p_lines) == 6  # header + 5 points
    assert p_lines == s_lines


def test_issue_358_psa_zeroth_order_product_scaling(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #358: PSA scales 0 -> A by product population."""
    text = """begin model
begin parameters
  k_syn 100000
  k_deg 1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 0
end seed species
begin observables
  Molecules Atot A()
end observables
begin reaction rules
  0 -> A() k_syn
  A() -> 0 k_deg
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"psa",t_end=>2,n_steps=>2,poplevel=>100,check_product_scale=>0,seed=>7})
"""
    res, native_dir = _run_native_bngl(bng_cpp, "issue_358", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    rows = _parse_gdat_rows(native_dir / "issue_358.gdat")
    assert len(rows) == 3
    # Analytic mean at t=2 is 1e5 * (1 - exp(-2)) ~= 86466.5; single trajectory within 20%
    assert 65000.0 < rows[-1]["Atot"] < 105000.0


def test_issue_360_arrhenius_actE_depends_on_Gf(bng_cpp, tmp_path):
    """Reproduce RuleWorld/bionetgen #360: Arrhenius actE may depend on energy pattern Gf."""
    text = """begin model
begin parameters
  kf   2
  kD   0.01
  phi  0.5
  Gf   ln(kD)
  Ea0  -ln(kf) - phi*Gf
  Gf2  ln(0.5)
end parameters
begin molecule types
  A(b)
  B(a)
  C(d)
  D(c)
end molecule types
begin seed species
  A(b) 1
  B(a) 1
  C(d) 1
  D(c) 1
end seed species
begin energy patterns
  A(b!1).B(a!1) Gf
  C(d!1).D(c!1) Gf2
end energy patterns
begin observables
  Molecules AB A(b!1).B(a!1)
  Molecules CD C(d!1).D(c!1)
end observables
begin reaction rules
  A(b) + B(a) <-> A(b!1).B(a!1) Arrhenius(phi, Ea0)
  C(d) + D(c) <-> C(d!1).D(c!1) Arrhenius(0.5, 0)
end reaction rules
end model
generate_network({overwrite=>1})
simulate({method=>"ode",t_end=>2,n_steps=>20})
"""
    res, native_dir = _run_native_bngl(bng_cpp, "issue_360", text, tmp_path / "native")
    assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
    rows = _parse_gdat_rows(native_dir / "issue_360.gdat")
    assert rows[-1]["AB"] == pytest.approx(0.7885030220695, rel=1e-4)
    assert rows[-1]["CD"] == pytest.approx(0.4945919510607, rel=1e-4)

    retained_net_path = _run_perl_network(
        ROOT / "legacy/perl/BNG2.pl",
        "issue_360",
        text.replace('simulate({method=>"ode",t_end=>2,n_steps=>20})\n', ""),
        tmp_path / "retained",
    )
    retained_graph = compare.parse_net(retained_net_path)
    assert retained_graph is not None
    assert retained_graph.n_reactions == 4
