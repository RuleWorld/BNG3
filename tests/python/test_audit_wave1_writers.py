"""Focused regression tests for Wave-1 writer and SBML reader audit fixes.

Covers verified defects across:
- NetWriter.cpp (EXPR-01/ETH-04, ETH-01/B3/RULEHUB-02, ETH-03, NET-07, NET-15, RULEHUB-08)
- BnglWriter.cpp (EXPR-11/B7)
- XmlWriter.cpp (EXPR-02, EXPR-13, NFC-10, NFC-11, NFC-12, NFC-15, NFC-16)
- SbmlWriter.cpp, SbmlUnitWriter.cpp, SbmlMultiWriter.cpp, SbmlReader.cpp
  (EXPR-05, EXPR-06, EXPR-07, SBML-11, SBML-12, SBML-13, MEM-03, MEM-07)
- MatlabWriter.cpp, MexWriter.cpp, CppExportWriter.cpp, PythonExportWriter.cpp
  (EXPR-12, B19)
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

import bionetgen
from bionetgen import _bionetgen_cpp as cpp


def _write_net_text(tmp_path: Path, bngl: str, name: str = "model.net") -> str:
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    out = tmp_path / name
    cpp.io.write_net(model, net, str(out))
    return out.read_text(encoding="utf-8")


def _parse_net_param_values(net_text: str) -> dict[str, str]:
    in_params = False
    params: dict[str, str] = {}
    for raw_line in net_text.splitlines():
        line = raw_line.strip()
        if line == "begin parameters":
            in_params = True
            continue
        if line == "end parameters":
            break
        if not in_params or not line or line.startswith("#"):
            continue
        body = line.split("#", 1)[0].strip()
        parts = body.split(None, 2)
        if len(parts) == 3:
            params[parts[1]] = parts[2].strip()
    return params


def _parse_net_reaction_rates(net_text: str) -> list[str]:
    in_rxns = False
    rates: list[str] = []
    for raw_line in net_text.splitlines():
        line = raw_line.strip()
        if line == "begin reactions":
            in_rxns = True
            continue
        if line == "end reactions":
            break
        if not in_rxns or not line or line.startswith("#"):
            continue
        body = line.split("#", 1)[0].strip()
        parts = body.split(None, 3)
        if len(parts) == 4:
            rates.append(parts[3].strip())
    return rates


def _read_last_dat_row(path: Path) -> list[float]:
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines, f"No data rows in {path}"
    return [float(tok) for tok in lines[-1].split()]


# ---------------------------------------------------------------------------
# 1. NetWriter.cpp
# ---------------------------------------------------------------------------


def test_net_writer_energy_expression_evaluator_scientific_unary_power_and_funcs(
    tmp_path: Path,
) -> None:
    """EXPR-01 / ETH-04: evaluateExpressionString handles 1e-5, ln(10)/RT, -2^2, 2^3^2."""
    bngl = """begin model
begin parameters
    RT 2.0
    e_sci 1e-5
    e_fn ln(2)+1
    e_div ln(10)/RT
    e_unpow -2^2
    e_rpow 2^3^2
    phi 0.5
    Ea0 0.0
end parameters
begin molecule types
    A(s~0~1~2~3~4~5)
end molecule types
begin seed species
    A(s~0) 10
end seed species
begin observables
    Molecules A0 A(s~0)
end observables
begin energy patterns
    A(s~1) e_sci
    A(s~2) e_fn
    A(s~3) e_div
    A(s~4) e_unpow
    A(s~5) e_rpow
