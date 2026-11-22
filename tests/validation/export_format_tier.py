"""Export-format tier: semantic round trips, downstream consumption, refusal.

Issue #163 ("E07: Populate format Tier-X with semantic and consumer-level
checks") asks for a nonempty tier of supported export formats whose exported
forms are qualified semantically, not merely for validity.

This module populates that tier with generated model cases and the export
formats the public model API exposes (``python/bionetgen/model.py`` and
``python/bionetgen/viz.py``). For every generated case and every round-trip
format it

* writes the model through the public model API,
* reads the exported form back,
* compares the resolved semantics against an independent expectation -- the
  closed-form law of the source model, and the source model's own entities
  recomputed from the source -- never against the writer's own output, and
* checks that the format's named downstream consumer can use the exported
  form.

For every format that cannot represent a feature the source model uses, the
tier requires an *explicit refusal* that names the unsupported feature. A
silent loss is a failure: the writer must raise, must say what it cannot
represent, and must not leave a plausible-looking artifact behind.

Tier boundaries (stated so that a passing report is not read as a broader
claim than it is):

* ``ROUNDTRIP_FORMATS`` are the formats with a supported read-back path.
  Their exported forms are re-read and executed.
* ``REFUSAL_FORMATS`` cannot represent eBNGL energy semantics. They are
  checked on an energy model, where the required outcome is a refusal.
* ``ENERGY_CAPABLE_FORMATS`` are the formats that *can* represent the same
  feature. They are checked on the same energy model and must not refuse, so
  that a blanket refusal of the model cannot pass as a format-specific one.

Structural and visualization outputs (contact maps, rule/influence/process
graphs) are deliberately outside the kinetics scope of this tier: they do not
claim to carry rate laws, so the absence of a kinetic feature in them is not
a loss. They are inventoried by the separate inventory obligation.

The module is import-safe: it only touches ``bionetgen``, ``numpy`` and the
optional independent consumers (``libsbml``/``libroadrunner``) when it runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

import numpy as np

from .campaign import STATUSES

try:  # The compiled extension is only required when the tier actually runs.
    import bionetgen
except ImportError:  # pragma: no cover - exercised by the harness guard
    bionetgen = None

ISSUES = (163,)

# --------------------------------------------------------------------------- #
# Generated model family and its independent closed-form law.
# --------------------------------------------------------------------------- #

TIMES = np.linspace(0.0, 2.0, 11)
T_END = 2.0
N_STEPS = 10
SOLVER_RTOL = 1e-10
SOLVER_ATOL = 1e-12

# The exported artifacts are compared against the analytic law of the source
# model. The tolerance admits the numerical error of the ODE solver and the
# twelve significant digits the CLI writes, and is far below the difference a
# wrong rate law, a wrong stoichiometry or a dropped species would produce.
LAW_RTOL = 1e-6
LAW_ATOL = 1e-6
# Two executions of the same model (source versus read-back) agree to the
# solver's own accuracy; the CLI's .gdat keeps twelve significant digits.
VALUE_RTOL = 1e-7
VALUE_ATOL = 1e-6

CASE_SPECS = (
    {
        "id": "conversion",
        "kind": "conversion",
        "rate": 0.4,
        "initial": 40.0,
        "seeds": {"A()": 40.0, "B()": 0.0},
        "description": "irreversible first-order conversion A() -> B()",
    },
    {
        "id": "reversible",
        "kind": "reversible",
        "forward": 0.4,
        "reverse": 0.2,
        "initial": 40.0,
        "seeds": {"A()": 40.0, "B()": 0.0},
        "description": "reversible first-order conversion A() <-> B()",
    },
)

# The model whose energy semantics the refusing formats cannot express.
ENERGY_MODEL = """begin model
begin parameters
  Gf 0.5
  phi 0.5
  Ea 1
end parameters
begin molecule types
  A(s~U~P)
end molecule types
begin energy patterns
  A(s~U) Gf
end energy patterns
begin seed species
  A(s~U) 10
  A(s~P) 0
end seed species
begin reaction rules
  flip: A(s~U) <-> A(s~P) Arrhenius(phi,Ea)
end reaction rules
end model
"""

ENERGY_FEATURE = "energy patterns"

ROUNDTRIP_FORMATS = ("bngl", "net", "sbml")
REFUSAL_FORMATS = ("sbml", "sbml-multi", "matlab", "latex")
ENERGY_CAPABLE_FORMATS = ("bngl", "bng-xml", "net")

# The consumer that must be able to use each round-trip format's output.
CONSUMERS = {
    "bngl": "BioNetGen parser and engine (the re-imported model is executed)",
    "net": "BioNetGen native CLI in a separate process (the .net is read back)",
    "sbml": "libRoadRunner (an independent SBML simulator)",
}


def cases():
    """Return the generated model cases of the tier."""
    return [dict(spec) for spec in CASE_SPECS]


def case_bngl(case):
    """Return the BNGL source of a generated case."""
    if case["kind"] == "conversion":
        rules = "  convert: A() -> B() k\n"
        parameters = "  k 0.4\n  N 40\n"
    elif case["kind"] == "reversible":
        rules = "  forward: A() -> B() kf\n  backward: B() -> A() kr\n"
        parameters = "  kf 0.4\n  kr 0.2\n  N 40\n"
    else:  # pragma: no cover - protected by the static case table
        raise ValueError(f"unknown case kind: {case['kind']!r}")
    return (
        "begin model\n"
        "begin parameters\n"
        f"{parameters}"
        "end parameters\n"
        "begin molecule types\n"
        "  A()\n"
        "  B()\n"
        "end molecule types\n"
        "begin seed species\n"
        "  A() N\n"
        "  B() 0\n"
        "end seed species\n"
        "begin observables\n"
        "  Molecules A A()\n"
        "  Molecules B B()\n"
        "end observables\n"
        "begin reaction rules\n"
        f"{rules}"
        "end reaction rules\n"
        "end model\n"
    )


def case_law(case):
    """Return the closed-form observable trajectories of a generated case.

    This is the independent expectation: it is derived from the case
    parameters, not from anything a writer produced.
    """
    times = TIMES
    initial = case["initial"]
    if case["kind"] == "conversion":
        a = initial * np.exp(-case["rate"] * times)
    elif case["kind"] == "reversible":
        equilibrium = initial * case["reverse"] / (case["forward"] + case["reverse"])
        a = equilibrium + (initial - equilibrium) * np.exp(
            -(case["forward"] + case["reverse"]) * times
        )
    else:  # pragma: no cover - protected by the static case table
        raise ValueError(f"unknown case kind: {case['kind']!r}")
    return {"A": a, "B": initial - a}


def check_ids():
    """Declare the expected evidence identities independently of execution."""
    ids = []
    for case in cases():
        for fmt in ROUNDTRIP_FORMATS:
            ids.append(f"export-format-tier:{case['id']}:{fmt}:roundtrip-semantics")
            ids.append(f"export-format-tier:{case['id']}:{fmt}:downstream-consumption")
    for fmt in REFUSAL_FORMATS:
        ids.append(f"export-format-tier:refusal:{fmt}:explicit-refusal")
    for fmt in ENERGY_CAPABLE_FORMATS:
        ids.append(f"export-format-tier:energy-control:{fmt}:feature-preserved")
    return ids


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def _row(check, status, detail, *, first_difference=None, artifact=None):
    row = {
        "id": check,
        "check": check.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "evidence_kind": {
            "PASS": "supported-execution",
            "UNSUPPORTED": "diagnostic-only",
            "FAIL": "supported-execution",
        }.get(status, "harness-error"),
        "supported_execution": status == "PASS",
    }
    if artifact is not None:
        row["source_artifact"] = artifact.name
        row["source_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return row


def _boundary_row(check, status, detail, *, first_difference=None):
    """A refusal check proves a boundary, so it is never support evidence.

    The same convention as the Atomizer boundary controls: a recorded refusal
    demonstrates that a construct is outside the format, not that the format
    supports anything.
    """
    row = _row(check, status, detail, first_difference=first_difference)
    row["evidence_kind"] = "diagnostic-only"
    row["supported_execution"] = False
    return row


def _failed(check, detail, difference=None, artifact=None):
    return _row(check, "FAIL", detail, first_difference=difference, artifact=artifact)


def _unsupported(check, detail, artifact=None):
    return _row(
        check,
        "UNSUPPORTED",
        detail,
        first_difference={"field": check.rsplit(":", 1)[-1]},
        artifact=artifact,
    )


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #


def _write_format(model, fmt, path):
    """Write the model in the named format through the public model API."""
    if fmt == "bngl":
        model.write_bngl(str(path))
    elif fmt == "bng-xml":
        model.write_xml(str(path))
    elif fmt == "net":
        model.write_net(str(path))
    elif fmt == "sbml":
        model.write_sbml(str(path))
    elif fmt == "sbml-multi":
        model.sbml_multi(str(path))
    elif fmt == "matlab":
        model.write_matlab(str(path))
    elif fmt == "latex":
        model.write_latex(str(path))
    else:
        raise ValueError(f"unknown export format: {fmt!r}")
    if not path.is_file():
        raise RuntimeError(f"{fmt} export produced no file at {path}")
    return path


# --------------------------------------------------------------------------- #
# Independent expectations
# --------------------------------------------------------------------------- #


def _model_entities(model):
    """Return the semantic entities of a model, recomputed from the model."""
    return {
        "parameters": {p.name: float(p.value) for p in model.parameters},
        "molecule_types": sorted(m.name for m in model.molecule_types),
        "seed_species": sorted(
            (s.pattern, s.amount.to_string(), s.compartment) for s in model.seed_species
        ),
        "observables": sorted(
            (o.name, o.type, tuple(o.patterns)) for o in model.observables
        ),
        "reaction_rules": sorted(
            (
                r.label,
                tuple(r.reactant_patterns),
                tuple(r.product_patterns),
                tuple(r.rates),
            )
            for r in model.reaction_rules
        ),
    }


def _observables(model):
    """Return the model's observable values on the tier's time grid."""
    result = model.simulate(
        method="ode",
        t_end=T_END,
        n_steps=N_STEPS,
        rtol=SOLVER_RTOL,
        atol=SOLVER_ATOL,
    )
    values = {
        name: np.asarray(v, dtype=float) for name, v in result.observables.items()
    }
    return values


def _compare_values(observed, expected, *, rtol, atol):
    """Compare observable value maps; return (ok, first difference)."""
    if set(observed) != set(expected):
        return False, {
            "field": "observable-names",
            "expected": sorted(expected),
            "observed": sorted(observed),
            "missing": sorted(set(expected) - set(observed)),
            "unexpected": sorted(set(observed) - set(expected)),
        }
    for name in sorted(expected):
        want = np.asarray(expected[name], dtype=float)
        got = np.asarray(observed[name], dtype=float)
        if got.shape != want.shape:
            return False, {
                "field": name,
                "expected_shape": list(want.shape),
                "observed_shape": list(got.shape),
            }
        if not np.allclose(got, want, rtol=rtol, atol=atol):
            index = int(np.argmax(np.abs(got - want)))
            return False, {
                "field": name,
                "index": index,
                "expected": float(want[index]),
                "observed": float(got[index]),
            }
    return True, None


def _compare_entities(observed, expected):
    """Compare two semantic-entity snapshots; return (ok, first difference)."""
    for key in sorted(expected):
        if observed.get(key) != expected[key]:
            return False, {
                "field": key,
                "expected": expected[key],
                "observed": observed.get(key),
            }
    return True, None


# --------------------------------------------------------------------------- #
# Round-trip routes
# --------------------------------------------------------------------------- #


def _run_cli(bng_cpp, work_dir, source_text):
    """Run the native CLI on a BNGL source; return (returncode, output)."""
    source = work_dir / "model.bngl"
    source.write_text(source_text, encoding="utf-8")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(Path(bng_cpp).parent), env.get("PATH", "")])
    proc = subprocess.run(
        [str(bng_cpp), "model.bngl"],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _net_route(case, directory, bng_cpp):
    """Reload the exported .net with the native CLI and simulate it.

    Returns (values, reloaded network, error).
    """
    from . import compare

    work = directory / "net-consumer"
    work.mkdir(parents=True, exist_ok=True)
    exported = directory / f"{case['id']}.export.net"
    (work / "export.net").write_bytes(exported.read_bytes())
    wrapper = (
        "begin model\nend model\nbegin actions\n"
        '  readFile({file=>"export.net"})\n'
        '  simulate_ode({t_end=>2,n_steps=>10,prefix=>"reload"})\n'
        '  writeNetwork({prefix=>"reloaded",overwrite=>1})\n'
        "end actions\n"
    )
    code, output = _run_cli(bng_cpp, work, wrapper)
    if code != 0:
        return None, None, f"the native CLI failed to consume the .net: {output}"
    gdat = work / "reload.gdat"
    if not gdat.is_file():
        return None, None, "the native CLI produced no trajectory for the .net"
    data, columns = compare.parse_gdat(gdat)
    if data is None:
        return None, None, f"the native CLI wrote an unreadable trajectory: {gdat}"
    reloaded = work / "reloaded.net"
    if not reloaded.is_file():
        return None, None, "the native CLI produced no reloaded network"
    network = compare.parse_net(reloaded)
    if network is None:
        return None, None, f"the native CLI wrote an unreadable network: {reloaded}"
    values = {
        name: data[:, index]
        for index, name in enumerate(columns)
        if name != "time" and index < data.shape[1]
    }
    return values, network, None


def _sbml_route(exported):
    """Load the exported SBML with the independent consumers.

    Returns a record with ``status`` in {"ok", "unavailable", "invalid"}:
    "unavailable" means an independent consumer is not installed, "invalid"
    means an installed consumer rejected the exported document.
    """
    try:
        import libsbml
    except ImportError as exc:
        return dict(status="unavailable", detail=f"libSBML is unavailable: {exc}")
    try:
        document = libsbml.readSBMLFromFile(str(exported))
    except Exception as exc:  # pragma: no cover - defensive
        return dict(
            status="invalid",
            detail=f"libSBML could not read the exported SBML: {exc}",
        )
    errors = [
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
        if document.getError(index).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    if errors:
        return dict(
            status="invalid",
            detail=f"libSBML rejected the exported SBML: {' | '.join(errors)}",
        )
    model = document.getModel()
    structure = {
        "species": sorted(
            (species.getName(), float(species.getInitialAmount()))
            for species in model.getListOfSpecies()
        ),
        "parameters": {
            parameter.getName(): float(parameter.getValue())
            for parameter in model.getListOfParameters()
        },
        "reactions": sorted(
            (
                reaction.getId(),
                tuple(
                    sorted(
                        reference.getSpecies()
                        for reference in reaction.getListOfReactants()
                    )
                ),
                tuple(
                    sorted(
                        reference.getSpecies()
                        for reference in reaction.getListOfProducts()
                    )
                ),
            )
            for reaction in model.getListOfReactions()
        ),
    }
    try:
        import roadrunner
    except ImportError as exc:
        return dict(
            status="unavailable",
            structure=structure,
            detail=f"libRoadRunner is unavailable: {exc}",
        )
    try:
        runner = roadrunner.RoadRunner(str(exported.resolve()))
        runner.integrator.relative_tolerance = SOLVER_RTOL
        runner.integrator.absolute_tolerance = SOLVER_ATOL
        available = set(runner.model.getGlobalParameterIds())
        names = [name for name in ("A", "B") if name in available]
        if len(names) != 2:
            return dict(
                status="invalid",
                structure=structure,
                detail=(
                    "the exported SBML does not expose the source model's "
                    f"observables; available global parameters: {sorted(available)}"
                ),
            )
        result = runner.simulate(times=TIMES, selections=["time", *names])
    except Exception as exc:
        return dict(
            status="invalid",
            structure=structure,
            detail=f"libRoadRunner could not run the exported SBML: {exc}",
        )
    values = {name: result[:, index + 1] for index, name in enumerate(names)}
    return dict(status="ok", structure=structure, values=values)


# --------------------------------------------------------------------------- #
# The tier itself
# --------------------------------------------------------------------------- #


def _roundtrip_bngl(case, directory, model, source_values, law):
    """Round trip the BNGL export and consume it with the engine."""
    exported = directory / f"{case['id']}.export.bngl"
    _write_format(model, "bngl", exported)
    roundtrip = f"export-format-tier:{case['id']}:bngl:roundtrip-semantics"
    consumption = f"export-format-tier:{case['id']}:bngl:downstream-consumption"
    try:
        restored = bionetgen.load(str(exported))
    except Exception as exc:
        return [
            _failed(
                roundtrip,
                f"the exported BNGL could not be re-parsed: {exc}",
                {"field": "reimport", "exception": type(exc).__name__},
                exported,
            ),
            _row(
                consumption,
                "NOT_TESTED",
                "the exported BNGL could not be re-parsed",
                first_difference={"field": "reimport"},
                artifact=exported,
            ),
        ]
    entity_ok, entity_difference = _compare_entities(
        _model_entities(restored), _model_entities(model)
    )
    try:
        values = _observables(restored)
    except Exception as exc:
        return [
            _failed(
                roundtrip,
                f"the re-imported BNGL could not be executed: {exc}",
                {"field": "execution", "exception": type(exc).__name__},
                exported,
            ),
            _row(
                consumption,
                "NOT_TESTED",
                "the re-imported BNGL could not be executed",
                first_difference={"field": "execution"},
                artifact=exported,
            ),
        ]
    value_ok, value_difference = _compare_values(
        values, source_values, rtol=VALUE_RTOL, atol=VALUE_ATOL
    )
    rows = []
    if entity_ok and value_ok:
        rows.append(
            _row(
                roundtrip,
                "PASS",
                "the exported BNGL re-parses to the source model's entities and "
                "reproduces the source model's observable values",
                artifact=exported,
            )
        )
    else:
        detail = (
            "the exported BNGL does not re-parse to the source model's entities"
            if not entity_ok
            else "the re-imported BNGL does not reproduce the source model's "
            "observable values"
        )
        rows.append(
            _failed(
                roundtrip,
                detail,
                entity_difference if not entity_ok else value_difference,
                exported,
            )
        )
    law_ok, law_difference = _compare_values(values, law, rtol=LAW_RTOL, atol=LAW_ATOL)
    if law_ok:
        rows.append(
            _row(
                consumption,
                "PASS",
                "the downstream consumer "
                f"({CONSUMERS['bngl']}) reproduces the closed-form law for "
                f"{case['description']}",
                artifact=exported,
            )
        )
    else:
        rows.append(
            _failed(
                consumption,
                "the downstream consumer "
                f"({CONSUMERS['bngl']}) disagrees with the closed-form law",
                law_difference,
                exported,
            )
        )
    return rows


def _route_error(case, fmt, exc):
    """Report an unexpected route failure without losing a named check."""
    detail = f"the {fmt} route could not be evaluated: {type(exc).__name__}: {exc}"
    formats = ROUNDTRIP_FORMATS if fmt == "source" else (fmt,)
    rows = []
    for name in formats:
        for suffix in ("roundtrip-semantics", "downstream-consumption"):
            rows.append(
                _failed(
                    f"export-format-tier:{case['id']}:{name}:{suffix}",
                    detail,
                    {"field": "route", "exception": type(exc).__name__},
                )
            )
    return rows


def _roundtrip_net(case, directory, model, source_values, law, bng_cpp):
    """Round trip the NET export and consume it with the native CLI."""
    exported = directory / f"{case['id']}.export.net"
    roundtrip = f"export-format-tier:{case['id']}:net:roundtrip-semantics"
    consumption = f"export-format-tier:{case['id']}:net:downstream-consumption"
    if bng_cpp is None:
        return [
            _row(
                roundtrip,
                "NOT_TESTED",
                "the native CLI is unavailable, so the exported .net could not "
                "be read back",
            ),
            _row(
                consumption,
                "NOT_TESTED",
                "the native CLI is unavailable, so the exported .net could not "
                "be consumed",
            ),
        ]
    _write_format(model, "net", exported)
    values, network, error = _net_route(case, directory, bng_cpp)
    if error is not None:
        return [
            _failed(roundtrip, error, {"field": "net-roundtrip"}, exported),
            _failed(
                consumption,
                f"the downstream consumer ({CONSUMERS['net']}) could not use "
                f"the exported .net: {error}",
                {"field": "net-consumption"},
                exported,
            ),
        ]
    source_network = model.generate_network()
    expected_species = list(source_network.species_names)
    observed_species = [
        network.species_by_index[index] for index in sorted(network.species_by_index)
    ]
    difference = None
    if observed_species != expected_species:
        difference = {
            "field": "species",
            "expected": expected_species,
            "observed": observed_species,
        }
    elif network.n_reactions != source_network.num_reactions:
        difference = {
            "field": "reaction-count",
            "expected": source_network.num_reactions,
            "observed": network.n_reactions,
        }
    value_ok, value_difference = _compare_values(
        values, source_values, rtol=VALUE_RTOL, atol=VALUE_ATOL
    )
    rows = []
    if difference is None and value_ok:
        rows.append(
            _row(
                roundtrip,
                "PASS",
                "the exported .net reloads to the source model's network and "
                "reproduces the source model's observable values",
                artifact=exported,
            )
        )
    else:
        detail = (
            "the reloaded .net does not resolve to the source model's network"
            if difference is not None
            else "the reloaded .net does not reproduce the source model's "
            "observable values"
        )
        rows.append(
            _failed(
                roundtrip,
                detail,
                difference if difference is not None else value_difference,
                exported,
            )
        )
    law_ok, law_difference = _compare_values(values, law, rtol=LAW_RTOL, atol=LAW_ATOL)
    if law_ok:
        rows.append(
            _row(
                consumption,
                "PASS",
                "the downstream consumer "
                f"({CONSUMERS['net']}) reproduces the closed-form law for "
                f"{case['description']}",
                artifact=exported,
            )
        )
    else:
        rows.append(
            _failed(
                consumption,
                "the downstream consumer "
                f"({CONSUMERS['net']}) disagrees with the closed-form law",
                law_difference,
                exported,
            )
        )
    return rows


def _roundtrip_sbml(case, directory, model, source_values, law):
    """Round trip the SBML export and consume it with libRoadRunner."""
    exported = directory / f"{case['id']}.export.sbml.xml"
    _write_format(model, "sbml", exported)
    roundtrip = f"export-format-tier:{case['id']}:sbml:roundtrip-semantics"
    consumption = f"export-format-tier:{case['id']}:sbml:downstream-consumption"
    route = _sbml_route(exported)
    if route["status"] == "unavailable":
        return [
            _unsupported(
                roundtrip,
                f"the exported SBML could not be re-imported: {route['detail']}",
                exported,
            ),
            _unsupported(
                consumption,
                f"the exported SBML could not be consumed: {route['detail']}",
                exported,
            ),
        ]
    structure = route.get("structure")
    if route["status"] != "ok" and structure is None:
        return [
            _failed(
                roundtrip,
                f"the exported SBML was rejected: {route['detail']}",
                {"field": "sbml-reimport"},
                exported,
            ),
            _failed(
                consumption,
                "the downstream consumer "
                f"({CONSUMERS['sbml']}) could not use the exported SBML: "
                f"{route['detail']}",
                {"field": "sbml-consumption"},
                exported,
            ),
        ]
    source_network = model.generate_network()
    expected_species = sorted(
        (name, float(case["seeds"].get(name, 0.0)))
        for name in source_network.species_names
    )
    difference = None
    if structure["species"] != expected_species:
        difference = {
            "field": "species",
            "expected": expected_species,
            "observed": structure["species"],
        }
    elif len(structure["reactions"]) != source_network.num_reactions:
        difference = {
            "field": "reaction-count",
            "expected": source_network.num_reactions,
            "observed": len(structure["reactions"]),
        }
    else:
        parameters = {p.name: float(p.value) for p in model.parameters}
        diverged = {
            name: value
            for name, value in parameters.items()
            if name not in structure["parameters"]
            or abs(structure["parameters"][name] - value) > 1e-12
        }
        if diverged:
            difference = {
                "field": "parameters",
                "expected": parameters,
                "observed": structure["parameters"],
            }
    values = route.get("values")
    value_ok, value_difference = (True, None)
    if values is not None:
        value_ok, value_difference = _compare_values(
            values, source_values, rtol=VALUE_RTOL, atol=VALUE_ATOL
        )
    rows = []
    if difference is None and value_ok and route["status"] == "ok":
        rows.append(
            _row(
                roundtrip,
                "PASS",
                "the exported SBML re-imports to the source model's network and "
                "reproduces the source model's observable values",
                artifact=exported,
            )
        )
    else:
        detail = (
            "the re-imported SBML does not resolve to the source model's network"
            if difference is not None
            else (
                "the re-imported SBML does not reproduce the source model's "
                "observable values"
                if not value_ok
                else f"the exported SBML was rejected: {route['detail']}"
            )
        )
        rows.append(
            _failed(
                roundtrip,
                detail,
                (
                    difference
                    if difference is not None
                    else (value_difference or {"field": "sbml-reimport"})
                ),
                exported,
            )
        )
    if values is None:
        rows.append(
            _failed(
                consumption,
                "the downstream consumer "
                f"({CONSUMERS['sbml']}) could not use the exported SBML: "
                f"{route['detail']}",
                {"field": "sbml-consumption"},
                exported,
            )
        )
        return rows
    law_ok, law_difference = _compare_values(values, law, rtol=LAW_RTOL, atol=LAW_ATOL)
    if law_ok:
        rows.append(
            _row(
                consumption,
                "PASS",
                "the downstream consumer "
                f"({CONSUMERS['sbml']}) reproduces the closed-form law for "
                f"{case['description']}",
                artifact=exported,
            )
        )
    else:
        rows.append(
            _failed(
                consumption,
                "the downstream consumer "
                f"({CONSUMERS['sbml']}) disagrees with the closed-form law",
                law_difference,
                exported,
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# Refusal and representability controls
# --------------------------------------------------------------------------- #


def _refusal_check(fmt, directory):
    """Require an explicit refusal naming the unsupported feature."""
    check = f"export-format-tier:refusal:{fmt}:explicit-refusal"
    source = directory / "energy.source.bngl"
    source.write_text(ENERGY_MODEL, encoding="utf-8")
    model = bionetgen.load(str(source))
    target = directory / f"energy.export.{fmt}"
    try:
        _write_format(model, fmt, target)
    except Exception as exc:
        message = str(exc)
        if ENERGY_FEATURE not in message:
            return _boundary_row(
                check,
                "FAIL",
                f"the {fmt} export refused the model without naming the "
                f"unsupported feature {ENERGY_FEATURE!r}: {message}",
                first_difference={"field": "refusal-message", "message": message},
            )
        if target.exists():
            return _boundary_row(
                check,
                "FAIL",
                f"the {fmt} export refused the model but still left an "
                f"artifact behind: {target}",
                first_difference={"field": "artifact", "path": str(target)},
            )
        return _boundary_row(
            check,
            "PASS",
            f"the {fmt} export explicitly refused the model and named the "
            f"unsupported feature: {message}",
        )
    return _boundary_row(
        check,
        "FAIL",
        f"the {fmt} export silently dropped {ENERGY_FEATURE!r} instead of "
        "refusing the model",
        first_difference={"field": "silent-loss", "artifact": str(target)},
    )


def _energy_control_check(fmt, directory):
    """Require a format that can express the feature not to refuse it."""
    from . import compare

    check = f"export-format-tier:energy-control:{fmt}:feature-preserved"
    source = directory / "energy.source.bngl"
    if not source.is_file():
        source.write_text(ENERGY_MODEL, encoding="utf-8")
    model = bionetgen.load(str(source))
    target = directory / f"energy.export.{fmt}"
    try:
        _write_format(model, fmt, target)
    except Exception as exc:
        return _failed(
            check,
            f"the {fmt} export refused a model whose {ENERGY_FEATURE!r} it "
            f"can represent: {exc}",
            {"field": "unexpected-refusal", "message": str(exc)},
        )
    text = target.read_text(encoding="utf-8", errors="replace")
    if fmt == "bngl":
        preserved = "begin energy patterns" in text
    elif fmt == "bng-xml":
        preserved = "<ListOfEnergyPatterns>" in text
    elif fmt == "net":
        # The .net resolves the energy-derived rate law into a numeric rate
        # parameter; a literal Arrhenius(...) call would not be executable.
        network = compare.parse_net(target)
        rates = []
        if network is not None:
            for key in network.reaction_multiset:
                try:
                    rates.append(float(key[2]))
                except (TypeError, ValueError):
                    rates.append(None)
        preserved = (
            "Arrhenius" not in text
            and network is not None
            and network.n_reactions >= 1
            and bool(rates)
            and all(rate is not None and math.isfinite(rate) for rate in rates)
        )
    else:  # pragma: no cover - protected by the static table
        raise ValueError(f"unknown energy-capable format: {fmt!r}")
    if not preserved:
        return _failed(
            check,
            f"the {fmt} export did not carry {ENERGY_FEATURE!r} into the "
            "exported artifact",
            {"field": "feature-preserved"},
        )
    return _row(
        check,
        "PASS",
        f"the {fmt} export carries {ENERGY_FEATURE!r} into the exported "
        "artifact instead of refusing the model",
        artifact=target,
    )


# --------------------------------------------------------------------------- #
# Worker entry points
# --------------------------------------------------------------------------- #


def run_worker(directory, *, bng_cpp=None):
    """Run the export-format tier and return its evidence rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if bng_cpp is not None:
        bng_cpp = Path(bng_cpp).expanduser().resolve()
        if not bng_cpp.is_file():
            return [
                _row(
                    check,
                    "NOT_TESTED",
                    f"the native CLI is unavailable at {bng_cpp}",
                )
                for check in check_ids()
            ]
    if bionetgen is None:
        return [
            _row(
                check,
                "NOT_TESTED",
                "the bionetgen package is unavailable",
            )
            for check in check_ids()
        ]

    rows = []
    for case in cases():
        work = directory / case["id"]
        work.mkdir(parents=True, exist_ok=True)
        source = work / "source.bngl"
        source.write_text(case_bngl(case), encoding="utf-8")
        try:
            model = bionetgen.load(str(source))
            law = case_law(case)
            source_values = _observables(model)
        except Exception as exc:
            rows.extend(_route_error(case, "source", exc))
            continue

        routes = (
            ("bngl", lambda: _roundtrip_bngl(case, work, model, source_values, law)),
            (
                "net",
                lambda: _roundtrip_net(case, work, model, source_values, law, bng_cpp),
            ),
            ("sbml", lambda: _roundtrip_sbml(case, work, model, source_values, law)),
        )
        for fmt, route in routes:
            try:
                rows.extend(route())
            except Exception as exc:
                rows.extend(_route_error(case, fmt, exc))

    energy = directory / "energy"
    energy.mkdir(parents=True, exist_ok=True)
    for fmt in REFUSAL_FORMATS:
        try:
            rows.append(_refusal_check(fmt, energy))
        except Exception as exc:
            rows.append(
                _boundary_row(
                    f"export-format-tier:refusal:{fmt}:explicit-refusal",
                    "FAIL",
                    f"the {fmt} refusal check could not be evaluated: "
                    f"{type(exc).__name__}: {exc}",
                    first_difference={
                        "field": "refusal",
                        "exception": type(exc).__name__,
                    },
                )
            )
    for fmt in ENERGY_CAPABLE_FORMATS:
        try:
            rows.append(_energy_control_check(fmt, energy))
        except Exception as exc:
            rows.append(
                _failed(
                    f"export-format-tier:energy-control:{fmt}:feature-preserved",
                    f"the {fmt} representability control could not be evaluated: "
                    f"{type(exc).__name__}: {exc}",
                    {"field": "energy-control", "exception": type(exc).__name__},
                )
            )

    summary = {
        "tier": sorted(set(ROUNDTRIP_FORMATS) | set(REFUSAL_FORMATS)),
        "roundtrip_formats": list(ROUNDTRIP_FORMATS),
        "refusal_formats": list(REFUSAL_FORMATS),
        "energy_capable_formats": list(ENERGY_CAPABLE_FORMATS),
        "consumers": dict(CONSUMERS),
        "cases": [case["id"] for case in cases()],
        "unsupported_feature": ENERGY_FEATURE,
    }
    (directory / "tier.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="worker produced an unknown status",
                supported_execution=False,
            )
    return rows


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--bng-cpp", type=Path)
    args = parser.parse_args(argv)
    rows = run_worker(args.report_dir, bng_cpp=args.bng_cpp)
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, indent=2))
    return 1 if any(row["status"] in {"FAIL", "HARNESS_ERROR"} for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI contract
    raise SystemExit(main())