end energy patterns
begin reaction rules
    r1: A(s~0) <-> A(s~1) Arrhenius(phi, Ea0)
    r2: A(s~0) <-> A(s~2) Arrhenius(phi, Ea0)
    r3: A(s~0) <-> A(s~3) Arrhenius(phi, Ea0)
    r4: A(s~0) <-> A(s~4) Arrhenius(phi, Ea0)
    r5: A(s~0) <-> A(s~5) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    net_text = _write_net_text(tmp_path, bngl, "energy_eval.net")
    params = _parse_net_param_values(net_text)

    expected_dgs = {
        "r1": 1e-5,
        "r2": math.log(2.0) + 1.0,
        "r3": math.log(10.0) / 2.0,
        # In canonical BNGL (BNG2.pl), `-2^2` is `(-2)^2 = +4` and `2^3^2` is `(2^3)^2 = 64`.
        "r4": 4.0,
        "r5": 64.0,
    }
    # Pair each reversible transition A(s~0) <-> A(s~i) by its (reactant, product) species indices.
    # Species 1 is A(s~0); each rule r1..r5 produces a distinct species s_i with energy dG_i.
    rxn_by_pair: dict[tuple[str, str], str] = {}
    in_rxns = False
    for raw_line in net_text.splitlines():
        line = raw_line.strip()
        if line == "begin reactions":
            in_rxns = True
            continue
        if line == "end reactions":
            break
        if not in_rxns or not line or line.startswith("#"):
            continue
        body = line.split("#", 1)[0].strip()
        parts = body.split(None, 3)
        if len(parts) == 4:
            rxn_by_pair[(parts[1], parts[2])] = parts[3].strip()
    assert len(rxn_by_pair) == 10
    # Match each of the 5 forward/reverse pairs against expected_dgs (sorted by dG)
    observed_pairs = []
    for (r, p), f_tok in rxn_by_pair.items():
        if r == "1" and (p, r) in rxn_by_pair:
            r_tok = rxn_by_pair[(p, r)]
            observed_pairs.append((float(params[f_tok]), float(params[r_tok])))
    assert len(observed_pairs) == 5
    for dg in expected_dgs.values():
        exp_kf = math.exp(-0.5 * dg)
        exp_kr = math.exp(0.5 * dg)
        assert any(
            math.isclose(kf, exp_kf, rel_tol=1e-9, abs_tol=1e-12)
            and math.isclose(kr, exp_kr, rel_tol=1e-9, abs_tol=1e-12)
            for kf, kr in observed_pairs
        ), f"Missing expected pair ({exp_kf}, {exp_kr}) for dG={dg} in {observed_pairs}"


def test_net_writer_dynamic_energy_pattern_fails_closed(tmp_path: Path) -> None:
    """ETH-04: non-numeric / observable-dependent energy pattern must error, not silently return 0."""
    bngl = """begin model
begin parameters
    phi 0.5
    Ea0 0.0
end parameters
begin molecule types
    A(s~0~1)
end molecule types
begin seed species
    A(s~0) 10
end seed species
begin observables
    Molecules A0 A(s~0)
end observables
begin energy patterns
    A(s~1) A0
end energy patterns
begin reaction rules
    A(s~0) <-> A(s~1) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    with pytest.raises(RuntimeError):
        cpp.io.write_net(model, net, str(tmp_path / "dyn_energy.net"))


def test_net_writer_symmetric_energy_patterns_divide_by_automorphisms(
    tmp_path: Path,
) -> None:
    """ETH-01 / B3 / RULEHUB-02: symmetric energy patterns A(b!1).A(b!1) and R(s!+,s!+) are not double-counted."""
    dG = -2.0
    bngl = f"""begin model
begin parameters
    dG {dG}
    phi 0.5
    Ea0 0.0
end parameters
begin molecule types
    A(b)
    R(s,s)
    L(r)
end molecule types
begin seed species
    A(b) 10
    R(s,s) 1
    L(r) 10
end seed species
begin observables
    Molecules AA A(b!1).A(b!1)
    Molecules R2 R(s!+,s!+)
end observables
begin energy patterns
    A(b!1).A(b!1) dG
    R(s!+,s!+) dG
end energy patterns
begin reaction rules
    dimer: A(b) + A(b) <-> A(b!1).A(b!1) Arrhenius(phi, Ea0)
    bind: R(s) + L(r) <-> R(s!1).L(r!1) Arrhenius(phi, Ea0)
end reaction rules
end model
"""
    net_text = _write_net_text(tmp_path, bngl, "sym_energy.net")
    params = _parse_net_param_values(net_text)
    rxn_rates = _parse_net_reaction_rates(net_text)

    # Pair forward and reverse reactions by their reactants/products
    rxn_pairs: dict[tuple[str, str], str] = {}
    in_rxns = False
    for raw_line in net_text.splitlines():
        line = raw_line.strip()
        if line == "begin reactions":
            in_rxns = True
            continue
        if line == "end reactions":
            break
        if not in_rxns or not line or line.startswith("#"):
            continue
        body = line.split("#", 1)[0].strip()
        parts = body.split(None, 3)
        if len(parts) == 4:
            rxn_pairs[(parts[1], parts[2])] = parts[3].strip().split("*")[-1]

    # Dimerization: 1,1 -> 4 (or similar) and reverse 4 -> 1,1: kf/kr = exp(-dG)
    dimer_ratios = []
    other_ratios = []
    for (r, p), f_tok in rxn_pairs.items():
        if (p, r) in rxn_pairs and r < p:
            r_tok = rxn_pairs[(p, r)]
            ratio = float(params[f_tok]) / float(params[r_tok])
            if "," in r and r.split(",")[0] == r.split(",")[1]:
                dimer_ratios.append(ratio)
            elif abs(ratio - 1.0) > 1e-6:
                other_ratios.append(ratio)
    assert len(dimer_ratios) == 1
    assert math.isclose(dimer_ratios[0], math.exp(-dG), rel_tol=1e-9)
    assert len(other_ratios) == 1
    assert math.isclose(other_ratios[0], math.exp(-dG), rel_tol=1e-9)


@pytest.mark.parametrize("phi_expr", ["p1+p2", "-0.2"])
def test_net_writer_reverse_arrhenius_parenthesizes_phi(
    tmp_path: Path, phi_expr: str
) -> None:
    """ETH-03: reverse Arrhenius phi = 1-(phiArg) preserves detailed balance kf/kr == exp(-dG)."""
    dG = 3.0
    bngl = f"""begin model
begin parameters
    p1 0.2
    p2 0.3
    dG {dG}
    Ea0 1.5
end parameters
begin molecule types
    A(s~0~1)
end molecule types
begin seed species
    A(s~0) 10
end seed species
begin observables
    Molecules A1 A(s~1)
end observables
begin energy patterns
    A(s~1) dG
end energy patterns
begin reaction rules
    flip: A(s~0) <-> A(s~1) Arrhenius({phi_expr}, Ea0)
end reaction rules
end model
"""
    net_text = _write_net_text(tmp_path, bngl, f"arr_{phi_expr.replace('+', 'p')}.net")
    params = _parse_net_param_values(net_text)
    rxn_rates = _parse_net_reaction_rates(net_text)
    assert len(rxn_rates) == 2
    kf = float(params[rxn_rates[0]])
    kr = float(params[rxn_rates[1]])
    assert math.isclose(kf / kr, math.exp(-dG), rel_tol=1e-9)


def test_net_writer_total_rate_keeps_compartment_scaling_and_multi_comp_synth_unscaled(
    tmp_path: Path,
) -> None:
    """NET-07 & NET-15: TotalRate keeps compartment 1/V scaling; multi-compartment synthesis is unscaled."""
    bngl = """begin model
begin parameters
    kb 2.0
    ks 3.0
    V_ec 5.0
    V_pm 2.0
end parameters
begin compartments
    EC 3 V_ec
    PM 2 V_pm EC
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @EC:A() 10
    @PM:B() 10
end seed species
begin observables
    Molecules Atot A()
end observables
begin reaction rules
    dimer_tr: A()@EC + A()@EC -> A()@EC kb TotalRate
    synth_multi: 0 -> A()@EC + B()@PM ks
end reaction rules
end model
"""
    net_text = _write_net_text(tmp_path, bngl, "comp_tr.net")
    rxn_rates = _parse_net_reaction_rates(net_text)
    assert len(rxn_rates) == 2

    # dimer_tr: TotalRate omits symmetry factor 0.5, KEEPS 1/V_ec = 0.2 -> 0.2*kb
    assert "0.2*kb" in rxn_rates[0]
    assert "0.1*kb" not in rxn_rates[0]

    # synth_multi: products in EC and PM -> must NOT multiply ks by V_ec (5) or V_pm (2)
    assert rxn_rates[1] == "ks"


def test_net_writer_emits_valid_expressions_and_roundtrips_via_readfile(
    tmp_path: Path,
) -> None:
    """RULEHUB-08: .net uses if(c,a,b), avoids --x, avoids Obs() parens, and round-trips."""
    bngl = """begin model
begin parameters
    k 0.5
    l_A 1.0
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Aobs A()
end observables
begin functions
    rate_fn() = if(Aobs > 5, -(-k), 0.1 * k)
end functions
begin reaction rules
    A() -> 0 rate_fn()
end reaction rules
end model
"""
    net_text = _write_net_text(tmp_path, bngl, "expr_rt.net")
    assert "if(" in net_text
    assert "if (" not in net_text
    assert "--" not in net_text
    assert "Aobs()" not in net_text

    # Direct ODE vs readFile(.net) ODE must match
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    direct = cpp.simulate_ode(model, net, t_end=2.0, n_steps=10)

    driver = tmp_path / "run_net.bngl"
    driver.write_text(
        'readFile({file=>"expr_rt.net"})\n'
        'simulate({method=>"ode",t_end=>2.0,n_steps=>10,prefix=>"expr_rt_out"})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(driver)).execute()
    last_row = _read_last_dat_row(tmp_path / "expr_rt_out.gdat")
    assert math.isclose(last_row[1], direct["observables"]["Aobs"][-1], rel_tol=1e-5)


# ---------------------------------------------------------------------------
# 2. BnglWriter.cpp
# ---------------------------------------------------------------------------


def test_bngl_writer_preserves_function_args_header_and_popmaps() -> None:
    """EXPR-11 / B7: BnglWriter emits formal function arguments, setOption, version, substanceUnits, pop maps."""
    bngl = """version("2.8.0")
substanceUnits("Number")
setOption("NumberPerQuantityUnit",6.02214076e23)
begin model
begin parameters
    k 0.5
    l_A 1.0
end parameters
begin molecule types
    A()
    P_A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Aobs A()
end observables
begin functions
    scale(x, y) = x * y + k
end functions
begin population maps
    A() -> P_A() l_A
end population maps
begin reaction rules
    A() -> 0 scale(2, 3)
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    emitted = cpp.io.write_bngl_string(model)

    assert "scale(x, y) =" in emitted
    assert 'version("2.8.0")' in emitted
    assert 'substanceUnits("Number")' in emitted
    assert 'setOption("NumberPerQuantityUnit"' in emitted
    assert "begin population maps" in emitted
    assert "end population maps" in emitted

    # Reparse emitted BNGL and confirm identical simulation
    reparsed = cpp.parse_string(emitted)
    net1 = cpp.generate_network(model)
    net2 = cpp.generate_network(reparsed)
    sim1 = cpp.simulate_ode(model, net1, t_end=1.0, n_steps=5)
    sim2 = cpp.simulate_ode(reparsed, net2, t_end=1.0, n_steps=5)
    np.testing.assert_allclose(
        sim1["observables"]["Aobs"], sim2["observables"]["Aobs"], rtol=1e-9, atol=1e-12
    )


# ---------------------------------------------------------------------------
# 3. XmlWriter.cpp
# ---------------------------------------------------------------------------


def test_xml_writer_time_precision_sat_reverse_names_and_muparser(
    tmp_path: Path,
) -> None:
    """EXPR-02, EXPR-13, NFC-10, NFC-11, NFC-12, NFC-15, NFC-16."""
    bngl = """begin model
begin parameters
    T 298.15
    t 5.0
    k_hi 0.23748464179239356
    V_hi 1000001
    A0 1000001
    k0 1.2
    K1 0.4
    K2 0.7
end parameters
begin compartments
    EC 3 V_hi
end compartments
begin molecule types
    A(b)
    B(a)
end molecule types
begin seed species
    @EC:A(b) A0
    @EC:B(a) 10
end seed species
begin observables
    Molecules Aobs A()
end observables
begin functions
    f_temp() = T * t + k_hi
    f_expr() = -(-k0) + (2 ** 3) + (Aobs % 3) + (~(Aobs ~= 0)) + ((Aobs > 1) ^^ (Aobs < 5))
end functions
begin reaction rules
    A(b)@EC + B(a)@EC <-> A(b!1).B(a!1)@EC k0, K1
    A(b)@EC <-> B(a)@EC k0, K1
    sat3: A(b)@EC + B(a)@EC -> A(b!1).B(a!1)@EC Sat(k0, K1, K2)
    expr_r: A(b)@EC -> 0 f_expr()
    temp_r: B(a)@EC -> 0 f_temp()
end reaction rules
end model
"""
    # 1) Direct write_xml_string checks
    model = cpp.parse_string(bngl)
    xml_str = cpp.io.write_xml_string(model)
    root = ET.fromstring(xml_str)
    ns = {"b": "http://www.sbml.org/sbml/level3"}

    # EXPR-02: T and user-declared t must be Constant references, NEVER Time
    refs = root.findall(".//b:Function[@id='f_temp']//b:Reference", ns)
    ref_map = {r.attrib["name"]: r.attrib["type"] for r in refs}
    assert ref_map.get("T") == "Constant"
    assert ref_map.get("t") == "Constant"

    # NFC-12: Full 17-digit precision for Parameter, Compartment, Species
    param_map = {
        p.attrib["id"]: p.attrib["value"]
        for p in root.findall(".//b:ListOfParameters/b:Parameter", ns)
    }
    assert math.isclose(float(param_map["k_hi"]), 0.23748464179239356, rel_tol=1e-15)
    assert math.isclose(float(param_map["V_hi"]), 1000001.0, rel_tol=1e-15)
    comp_ec = root.find(".//b:ListOfCompartments/b:Compartment[@id='EC']", ns)
    assert comp_ec is not None
    assert math.isclose(float(comp_ec.attrib["size"]), 1000001.0, rel_tol=1e-15)
    sp_a = root.find(".//b:ListOfSpecies/b:Species[@id='S1']", ns)
    assert sp_a is not None
    assert math.isclose(float(sp_a.attrib["concentration"]), 1000001.0, rel_tol=1e-15)

    # NFC-16: Unlabeled bidirectional rules have unique reverse rule names
    rule_names = [
        r.attrib["name"]
        for r in root.findall(".//b:ListOfReactionRules/b:ReactionRule", ns)
    ]
    assert len(rule_names) == len(set(rule_names)), f"Duplicate rule names: {rule_names}"
    assert "_reverse" not in rule_names

    # NFC-10: 3-arg Sat stays type="Sat" with 3 RateConstants
    sat_rule = root.find(".//b:ReactionRule[@name='sat3']/b:RateLaw", ns)
    assert sat_rule is not None
    assert sat_rule.attrib["type"] == "Sat"
    assert len(sat_rule.findall("./b:ListOfRateConstants/b:RateConstant", ns)) == 3

    # NFC-15: muParser syntax (no **, no --, no raw ~, ~=, ^^, %)
    expr_el = root.find(".//b:Function[@id='f_expr']/b:Expression", ns)
    assert expr_el is not None and expr_el.text is not None
    expr_txt = expr_el.text
    assert "**" not in expr_txt
    assert "--" not in expr_txt
    assert "~=" not in expr_txt
    assert "~" not in expr_txt
    assert "^^" not in expr_txt
    assert "%" not in expr_txt
    assert "^" in expr_txt

    # NFC-11: writeXML() after generate_network() preserves compartment on species
    src = tmp_path / "comp_xml.bngl"
    src.write_text(
        bngl + "\ngenerate_network({overwrite=>1})\nwriteXML({overwrite=>1})\n",
        encoding="utf-8",
    )
    bionetgen.load(str(src)).execute()
    gen_xml = (tmp_path / "comp_xml.xml").read_text(encoding="utf-8")
    gen_root = ET.fromstring(gen_xml)
    gen_species = gen_root.findall(".//b:ListOfSpecies/b:Species", ns)
    assert gen_species
    for sp in gen_species:
        assert sp.attrib.get("compartment") == "EC"
        assert sp.attrib.get("name", "").startswith("@EC::")


# ---------------------------------------------------------------------------
# 4. SbmlWriter, SbmlUnitWriter, SbmlMultiWriter, SbmlReader
# ---------------------------------------------------------------------------


def test_sbml_writer_mathml_operators_functions_and_l2_rem(tmp_path: Path) -> None:
    """EXPR-05 / SBML-11: unary ~, log10, log2, rint, sum, avg, sign, Sat/MM/Hill, L2 no <rem/>, fail-closed mratio."""
    bngl = """begin model
begin parameters
    a 4.0
    b 2.0
    k0 1.0
    K1 0.5
    K2 0.25
    n 2.0
end parameters
begin molecule types
    A()
    B()
end molecule types
begin seed species
    A() 10
    B() 5
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin functions
    f_ops() = (~a) + log10(100) + log2(8) + rint(2.4) + sum(a, b) + avg(a, b) + sign(a - b) + (Aobs % 3) + if(Aobs, 1, 0) + (Aobs && Bobs)
end functions
begin reaction rules
    r_ops: A() -> 0 f_ops()
    r_sat3: A() + B() -> 0 Sat(k0, K1, K2)
    r_mm: A() + B() -> 0 MM(k0, K1)
    r_hill: A() -> 0 Hill(k0, K1, n)
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    out_l2 = tmp_path / "ops_l2.xml"
    cpp.io.write_sbml(model, net, str(out_l2), level=2)
    xml_text = out_l2.read_text(encoding="utf-8")

    # No L3-only <rem/> in Level 2 SBML
    assert "<rem/>" not in xml_text
    # No unlowered bare function identifiers
    for bad in ("<ci> log10 </ci>", "<ci> log2 </ci>", "<ci> rint </ci>",
                "<ci> sum </ci>", "<ci> avg </ci>", "<ci> sign </ci>",
                "<ci> sat </ci>", "<ci> Sat </ci>", "<ci> MM </ci>", "<ci> Hill </ci>"):
        assert bad not in xml_text
    # logbase used for log10/log2, piecewise used for if/sign/rem/boolean coercion
    assert "<logbase>" in xml_text
    assert "<piecewise>" in xml_text

    # Optional libSBML structural check if installed
    try:
        import libsbml  # type: ignore
    except ImportError:
        libsbml = None
    if libsbml is not None:
        doc = libsbml.readSBMLFromFile(str(out_l2))
        assert doc.getNumErrors(libsbml.LIBSBML_SEV_ERROR) == 0

    # Fail-closed on unsupported mratio
    bngl_mratio = """begin model
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin functions
    fm() = mratio(1, 2, 3)
end functions
begin reaction rules
    A() -> 0 fm()
end reaction rules
end model
"""
    m_bad = cpp.parse_string(bngl_mratio)
    n_bad = cpp.generate_network(m_bad)
    with pytest.raises((ValueError, RuntimeError)):
        cpp.io.write_sbml(m_bad, n_bad, str(tmp_path / "mratio.xml"))


def test_sbml_unit_writer_l2_scale_and_valid_id_disambiguation(tmp_path: Path) -> None:
    """EXPR-06 & EXPR-07: cm^3 has scale=-2 (not -6), um^2 has scale=-6; metre/second != metre*second."""
    bngl = """setOption("units", "strict")
begin model
begin units
    timeUnits second
    substanceUnits item
    volumeUnits cm^3
    areaUnits um^2
    extentUnits item
end units
begin parameters
    k_div = 1.0 [metre/second]
    k_mul = 2.0 [metre*second]
    k_decay = 0.5 [second^-1]
end parameters
begin compartments
    EC 3 1 [cm^3]
    PM 2 1 EC [um^2]
end compartments
begin molecule types
    A()
end molecule types
begin seed species
    @EC:A() 10 [item]
end seed species
begin reaction rules
    A()@EC -> 0 k_decay
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)
    out_l2 = tmp_path / "units_l2.xml"
    cpp.io.write_sbml(model, net, str(out_l2), level=2)
    root = ET.parse(out_l2).getroot()

    unit_defs = {}
    for ud in root.iter():
        if ud.tag.endswith("unitDefinition"):
            uid = ud.attrib["id"]
            assert uid not in unit_defs, f"Duplicate unitDefinition id: {uid}"
            units = [u.attrib for u in ud.iter() if u.tag.endswith("unit")]
            unit_defs[uid] = units

    assert "volume" in unit_defs
    assert any(
        u.get("kind") == "metre" and u.get("exponent") == "3" and u.get("scale") == "-2"
        for u in unit_defs["volume"]
    ), f"Unexpected L2 volume unitDefinition: {unit_defs['volume']}"

    assert "area" in unit_defs
    assert any(
        u.get("kind") == "metre" and u.get("exponent") == "2" and u.get("scale") == "-6"
        for u in unit_defs["area"]
    ), f"Unexpected L2 area unitDefinition: {unit_defs['area']}"

    # Parameter units for [metre/second] and [metre*second] must have distinct unit IDs
    param_units = {}
    for p in root.iter():
        if p.tag.endswith("parameter") and "id" in p.attrib and "units" in p.attrib:
            param_units[p.attrib["id"]] = p.attrib["units"]
    assert "k_div" in param_units and "k_mul" in param_units
    assert param_units["k_div"] != param_units["k_mul"]


def test_sbml_multi_writer_emits_functions_and_lowers_sat() -> None:
    """SBML-12: SbmlMultiWriter emits BNGL functions and lowers Sat()."""
    bngl = """begin model
begin parameters
    k0 2.0
    K1 0.5
end parameters
begin molecule types
    A()
end molecule types
begin seed species
    A() 10
end seed species
begin observables
    Molecules Aobs A()
end observables
begin functions
    f_zero() = k0 * Aobs
    f_arg(x) = x + 1
end functions
begin reaction rules
    r1: A() -> 0 f_zero()
    r2: A() -> 0 Sat(k0, K1)
    r3: A() -> 0 f_arg(Aobs)
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    xml_str = cpp.viz.write_sbml_multi(model)
    root = ET.fromstring(xml_str)

    # Parameterized function emitted as <functionDefinition id="f_arg">
    fn_ids = [
        el.attrib["id"]
        for el in root.iter()
        if el.tag.endswith("functionDefinition") and "id" in el.attrib
    ]
    assert "f_arg" in fn_ids

    # Zero-arg function emitted as assignmentRule targeting f_zero
    rule_vars = [
        el.attrib["variable"]
        for el in root.iter()
        if el.tag.endswith("assignmentRule") and "variable" in el.attrib
    ]
    assert "f_zero" in rule_vars

    # Sat() lowered (no bare <ci> Sat </ci>)
    assert "<ci> Sat </ci>" not in xml_str
    assert "<ci> sat </ci>" not in xml_str


def test_sbml_reader_enotation_root_units_assignment_and_safety_guards(
    tmp_path: Path,
) -> None:
    """SBML-13, MEM-03, MEM-07: e-notation, root degree, unit multiplier^exp, assignmentRule, depth & stoich caps."""
    # 1) e-notation + root degree + unit multiplier^exponent + weighted & nonlinear assignmentRule
    sbml_ok = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="reader_audit">
    <listOfUnitDefinitions>
      <unitDefinition id="min_sq">
        <listOfUnits>
          <unit kind="second" exponent="2" scale="0" multiplier="60"/>
        </listOfUnits>
      </unitDefinition>
      <unitDefinition id="per_s">
        <listOfUnits>
          <unit kind="second" exponent="-1" scale="0" multiplier="1"/>
        </listOfUnits>
      </unitDefinition>
    </listOfUnitDefinitions>
    <listOfCompartments>
      <compartment id="cell" size="1" units="litre"/>
    </listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="cell" initialAmount="10"/>
      <species id="S2" compartment="cell" initialAmount="10"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k_rate" value="1" units="per_s" constant="false"/>
      <parameter id="p_lin" value="0" constant="false"/>
      <parameter id="p_nonlin" value="0" constant="false"/>
    </listOfParameters>
    <listOfRules>
      <assignmentRule variable="k_rate">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <times/>
            <cn type="e-notation"> 5 <sep/> -2 </cn>
            <apply>
              <root/>
              <degree><cn type="integer"> 3 </cn></degree>
              <cn> 8 </cn>
            </apply>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="p_lin">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <times/>
            <cn> 2 </cn>
            <ci> S1 </ci>
          </apply>
        </math>
      </assignmentRule>
      <assignmentRule variable="p_nonlin">
        <math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply>
            <divide/>
            <ci> S1 </ci>
            <apply><plus/><ci> S1 </ci><ci> S2 </ci></apply>
          </apply>
        </math>
      </assignmentRule>
    </listOfRules>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants>
          <speciesReference species="S1" stoichiometry="1"/>
        </listOfReactants>
        <kineticLaw>
          <math xmlns="http://www.w3.org/1998/Math/MathML">
            <apply>
              <times/>
              <ci> k_rate </ci>
              <ci> S1 </ci>
            </apply>
          </math>
        </kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
    sbml_path = tmp_path / "reader_audit.xml"
    sbml_path.write_text(sbml_ok, encoding="utf-8")
    parsed = cpp.io.read_sbml(str(sbml_path))
    assert parsed["success"], parsed["error"]

    # Simulate via readSBML: k_rate = 5e-2 * cbrt(8) = 0.05 * 2 = 0.1
    # => S1(2) = 10 * exp(-0.2)
    driver = tmp_path / "run_sbml.bngl"
    driver.write_text(
        'readSBML({file=>"reader_audit.xml",basename=>"reader_audit_out"})\n'
        'simulate({method=>"ode",t_end=>2,n_steps=>4})\n',
        encoding="utf-8",
    )
    bionetgen.load(str(driver)).execute()
    row = _read_last_dat_row(tmp_path / "reader_audit_out.cdat")
    assert math.isclose(row[1], 10.0 * math.exp(-0.2), rel_tol=1e-4)

    # 2) MEM-03: Deeply nested MathML (>256) fails cleanly without stack overflow
    depth = 300
    nested = "<apply><plus/><cn>1</cn>" * depth + "<cn>1</cn>" + "</apply>" * depth
    sbml_deep = f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="deep">
    <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
    <listOfSpecies><species id="S1" compartment="c" initialAmount="1"/></listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="S1" stoichiometry="1"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">{nested}</math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
    deep_path = tmp_path / "deep.xml"
    deep_path.write_text(sbml_deep, encoding="utf-8")
    deep_res = cpp.io.read_sbml(str(deep_path))
    assert not deep_res["success"]
    assert "depth" in deep_res["error"].lower()

    # 3) MEM-07: Huge stoichiometry (>10000) fails cleanly without OOM
    sbml_stoich = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level2/version4" level="2" version="4">
  <model id="huge_stoich">
    <listOfCompartments><compartment id="c" size="1"/></listOfCompartments>
    <listOfSpecies><species id="S1" compartment="c" initialAmount="1"/></listOfSpecies>
    <listOfReactions>
      <reaction id="R1" reversible="false">
        <listOfReactants><speciesReference species="S1" stoichiometry="1000000000"/></listOfReactants>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><cn>1</cn></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
    stoich_path = tmp_path / "huge_stoich.xml"
    stoich_path.write_text(sbml_stoich, encoding="utf-8")
    stoich_res = cpp.io.read_sbml(str(stoich_path))
    assert not stoich_res["success"]
    assert "stoichiometry" in stoich_res["error"].lower()


# ---------------------------------------------------------------------------
# 5. MatlabWriter, MexWriter, CppExportWriter, PythonExportWriter
# ---------------------------------------------------------------------------


def test_code_export_writers_compartments_pow_and_python_math(tmp_path: Path) -> None:
    """EXPR-12 / B19: compartment 1/V & *V scaling, pow() in C/C++, math.* import/prefix in Python."""
    bngl = """begin model
begin parameters
    V_ec 5.0
    k_base 2.0
    k_pow k_base^2
    ks 3.0
end parameters
begin compartments
    EC 3 V_ec
end compartments
begin molecule types
    A()
    B()
end molecule types
begin seed species
    @EC:A() 4.0
    @EC:B() 2.0
end seed species
begin observables
    Molecules Aobs A()
    Molecules Bobs B()
end observables
begin reaction rules
    bind: A()@EC + B()@EC -> 0 exp(-0.05 * k_base) * k_pow
    synth: 0 -> A()@EC ks
end reaction rules
end model
"""
    model = cpp.parse_string(bngl)
    net = cpp.generate_network(model)

    # 1) MexWriter: emits pow(..., ...) instead of ^ and scales bimolecular by 1/V_ec=0.2 and synthesis by V_ec=5
    mex_c = cpp.io.write_mex_string(model, net)
    assert "pow(" in mex_c
    assert "^" not in mex_c
    # Bimolecular factor 0.2 and zero-order synthesis factor 5
    assert re.search(r"ratelaws\[0\].*0\.2", mex_c)
    assert re.search(r"ratelaws\[1\].*5\*", mex_c)

    # 2) export_sympy_odes (uses MexWriter): preserves compartment 1/V and *V scaling!
    try:
        import sympy  # type: ignore
        from bionetgen.modelapi.sympy_odes import export_sympy_odes
    except ImportError:
        sympy = None
    if sympy is not None:
        bngl_file = tmp_path / "sympy_comp.bngl"
        bngl_file.write_text(bngl, encoding="utf-8")
        sym_res = export_sympy_odes(str(bngl_file), out_dir=str(tmp_path / "sym"))
        # Substitute default parameter values & initial species [A=4, B=2]
        subs = dict(zip(sym_res.params, [5.0, 2.0, 4.0, 3.0]))
        subs.update(dict(zip(sym_res.species, [4.0, 2.0])))
        # dA/dt = - (1/5) * exp(-0.1) * 4 * (4 * 2) + 5 * 3
        expected_dA = -(1.0 / 5.0) * math.exp(-0.1) * 4.0 * 8.0 + 5.0 * 3.0
        actual_dA = float(sym_res.odes[0].evalf(subs=subs))
        assert math.isclose(actual_dA, expected_dA, rel_tol=1e-9)

    # 3) MatlabWriter: compartment volume scaling present
    matlab_path = tmp_path / "comp_export.m"
    cpp.io.write_matlab(model, net, str(matlab_path))
    matlab_text = matlab_path.read_text(encoding="utf-8")
    assert re.search(r"ratelaws\(1\).*0\.2", matlab_text)
    assert re.search(r"ratelaws\(2\).*5\*", matlab_text)

    # 4) CppExportWriter: emits pow(..., ...) instead of ^ and scales by compartment volume
    driver_cpp = tmp_path / "export_all.bngl"
    driver_cpp.write_text(
        bngl
        + "\ngenerate_network({overwrite=>1})\n"
        + "writeCPPfile({overwrite=>1})\n"
        + "writeCPYfile({overwrite=>1,t_start=>0,t_end=>1,n_steps=>10})\n",
        encoding="utf-8",
    )
    bionetgen.load(str(driver_cpp)).execute()

    cpp_h = (tmp_path / "export_all_cvode.h").read_text(encoding="utf-8")
    assert "pow(" in cpp_h
    assert "k_base^2" not in cpp_h
    assert re.search(r"NV_Ith_S\(ratelaws,0\).*0\.2", cpp_h)
    assert re.search(r"NV_Ith_S\(ratelaws,1\).*5\*", cpp_h)

    # 5) PythonExportWriter: imports math, prefixes math.exp, executes with no NameError,
    #    and matches native CVODE ODE trajectory (including compartment scaling & derived k_pow)!
    py_code = (tmp_path / "export_all_pyode.py").read_text(encoding="utf-8")
    assert "import math" in py_code
    assert "math.exp(" in py_code
    ns: dict = {}
    exec(compile(py_code, "<exported_pyode>", "exec"), ns)
    times = np.linspace(0.0, 1.0, 11)
    _, _, obs_py = ns["simulate"](times)
    native = cpp.simulate_ode(model, net, t_end=1.0, n_steps=10)
    np.testing.assert_allclose(obs_py[:, 0], native["observables"]["Aobs"], rtol=1e-4, atol=1e-5)
    np.testing.assert_allclose(obs_py[:, 1], native["observables"]["Bobs"], rtol=1e-4, atol=1e-5)
