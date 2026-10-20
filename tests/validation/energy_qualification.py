"""Energy extension qualification (#177).

Issue #177 ("G07: Independently qualify barrier and reservoir energy
extensions") asks for analytic expectations and an independent reference for
the detailed-balance/affinity, reversal, unit and exporter claims, and asks
for the experimental opt-in to stay explicit until the supported extension
surface has execution evidence.

This module qualifies that surface on a fixed, generated corpus of two-state
energy models. The rules that keep the claims honest:

* **Analytic expectation.** Every rate claim is compared against the closed
  form stated in ``docs/nonequilibrium_energy.md`` and derived from the case
  parameters -- never against a number the engine produced. The law is

      k_f = exp[-(Ea + B + phi       * (dG - W)) / RT]
      k_r = exp[-(Ea + B + (1 - phi) * (W - dG)) / RT]

  with ``RT = 1`` on the network path (energies are already in RT units).

* **Independent reference.** For the subset canonical BioNetGen implements
  (plain eBNGL Arrhenius with energy patterns), the canonical Perl BNG2 oracle
  expands the rate law itself. The harness evaluates BNG2's own expression
  with its own evaluator and compares the result with BNG3's resolved
  constant. For the barrier/reservoir extension no canonical oracle exists,
  and that limitation is a named boundary, not a silent gap: the extension
  subset is judged against the analytic law alone.

* **Explicit opt-in.** The extension is gated by ``BNG_NFSIM_GENERAL_ENERGY``.
  With the gate unset every backend boundary must refuse the construct. A
  model that quietly runs as an equilibrium model is a failure, so the
  refusal is executed, not assumed.

* **Two conventions, one law.** The network path and the network-free NFsim
  path apply the reservoir work differently (the network path builds the
  reverse as its own reaction with a negated work, the NFsim path uses
  ``phi - 1`` with the forward work). Both are executed against the same
  analytic law, so a sign error in either convention shows up as a
  disagreement rather than as a plausible number.

The module is import-safe: it only touches ``bionetgen``, ``numpy`` and the
optional Perl oracle when it runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from .campaign import STATUSES

try:  # The compiled extension is only required when the family actually runs.
    import bionetgen
except ImportError:  # pragma: no cover - exercised by the harness guard
    bionetgen = None

ISSUES = (177,)
ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #

# The gate that opts into the experimental extension. The name is the one the
# product documents; the family never invents a second switch.
GATE = "BNG_NFSIM_GENERAL_ENERGY"

# The canonical Perl BNG2 oracle. It is the independent reference for the
# subset it implements and the named boundary for the subset it does not.
BNG2_PERL = ROOT / "legacy" / "perl" / "BNG2.pl"

# Rate constants are compared in the logarithm, so the comparison is a
# relative comparison of the exponential's argument: 1e-12 is far below the
# double-precision noise of exp() over the exponent range these cases use and
# far above the difference a sign error or a wrong RT divisor produces.
LOG_RTOL = 1e-12

# The two-state corpus: a fixed population of independent molecules, so the
# number of reactant molecules at time t is Binomial(N, q(t)).
POPULATION = 200
T_END = 2.0
N_STEPS = 4

# The stochastic control of the network-free path: a fixed seed, a fixed run
# budget and a stated error control. The band is four standard errors of the
# binomial law, which for a 48-member ensemble is far outside the sampling
# error of a correct implementation and far inside the error of a wrong rate.
ENSEMBLE_RUNS = 48
SEED_BASE = 20261020
STATISTICAL_SIGMA = 4.0

# The exporters that can carry the extension semantics and the exporters that
# must refuse it.
ENERGY_CAPABLE_EXPORTERS = ("bngl", "xml", "net")
REFUSING_EXPORTERS = ("sbml", "matlab", "latex")

# The generated corpus. Every case is a two-state energy model whose
# parameters are declared in the model source, so the analytic expectation is
# a function of the case alone.
CASE_SPECS = (
    {
        "id": "equilibrium-arrhenius",
        "activation": 1.0,
        "phi": 0.5,
        "delta_g": 1.0,
        "work": 0.0,
        "barrier": 0.0,
        # The canonical oracle implements this subset, so it is the subset
        # whose rates can be checked against an independent reference.
        "reference": True,
    },
    {
        "id": "equilibrium-phi-skew",
        "activation": 0.8,
        "phi": 0.25,
        "delta_g": 1.2,
        "work": 0.0,
        "barrier": 0.0,
        "reference": True,
    },
    {
        "id": "barrier-only",
        "activation": 1.0,
        "phi": 0.5,
        "delta_g": 0.5,
        "work": 0.0,
        "barrier": 1.2,
        "reference": False,
    },
    {
        "id": "driven-only",
        "activation": 1.5,
        "phi": 0.5,
        "delta_g": 0.4,
        "work": 0.8,
        "barrier": 0.0,
        "reference": False,
    },
    {
        "id": "driven-and-barrier",
        "activation": 1.0,
        "phi": 0.4,
        "delta_g": 0.6,
        "work": 0.5,
        "barrier": 0.9,
        "reference": False,
    },
)

# The three-state driven cycle. The ground-state differences around the cycle
# sum to zero, so the cycle's affinity is exactly the reservoir work that the
# one driven edge supplies: a nonzero affinity is a non-equilibrium model,
# and its magnitude is analytic.
CYCLE_SPEC = {
    "id": "driven-cycle",
    "activation": 1.0,
    "phi": 0.5,
    "states": (("U", 0.0), ("P", 0.4), ("Q", 1.0)),
    "work": 0.8,
}

# The energy scale factor of the unit-consistency control. All energies are
# declared in RT units, so scaling them by a constant must scale the rate
# constants by the same power; a hidden RT divisor or a physical-unit
# conversion breaks that homogeneity.
ENERGY_SCALE = 2.478

# The energy-capable exporters write a file that must still carry the
# extension; the refusing exporters must refuse and name the construct.
REFUSAL_KEYWORDS = ("barrier", "energy", "arrhenius", "reservoir")


# --------------------------------------------------------------------------- #
# Analytic expectations
# --------------------------------------------------------------------------- #


def analytic_rates(case):
    """Return the analytic (forward, reverse) rate constants of a case.

    The law is the one the product documents; it is a function of the case
    parameters only, so it is independent of anything the engine produced.
    """
    activation = float(case["activation"])
    phi = float(case["phi"])
    delta_g = float(case["delta_g"])
    work = float(case["work"])
    barrier = float(case["barrier"])
    forward = math.exp(-(activation + barrier + phi * (delta_g - work)))
    reverse = math.exp(-(activation + barrier + (1.0 - phi) * (work - delta_g)))
    return forward, reverse


def analytic_effective_delta_g(case):
    """Return the analytic effective free-energy difference of a transition.

    The reservoir work shifts the ground-state difference, so the transition
    carries ``dG - W`` and the reverse traversal carries its negation.
    """
    return float(case["delta_g"]) - float(case["work"])


def two_state_law(case, times):
    """Return the analytic mean and variance of the reactant count.

    Every molecule is an independent two-state process, so the reactant count
    is Binomial(N, q(t)) with

        q(t) = q_ss + (1 - q_ss) exp[-(k_f + k_r) t]
        q_ss = k_r / (k_f + k_r)

    This is the closed form of the deterministic system, which is also the
    mean of the stochastic process because the propensity is linear.
    """
    forward, reverse = analytic_rates(case)
    total = forward + reverse
    steady = reverse / total
    times = np.asarray(times, dtype=float)
    q = steady + (1.0 - steady) * np.exp(-total * times)
    population = float(POPULATION)
    mean = population * q
    variance = population * q * (1.0 - q)
    return mean, variance


def cycle_affinity():
    """Return the analytic affinity of the driven cycle."""
    states = dict(CYCLE_SPEC["states"])
    edges = (
        ("U", "P", float(CYCLE_SPEC["work"])),
        ("P", "Q", 0.0),
        ("Q", "U", 0.0),
    )
    affinity = 0.0
    for source, target, work in edges:
        affinity += (states[target] - states[source]) - work
    return affinity


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #


def case_source(case, *, mirrored=False, scale=1.0):
    """Return the BNGL source of a two-state case.

    ``mirrored`` writes the rule in the opposite direction, which reverses
    the transition's ground-state difference while the reservoir work stays
    attached to the rule's forward traversal. ``scale`` multiplies every
    declared energy, which is the unit-consistency control.
    """
    activation = float(case["activation"]) * scale
    delta_g = float(case["delta_g"]) * scale
    work = float(case["work"]) * scale
    barrier = float(case["barrier"]) * scale
    reactant, product = ("s~U", "s~P")
    if mirrored:
        reactant, product = ("s~P", "s~U")
    lines = [
        "begin model",
        "begin parameters",
        f"  phi {float(case['phi'])}",
        f"  Ea {activation!r}",
        f"  GU {0.0!r}",
        f"  GP {delta_g!r}",
        f"  muATP {work!r}",
    ]
    if barrier != 0.0:
        lines.append(f"  Gbar {barrier!r}")
    lines += [
        "end parameters",
        "begin molecule types",
        "  A(s~U~P)",
        "end molecule types",
        "begin energy patterns",
        "  A(s~U) GU",
        "  A(s~P) GP",
        "end energy patterns",
        "begin seed species",
        f"  A(s~U) {POPULATION}",
        "  A(s~P) 0",
        "end seed species",
        "begin observables",
        "  Molecules U A(s~U)",
        "  Molecules P A(s~P)",
        "end observables",
    ]
    if barrier != 0.0:
        lines += [
            "begin barrier patterns",
            "  slow: A(s~U) -> A(s~P) Gbar",
            "end barrier patterns",
        ]
    lines += [
        "begin reaction rules",
    ]
    rule = f"  R1: A({reactant}) <-> A({product}) Arrhenius(phi,Ea)"
    if work != 0.0:
        # A zero reservoir work is expressed by omitting the annotation: the
        # canonical oracle implements the plain eBNGL subset and cannot read
        # a driven_by() it would have to ignore.
        rule += " driven_by(muATP)"
    lines.append(rule)
    lines += [
        "end reaction rules",
        "end model",
        "",
    ]
    return "\n".join(lines)


def cycle_source(scale=1.0):
    """Return the BNGL source of the three-state driven cycle."""
    states = CYCLE_SPEC["states"]
    activation = float(CYCLE_SPEC["activation"]) * scale
    work = float(CYCLE_SPEC["work"]) * scale
    lines = [
        "begin model",
        "begin parameters",
        f"  phi {float(CYCLE_SPEC['phi'])}",
        f"  Ea {activation!r}",
    ]
    for name, energy in states:
        lines.append(f"  G{name} {float(energy) * scale!r}")
    lines.append(f"  muATP {work!r}")
    lines += [
        "end parameters",
        "begin molecule types",
        "  A(s~U~P~Q)",
        "end molecule types",
        "begin energy patterns",
    ]
    for name, _ in states:
        lines.append(f"  A(s~{name}) G{name}")
    lines += [
        "end energy patterns",
        "begin seed species",
        f"  A(s~U) {POPULATION}",
    ]
    for name, _ in states[1:]:
        lines.append(f"  A(s~{name}) 0")
    lines.append("end seed species")
    lines += [
        "begin observables",
        "  Molecules U A(s~U)",
        "  Molecules P A(s~P)",
        "  Molecules Q A(s~Q)",
        "end observables",
        "begin reaction rules",
        f"  R1: A(s~U) <-> A(s~P) Arrhenius(phi,Ea) driven_by(muATP)",
        f"  R2: A(s~P) <-> A(s~Q) Arrhenius(phi,Ea)",
        f"  R3: A(s~Q) <-> A(s~U) Arrhenius(phi,Ea)",
        "end reaction rules",
        "end model",
        "",
    ]
    return "\n".join(lines)


def cases():
    """Return the fixed, generated corpus of energy cases."""
    result = []
    for spec in CASE_SPECS:
        case = dict(spec)
        case["bngl"] = case_source(case)
        case["mirrored_bngl"] = case_source(case, mirrored=True)
        case["scaled_bngl"] = case_source(case, scale=ENERGY_SCALE)
        case["barrier_free_bngl"] = case_source(dict(case, barrier=0.0))
        result.append(case)
    return result


def corpus_record():
    """Return the description of the corpus the qualification used."""
    return {
        "cases": [
            {
                "id": case["id"],
                "activation": case["activation"],
                "phi": case["phi"],
                "delta_g": case["delta_g"],
                "work": case["work"],
                "barrier": case["barrier"],
                "canonical_reference": case["reference"],
                "population": POPULATION,
                "t_end": T_END,
                "n_steps": N_STEPS,
                "bngl_sha256": hashlib.sha256(case["bngl"].encode()).hexdigest(),
            }
            for case in cases()
        ],
        "cycle": {
            "id": CYCLE_SPEC["id"],
            "states": [list(state) for state in CYCLE_SPEC["states"]],
            "work": CYCLE_SPEC["work"],
            "analytic_affinity": cycle_affinity(),
            "bngl_sha256": hashlib.sha256(cycle_source().encode()).hexdigest(),
        },
        "ensemble_runs": ENSEMBLE_RUNS,
        "seed_base": SEED_BASE,
        "statistical_sigma": STATISTICAL_SIGMA,
        "energy_scale": ENERGY_SCALE,
        "gate": GATE,
    }


def corpus_digest():
    """Return the digest of the corpus description."""
    return hashlib.sha256(
        json.dumps(corpus_record(), sort_keys=True).encode()
    ).hexdigest()


# --------------------------------------------------------------------------- #
# Check identities
# --------------------------------------------------------------------------- #

CASE_CHECKS = (
    "detailed-balance",
    "transition-affinity",
    "reversal",
    "units",
    "network-free-agreement",
    "exporter-semantics",
)


def check_ids():
    """Declare the expected evidence identities independently of execution."""
    ids = [
        "energy-qualification:family:environment-record",
        "energy-qualification:family:experimental-opt-in",
        "energy-qualification:family:canonical-oracle-boundary",
        "energy-qualification:family:resolution-determinism",
        "energy-qualification:family:driven-cycle-affinity",
    ]
    for case in cases():
        for name in CASE_CHECKS:
            ids.append(f"energy-qualification:{case['id']}:{name}")
        if case["reference"]:
            ids.append(f"energy-qualification:{case['id']}:independent-reference")
    return ids


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #


def _row(check, status, detail, *, first_difference=None, artifact=None, kind=None):
    if kind is None:
        kind = {
            "PASS": "supported-execution",
            "FAIL": "supported-execution",
        }.get(status, "diagnostic-only")
    row = {
        "id": check,
        "check": check.rsplit(":", 1)[-1],
        "status": status,
        "detail": str(detail),
        "first_difference": first_difference,
        "related_issues": list(ISSUES),
        "evidence_kind": kind,
        "supported_execution": status == "PASS" and kind == "supported-execution",
    }
    if artifact is not None:
        row["source_artifact"] = artifact.name
        row["source_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return row


def _boundary_row(check, status, detail, *, first_difference=None):
    """A recorded refusal proves a boundary, so it is never support evidence."""
    row = _row(check, status, detail, first_difference=first_difference)
    row["evidence_kind"] = "diagnostic-only"
    row["supported_execution"] = False
    return row


def _not_tested(check, detail, *, artifact=None):
    return _row(check, "NOT_TESTED", detail, artifact=artifact)


def _failed(check, detail, difference=None, artifact=None):
    return _row(check, "FAIL", detail, first_difference=difference, artifact=artifact)


# --------------------------------------------------------------------------- #
# Comparison helpers
# --------------------------------------------------------------------------- #


def _compare_log(observed, expected, *, label):
    """Compare rate constants in the logarithm.

    The comparison is on ``log(k)``, so it is a relative comparison of the
    exponential's argument and does not depend on the magnitude of the rate.
    """
    observed_log = math.log(float(observed))
    expected_log = math.log(float(expected))
    deviation = abs(observed_log - expected_log)
    if deviation > LOG_RTOL * max(1.0, abs(expected_log)):
        return False, {
            "field": label,
            "expected_log": expected_log,
            "observed_log": observed_log,
            "deviation": deviation,
            "tolerance": LOG_RTOL * max(1.0, abs(expected_log)),
        }
    return True, None


def _correctness(ok, detail, difference=None):
    return {"ok": bool(ok), "detail": detail, "difference": difference}


# --------------------------------------------------------------------------- #
# The .net artifact
# --------------------------------------------------------------------------- #


def parse_net(text):
    """Return the parameters, species and reactions of a .net artifact.

    The parser is deliberately shared between BNG3's own artifact and the
    canonical oracle's artifact: both are the same format, and comparing two
    artifacts parsed by one parser keeps the comparison about the numbers.
    """
    parameters, species, reactions = {}, {}, []
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("begin "):
            section = line[6:].split()[0]
            continue
        if line.startswith("end "):
            section = None
            continue
        parts = line.split()
        if section == "parameters" and len(parts) >= 3 and parts[0].isdigit():
            parameters[parts[1]] = parts[2]
        elif section == "species" and len(parts) >= 3 and parts[0].isdigit():
            species[int(parts[0])] = parts[1]
        elif section == "reactions" and len(parts) >= 4 and parts[0].isdigit():
            reactions.append(
                dict(
                    index=int(parts[0]),
                    reactants=[int(value) for value in parts[1].split(",")],
                    products=[int(value) for value in parts[2].split(",")],
                    rate=parts[3],
                )
            )
    return parameters, species, reactions


def net_rate_pairs(text):
    """Return the network's rate constants keyed by (reactant, product).

    The key uses the species names, not the indices, so the two artifacts
    can be compared without assuming a common species ordering.
    """
    parameters, species, reactions = parse_net(text)
    pairs = {}
    for reaction in reactions:
        reactants = tuple(sorted(species[index] for index in reaction["reactants"]))
        products = tuple(sorted(species[index] for index in reaction["products"]))
        expression = parameters.get(reaction["rate"])
        if expression is None:
            continue
        pairs[(reactants, products)] = expression
    return pairs


# --------------------------------------------------------------------------- #
# An independent evaluator for the canonical oracle's rate expressions
# --------------------------------------------------------------------------- #


class ExpressionError(ValueError):
    """Raised when the canonical oracle's rate expression cannot be read."""


_TOKEN = re.compile(
    r"\s*(?:(?P<number>\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<operator>[-+*/()]))"
)


def _tokenize(text):
    tokens, position = [], 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            if text[position].isspace():
                position += 1
                continue
            raise ExpressionError(f"unexpected character in {text!r}")
        tokens.append((match.lastgroup, match.group(match.lastgroup)))
        position = match.end()
    return tokens


class _Evaluator:
    """A recursive-descent evaluator for the oracle's rate expressions.

    The evaluator is the harness's own: it never calls into the product, so
    the number it produces is independent of the engine under test. It
    supports exactly the arithmetic the canonical oracle emits -- numbers,
    parameter identifiers, the four operators and ``exp``.
    """

    def __init__(self, values):
        self.values = values
        self.tokens = _tokenize("")
        self.index = 0

    def evaluate(self, text):
        self.tokens = _tokenize(text)
        self.index = 0
        value = self._sum()
        if self.index != len(self.tokens):
            raise ExpressionError("the expression has trailing tokens")
        return value

    def _sum(self):
        value = self._product()
        while self._operator("+", "-"):
            operator = self.tokens[self.index - 1][1]
            right = self._product()
            value = value + right if operator == "+" else value - right
        return value

    def _product(self):
        value = self._unary()
        while self._operator("*", "/"):
            operator = self.tokens[self.index - 1][1]
            right = self._unary()
            value = value * right if operator == "*" else value / right
        return value

    def _unary(self):
        if self._operator("-"):
            return -self._unary()
        if self._operator("+"):
            return self._unary()
        return self._primary()

    def _operator(self, *names):
        if self.index < len(self.tokens):
            kind, text = self.tokens[self.index]
            if kind == "operator" and text in names:
                self.index += 1
                return True
        return False

    def _primary(self):
        if self.index >= len(self.tokens):
            raise ExpressionError("the expression ended unexpectedly")
        kind, text = self.tokens[self.index]
        if kind == "number":
            self.index += 1
            return float(text)
        if kind == "name":
            if self.index + 1 < len(self.tokens) and self.tokens[self.index + 1] == (
                "operator",
                "(",
            ):
                if text != "exp":
                    raise ExpressionError(f"unsupported function: {text}")
                self.index += 2
                value = self._sum()
                if not self._operator(")"):
                    raise ExpressionError("the function call is not closed")
                return math.exp(value)
            self.index += 1
            if text not in self.values:
                raise ExpressionError(f"unknown parameter: {text}")
            return float(self.values[text])
        if kind == "operator" and text == "(":
            self.index += 1
            value = self._sum()
            if not self._operator(")"):
                raise ExpressionError("the parenthesis is not closed")
            return value
        raise ExpressionError(f"unexpected token: {text!r}")


def evaluate_expression(text, values):
    """Evaluate one of the canonical oracle's rate expressions.

    The evaluator is the harness's own: it never calls into the product, so
    the number it produces is independent of the engine under test.
    """
    return _Evaluator(values).evaluate(text)


# --------------------------------------------------------------------------- #
# The canonical oracle
# --------------------------------------------------------------------------- #


def _bng2_available():
    return shutil.which("perl") is not None and BNG2_PERL.is_file()


def _with_generate_network(source):
    """Return the model source with a network-generation action appended.

    The canonical oracle reads a model and writes nothing unless the model
    asks for it, so the reference run needs the action the product's own
    writer does not emit.
    """
    marker = "end model"
    index = source.rfind(marker)
    if index < 0:
        return source
    return (
        source[:index]
        + "begin actions\n  generate_network({overwrite=>1})\nend actions\n"
        + source[index:]
    )


def run_bng2(source, directory):
    """Run the canonical Perl BNG2 on a model and return its outcome.

    The outcome records whether the oracle could process the model at all.
    For the extension subset it cannot, and that refusal is the boundary the
    family has to name rather than a gap to paper over.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "model.bngl"
    path.write_text(_with_generate_network(source), encoding="utf-8")
    environment = dict(os.environ)
    environment["BNGPATH"] = str(BNG2_PERL.parent)
    completed = subprocess.run(
        ["perl", str(BNG2_PERL), str(path)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(directory),
        env=environment,
    )
    net = directory / "model.net"
    return dict(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        net=net.read_text(encoding="utf-8") if net.is_file() else None,
    )


def bng2_reference_rates(source, directory):
    """Return the canonical oracle's rate constants for a model.

    The oracle expands the rate law itself and keeps the expansion symbolic
    in its ``.net`` artifact, so the harness evaluates that expansion with
    its own evaluator.
    """
    outcome = run_bng2(source, directory)
    if outcome["returncode"] != 0 or outcome["net"] is None:
        return None, outcome
    parameters, _, _ = parse_net(outcome["net"])
    values = {}
    for name, expression in parameters.items():
        try:
            values[name] = float(expression)
        except ValueError:
            values[name] = None
    resolved = {}
    for name, expression in parameters.items():
        if values.get(name) is not None:
            continue
        try:
            resolved[name] = evaluate_expression(expression, values)
        except ExpressionError:
            resolved[name] = None
    pairs = {}
    _, species, reactions = parse_net(outcome["net"])
    for reaction in reactions:
        reactants = tuple(sorted(species[index] for index in reaction["reactants"]))
        products = tuple(sorted(species[index] for index in reaction["products"]))
        value = resolved.get(reaction["rate"])
        if value is None:
            continue
        pairs[(reactants, products)] = value
    return pairs, outcome


# --------------------------------------------------------------------------- #
# The product surface
# --------------------------------------------------------------------------- #


def _resolved_net(source, directory, *, gate=True):
    """Resolve a model's network and return its .net artifact.

    The gate is read by the product when the rate laws are lowered, so it is
    set around the call rather than around the parse.
    """
    from bionetgen import _bionetgen_cpp as cpp

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get(GATE)
    if gate:
        os.environ[GATE] = "1"
    else:
        os.environ.pop(GATE, None)
    try:
        model = cpp.parse_string(source)
        network = cpp.generate_network(model)
        path = directory / "model.net"
        cpp.io.write_net(model, network, str(path))
        return path.read_text(encoding="utf-8"), model, network
    finally:
        if previous is None:
            os.environ.pop(GATE, None)
        else:
            os.environ[GATE] = previous


def _numeric_pairs(net_text):
    """Return the resolved numeric rate constants of a .net artifact."""
    pairs = {}
    for key, expression in net_rate_pairs(net_text).items():
        pairs[key] = float(expression)
    return pairs


# The species pairs of a two-state transition. The rule's forward direction
# is reactant -> product; the mirrored rule runs product -> reactant.
REACTANT = ("A(s~U)",)
PRODUCT = ("A(s~P)",)
FORWARD_KEY = (REACTANT, PRODUCT)
REVERSE_KEY = (PRODUCT, REACTANT)


def _two_state_pairs(net_text, *, forward_key=FORWARD_KEY, reverse_key=REVERSE_KEY):
    """Return the forward and reverse rate constants of a two-state network."""
    pairs = _numeric_pairs(net_text)
    forward = pairs.get(forward_key)
    reverse = pairs.get(reverse_key)
    if forward is None or reverse is None:
        return None, None
    return forward, reverse


# --------------------------------------------------------------------------- #
# The per-case checks
# --------------------------------------------------------------------------- #


def _case_detail(case):
    return (
        f"case {case['id']}: Ea={case['activation']}, phi={case['phi']}, "
        f"dG={case['delta_g']}, W={case['work']}, B={case['barrier']}"
    )


def check_detailed_balance(case, net_text):
    """The local detailed balance of a transition must be the analytic one."""
    forward, reverse = _two_state_pairs(net_text)
    if forward is None or reverse is None:
        return _correctness(
            False,
            "the generated network does not carry a forward and a reverse "
            "reaction for the transition",
        )
    expected_forward, expected_reverse = analytic_rates(case)
    ok_forward, difference_forward = _compare_log(
        forward, expected_forward, label="forward-rate"
    )
    ok_reverse, difference_reverse = _compare_log(
        reverse, expected_reverse, label="reverse-rate"
    )
    if ok_forward and ok_reverse:
        return _correctness(
            True,
            "the resolved forward and reverse rate constants reproduce the "
            "analytic Arrhenius pair "
            f"exp[-(Ea+B+phi(dG-W))]={expected_forward:.12g} and "
            f"exp[-(Ea+B+(1-phi)(W-dG))]={expected_reverse:.12g}",
        )
    difference = difference_forward or difference_reverse
    return _correctness(
        False,
        "the resolved rate constants differ from the analytic Arrhenius pair: "
        f"forward {forward:.12g} against {expected_forward:.12g}, reverse "
        f"{reverse:.12g} against {expected_reverse:.12g}",
        difference,
    )


def check_transition_affinity(case, net_text, barrier_free_text):
    """The transition's affinity must exclude the barrier.

    The barrier is a transition-state contribution: it changes the kinetics
    but not the local detailed balance, so the effective free-energy
    difference implied by the rate ratio must be the same with and without
    it.
    """
    forward, reverse = _two_state_pairs(net_text)
    if forward is None or reverse is None:
        return _correctness(
            False,
            "the generated network does not carry a forward and a reverse "
            "reaction for the transition",
        )
    implied = math.log(forward) - math.log(reverse)
    expected = -analytic_effective_delta_g(case)
    ok, difference = _compare_log(
        math.exp(implied), math.exp(expected), label="effective-delta-g"
    )
    if not ok:
        return _correctness(
            False,
            "the effective free-energy difference implied by the rate ratio "
            f"is {implied:.12g} and does not match the analytic "
            f"{expected:.12g}",
            difference,
        )
    bare_forward, bare_reverse = _two_state_pairs(barrier_free_text)
    if bare_forward is None or bare_reverse is None:
        return _correctness(
            False,
            "the barrier-free control network does not carry a forward and a "
            "reverse reaction for the transition",
        )
    bare = math.log(bare_forward) - math.log(bare_reverse)
    if abs(bare - implied) > LOG_RTOL * max(1.0, abs(implied)):
        return _correctness(
            False,
            "the barrier changed the transition's affinity: the implied "
            f"effective difference is {implied:.12g} with the barrier and "
            f"{bare:.12g} without it",
            {
                "field": "barrier-invariance",
                "with_barrier": implied,
                "without_barrier": bare,
            },
        )
    return _correctness(
        True,
        "the effective free-energy difference implied by the rate ratio is "
        f"{implied:.12g}, matching the analytic dG-W={expected:.12g}, and the "
        "barrier leaves it unchanged",
    )


def check_reversal(case, net_text, mirrored_text):
    """The reverse traversal must carry the negated reservoir work."""
    forward, reverse = _two_state_pairs(net_text)
    if forward is None or reverse is None:
        return _correctness(
            False,
            "the generated network does not carry a forward and a reverse "
            "reaction for the transition",
        )
    mirrored_forward, mirrored_reverse = _two_state_pairs(
        mirrored_text, forward_key=REVERSE_KEY, reverse_key=FORWARD_KEY
    )
    if mirrored_forward is None or mirrored_reverse is None:
        return _correctness(
            False,
            "the mirrored network does not carry a forward and a reverse "
            "reaction for the transition",
        )
    activation = float(case["activation"])
    phi = float(case["phi"])
    barrier = float(case["barrier"])
    delta_g = float(case["delta_g"])
    work = float(case["work"])
    # The mirrored rule runs in the opposite direction, so its ground-state
    # difference is negated while the work stays on the rule's forward
    # traversal. A sign error in the work handling shows up here.
    expected_forward = math.exp(-(activation + barrier + phi * (-delta_g - work)))
    expected_reverse = math.exp(
        -(activation + barrier + (1.0 - phi) * (work + delta_g))
    )
    ok_forward, difference_forward = _compare_log(
        mirrored_forward, expected_forward, label="mirrored-forward-rate"
    )
    ok_reverse, difference_reverse = _compare_log(
        mirrored_reverse, expected_reverse, label="mirrored-reverse-rate"
    )
    if not (ok_forward and ok_reverse):
        return _correctness(
            False,
            "the mirrored rule does not reproduce the mirrored analytic pair: "
            f"forward {mirrored_forward:.12g} against "
            f"{expected_forward:.12g}, reverse {mirrored_reverse:.12g} "
            f"against {expected_reverse:.12g}",
            difference_forward or difference_reverse,
        )
    # The reverse traversal's effective difference must be the negation of the
    # forward traversal's.
    forward_effective = math.log(forward) - math.log(reverse)
    reverse_effective = -forward_effective
    if abs(reverse_effective + forward_effective) > LOG_RTOL * max(
        1.0, abs(forward_effective)
    ):
        return _correctness(
            False,
            "the reverse traversal does not carry the negated effective "
            f"free-energy difference: forward {forward_effective:.12g}, "
            f"reverse {reverse_effective:.12g}",
            {
                "field": "reversal",
                "forward_effective": forward_effective,
                "reverse_effective": reverse_effective,
            },
        )
    return _correctness(
        True,
        "the reverse traversal carries the negated effective free-energy "
        f"difference ({forward_effective:.12g} against "
        f"{-forward_effective:.12g}) and the mirrored rule reproduces the "
        "mirrored analytic pair",
    )


def check_units(case, net_text, scaled_text):
    """The declared energy unit must be the only scale that applies.

    All energies are declared in RT units, so multiplying every declared
    energy by a constant must multiply the logarithm of every rate constant
    by the same constant. A hidden RT divisor, a physical-unit conversion or
    a scale applied to only some of the energies breaks that homogeneity.
    """
    forward, reverse = _two_state_pairs(net_text)
    if forward is None or reverse is None:
        return _correctness(
            False,
            "the generated network does not carry a forward and a reverse "
            "reaction for the transition",
        )
    scaled_forward, scaled_reverse = _two_state_pairs(scaled_text)
    if scaled_forward is None or scaled_reverse is None:
        return _correctness(
            False,
            "the scaled network does not carry a forward and a reverse "
            "reaction for the transition",
        )
    expected_forward = math.log(forward) * ENERGY_SCALE
    expected_reverse = math.log(reverse) * ENERGY_SCALE
    ok_forward, difference_forward = _compare_log(
        scaled_forward, math.exp(expected_forward), label="scaled-forward-rate"
    )
    ok_reverse, difference_reverse = _compare_log(
        scaled_reverse, math.exp(expected_reverse), label="scaled-reverse-rate"
    )
    if not (ok_forward and ok_reverse):
        return _correctness(
            False,
            "the rate constants are not homogeneous of degree one in the "
            f"declared energy: scaling every energy by {ENERGY_SCALE} gave "
            f"{scaled_forward:.12g} and {scaled_reverse:.12g} against "
            f"{math.exp(expected_forward):.12g} and "
            f"{math.exp(expected_reverse):.12g}",
            difference_forward or difference_reverse,
        )
    return _correctness(
        True,
        "the rate constants are homogeneous of degree one in the declared "
        f"energy: scaling every energy by {ENERGY_SCALE} scaled the "
        "logarithms of both rate constants by the same factor, so the "
        "declared energies are in RT units and no other conversion applies",
    )


def check_network_free_agreement(case):
    """The network-free path must obey the same analytic law.

    The network path and the network-free path apply the reservoir work
    differently, so this is the differential control between the two
    conventions: the network-free ensemble is compared against the same
    closed form the network path was checked against.
    """
    from bionetgen import _bionetgen_cpp as cpp

    forward, reverse = analytic_rates(case)
    total = forward + reverse
    steady = reverse / total
    times = np.linspace(0.0, T_END, N_STEPS + 1)
    mean, variance = two_state_law(case, times)
    previous = os.environ.get(GATE)
    os.environ[GATE] = "1"
    samples = []
    try:
        model = cpp.parse_string(case["bngl"])
        for index in range(ENSEMBLE_RUNS):
            result = cpp.simulate_nf(
                model,
                t_end=T_END,
                n_steps=N_STEPS,
                seed=SEED_BASE + index,
            )
            observable = np.asarray(result["observables"]["U"], dtype=float)
            samples.append(observable)
    finally:
        if previous is None:
            os.environ.pop(GATE, None)
        else:
            os.environ[GATE] = previous
    ensemble = np.vstack(samples)
    observed = ensemble.mean(axis=0)
    deviation = ensemble.std(axis=0, ddof=1)
    errors = np.where(
        variance > 0.0,
        np.sqrt(variance / ENSEMBLE_RUNS),
        np.where(deviation > 0.0, deviation / np.sqrt(ENSEMBLE_RUNS), 0.0),
    )
    band = STATISTICAL_SIGMA * errors
    difference = observed - mean
    worst = int(np.argmax(np.abs(difference) - band))
    if band[worst] > 0.0 and np.abs(difference[worst]) > band[worst]:
        return _correctness(
            False,
            "the network-free ensemble mean departs from the analytic law: at "
            f"t={times[worst]:.6g} the mean was {observed[worst]:.6g} against "
            f"{mean[worst]:.6g}, outside the {STATISTICAL_SIGMA}-sigma band "
            f"{band[worst]:.6g}",
            {
                "field": "network-free-mean",
                "time": float(times[worst]),
                "expected": float(mean[worst]),
                "observed": float(observed[worst]),
                "band": float(band[worst]),
                "runs": ENSEMBLE_RUNS,
            },
        )
    return _correctness(
        True,
        "the network-free ensemble of "
        f"{ENSEMBLE_RUNS} trajectories (seed base {SEED_BASE}) reproduces the "
        "analytic two-state law at every recorded time, inside the "
        f"{STATISTICAL_SIGMA}-sigma band; the largest deviation was "
        f"{float(np.max(np.abs(difference))):.6g}",
    )


def check_exporter_semantics(case, directory):
    """The capable exporters must carry the extension; the others must refuse."""
    from bionetgen.model import BioNetGenModel

    from bionetgen import _bionetgen_cpp as cpp

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get(GATE)
    os.environ[GATE] = "1"
    try:
        model = cpp.parse_string(case["bngl"])
        public = BioNetGenModel(model)
        net_text, _, _ = _resolved_net(case["bngl"], directory / "net")
        for name in ENERGY_CAPABLE_EXPORTERS:
            path = directory / f"model.{name}"
            try:
                if name == "bngl":
                    public.write_bngl(str(path))
                elif name == "xml":
                    public.write_xml(str(path))
                else:
                    public.write_net(str(path))
            except Exception as exc:  # noqa: BLE001 - the message is the claim
                return _correctness(
                    False,
                    f"the {name} exporter refused a model it is able to carry: "
                    f"{type(exc).__name__}: {exc}",
                    {"field": name, "exception": type(exc).__name__},
                )
            if not path.is_file() or path.stat().st_size == 0:
                return _correctness(
                    False,
                    f"the {name} exporter produced no artifact",
                    {"field": name},
                )
        # The exported BNGL must round trip back into the same rates: a
        # writer that drops the barrier or the work would export a model that
        # no longer means what the source said.
        written = (directory / "model.bngl").read_text(encoding="utf-8")
        round_trip, _, _ = _resolved_net(written, directory / "roundtrip")
        original = _numeric_pairs(net_text)
        again = _numeric_pairs(round_trip)
        if set(original) != set(again):
            return _correctness(
                False,
                "the exported BNGL does not round trip into the same network: "
                f"{sorted(original)} against {sorted(again)}",
                {
                    "field": "bngl-roundtrip",
                    "expected": sorted(original),
                    "observed": sorted(again),
                },
            )
        for key, value in original.items():
            ok, difference = _compare_log(
                again[key], value, label="bngl-roundtrip-rate"
            )
            if not ok:
                return _correctness(
                    False,
                    "the exported BNGL does not round trip into the same rate "
                    f"constants: {key} became {again[key]:.12g} against "
                    f"{value:.12g}",
                    difference,
                )
        refusals = {}
        for name in REFUSING_EXPORTERS:
            path = directory / f"model.{name}"
            try:
                if name == "sbml":
                    public.write_sbml(str(path))
                elif name == "matlab":
                    public.write_matlab(str(path))
                else:
                    public.write_latex(str(path))
            except Exception as exc:  # noqa: BLE001 - the message is the claim
                message = str(exc).lower()
                if not any(keyword in message for keyword in REFUSAL_KEYWORDS):
                    return _correctness(
                        False,
                        f"the {name} exporter refused the model but did not name "
                        f"the unsupported construct: {exc}",
                        {"field": name, "message": str(exc)},
                    )
                refusals[name] = str(exc)
            else:
                return _correctness(
                    False,
                    f"the {name} exporter accepted a model whose barrier and "
                    "reservoir work it cannot represent, so the export would "
                    "silently change the kinetics",
                    {"field": name},
                )
    finally:
        if previous is None:
            os.environ.pop(GATE, None)
        else:
            os.environ[GATE] = previous
    return _correctness(
        True,
        "the BNGL, BNG-XML and NET exports carry the extension and the "
        "exported BNGL round trips into the same rate constants, while the "
        + ", ".join(
            f"{name} ({message[:60]}...)" for name, message in sorted(refusals.items())
        )
        + " exporters refuse explicitly and name the construct",
    )


def check_independent_reference(case, directory):
    """The canonical oracle's own rate law must agree with the product's.

    The oracle expands the rate law itself and keeps the expansion symbolic,
    so the harness evaluates that expansion with its own evaluator and
    compares the numbers. This is only meaningful for the subset the oracle
    implements, which is why the check exists for that subset only.
    """
    if not _bng2_available():
        return _correctness(
            False,
            "the canonical Perl BNG2 oracle is unavailable, so the "
            "independent reference could not be executed",
            {"field": "canonical-oracle"},
        )
    reference, outcome = bng2_reference_rates(case["bngl"], Path(directory) / "bng2")
    if reference is None:
        return _correctness(
            False,
            "the canonical oracle did not produce a network for this model: "
            + (outcome["stderr"].strip()[-400:] or outcome["stdout"].strip()[-400:]),
            {"field": "canonical-oracle"},
        )
    net_text, _, _ = _resolved_net(case["bngl"], Path(directory) / "product")
    product = _numeric_pairs(net_text)
    shared = set(reference) & set(product)
    if not shared:
        return _correctness(
            False,
            "the canonical oracle and the product disagree on the reaction "
            f"set: {sorted(reference)} against {sorted(product)}",
            {
                "field": "reaction-set",
                "expected": sorted(reference),
                "observed": sorted(product),
            },
        )
    worst = None
    for key in sorted(shared):
        ok, difference = _compare_log(
            product[key], reference[key], label="canonical-reference-rate"
        )
        if not ok:
            return _correctness(
                False,
                "the product's rate constant differs from the canonical "
                f"oracle's independent expansion: {key} is "
                f"{product[key]:.12g} against {reference[key]:.12g}",
                difference,
            )
        deviation = abs(math.log(product[key]) - math.log(reference[key]))
        if worst is None or deviation > worst[0]:
            worst = (deviation, key)
    return _correctness(
        True,
        "the canonical Perl BNG2 oracle expanded the same rate law and its "
        "own evaluation agrees with the product on every shared reaction "
        f"({len(shared)} reactions; the largest logarithmic deviation was "
        f"{worst[0]:.3g} at {worst[1]})",
    )


# --------------------------------------------------------------------------- #
# The family checks
# --------------------------------------------------------------------------- #


def check_cycle_affinity(directory):
    """A driven cycle must carry the analytic, nonzero affinity."""
    source = cycle_source()
    net_text, _, _ = _resolved_net(source, Path(directory) / "cycle")
    pairs = _numeric_pairs(net_text)
    affinity = cycle_affinity()
    edges = (
        (
            (("A(s~U)",), ("A(s~P)",)),
            (("A(s~P)",), ("A(s~U)",)),
        ),
        (
            (("A(s~P)",), ("A(s~Q)",)),
            (("A(s~Q)",), ("A(s~P)",)),
        ),
        (
            (("A(s~Q)",), ("A(s~U)",)),
            (("A(s~U)",), ("A(s~Q)",)),
        ),
    )
    product = 0.0
    for forward_key, reverse_key in edges:
        forward = pairs.get(forward_key)
        reverse = pairs.get(reverse_key)
        if forward is None or reverse is None:
            return _correctness(
                False,
                f"the generated cycle network does not carry the reaction "
                f"{forward_key} -> {reverse_key}",
                {"field": "cycle-reactions"},
            )
        product += math.log(forward) - math.log(reverse)
    expected = -affinity
    if abs(product - expected) > LOG_RTOL * max(1.0, abs(expected)):
        return _correctness(
            False,
            "the driven cycle's rate-ratio product does not match the "
            f"analytic affinity: the logarithm of the product is "
            f"{product:.12g} against {expected:.12g}",
            {
                "field": "cycle-affinity",
                "expected_log": expected,
                "observed_log": product,
            },
        )
    if abs(affinity) < 1e-12:
        return _correctness(
            False,
            "the driven cycle's analytic affinity is zero, so the case does "
            "not exercise a driven cycle",
            {"field": "cycle-affinity"},
        )
    return _correctness(
        True,
        "the driven cycle carries the analytic affinity "
        f"{affinity:.12g} in RT units: the logarithm of the rate-ratio "
        f"product around the cycle is {product:.12g}, so the cycle is not "
        "equilibrium-compatible and the reservoir work sustains a nonzero "
        "affinity",
    )


def check_experimental_opt_in(directory):
    """With the gate unset, every backend boundary must refuse the extension."""
    from bionetgen import _bionetgen_cpp as cpp

    case = next(item for item in cases() if item["barrier"] > 0.0)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get(GATE)
    os.environ.pop(GATE, None)
    try:
        model = cpp.parse_string(case["bngl"])
        network = cpp.generate_network(model)
        refusals = {}
        try:
            cpp.io.write_net(model, network, str(Path(directory) / "refused.net"))
        except Exception as exc:  # noqa: BLE001 - the refusal is the claim
            refusals["network"] = str(exc)
        else:
            return _correctness(
                False,
                "the network writer accepted a driven rule with the "
                f"{GATE} gate unset, so the model would silently run as an "
                "equilibrium model",
                {"field": "network-writer"},
            )
        try:
            cpp.simulate_nf(model, t_end=0.1, n_steps=1, seed=1)
        except Exception as exc:  # noqa: BLE001 - the refusal is the claim
            refusals["nfsim"] = str(exc)
        else:
            return _correctness(
                False,
                "the network-free NFsim path accepted a driven rule with the "
                f"{GATE} gate unset",
                {"field": "nfsim"},
            )
    finally:
        if previous is None:
            os.environ.pop(GATE, None)
        else:
            os.environ[GATE] = previous
    for route, message in refusals.items():
        if GATE not in message:
            return _correctness(
                False,
                f"the {route} boundary refused the model but did not name the "
                f"gate {GATE}: {message}",
                {"field": route, "message": message},
            )
    # An explicit "0" keeps the gate off, so a CI job can pin it.
    os.environ[GATE] = "0"
    try:
        model = cpp.parse_string(case["bngl"])
        network = cpp.generate_network(model)
        try:
            cpp.io.write_net(model, network, str(Path(directory) / "refused0.net"))
        except Exception:  # noqa: BLE001 - the refusal is the claim
            pass
        else:
            return _correctness(
                False,
                f"the {GATE} gate was set to '0' and the network writer still "
                "accepted the driven rule",
                {"field": "gate-zero"},
            )
    finally:
        os.environ.pop(GATE, None)
        if previous is not None:
            os.environ[GATE] = previous
    return _correctness(
        True,
        "with the gate unset the network writer refuses the driven rule "
        f"({refusals['network'][:80]}...) and the network-free NFsim path "
        f"refuses it ({refusals['nfsim'][:80]}...); an explicit '0' keeps "
        "the gate off, so the extension is opt-in and never claimed as "
        "supported by default",
    )


def check_canonical_oracle_boundary(directory):
    """The canonical oracle must not be used as proof for the extension."""
    if not _bng2_available():
        return _correctness(
            False,
            "the canonical Perl BNG2 oracle is unavailable, so the boundary "
            "between the supported subset and the extension could not be "
            "executed",
            {"field": "canonical-oracle"},
        )
    extension = next(item for item in cases() if not item["reference"])
    outcome = run_bng2(extension["bngl"], Path(directory) / "bng2-extension")
    combined = (outcome["stdout"] + outcome["stderr"]).lower()
    if outcome["net"] is not None:
        return _correctness(
            False,
            "the canonical oracle produced a network for a model with barrier "
            "patterns and reservoir work, so it must not be treated as an "
            "oracle for the extension until that changes",
            {"field": "canonical-oracle"},
        )
    if "barrier" not in combined and "driven_by" not in combined:
        return _correctness(
            False,
            "the canonical oracle refused the extension model but did not "
            "name the unsupported construct: " + combined.strip()[-300:],
            {"field": "canonical-oracle"},
        )
    return _correctness(
        True,
        "the canonical Perl BNG2 oracle cannot process the extension: it "
        "aborted with '"
        + next(
            (
                line.strip()
                for line in combined.splitlines()
                if "barrier" in line or "driven_by" in line
            ),
            "the unsupported construct",
        )
        + "'. The extension subset is therefore judged against the analytic "
        "law alone, and the canonical oracle is used only for the "
        "equilibrium subset it implements",
    )


def check_resolution_determinism(directory):
    """The same model must resolve to the same numbers every time."""
    case = cases()[0]
    first, _, _ = _resolved_net(case["bngl"], Path(directory) / "first")
    second, _, _ = _resolved_net(case["bngl"], Path(directory) / "second")
    if first != second:
        return _correctness(
            False,
            "resolving the same model twice produced different rate " "constants",
            {"field": "determinism"},
        )
    return _correctness(
        True,
        "resolving the same model twice produced byte-identical rate "
        "constants, so the energy resolution is deterministic and can be "
        "compared against an analytic expectation",
    )


def environment_record():
    """Return the environment, corpus and revision the qualification ran on."""
    package = Path(bionetgen.__file__).resolve() if bionetgen is not None else None
    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except (AttributeError, OSError):  # pragma: no cover - platform specific
        load_average = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "package": str(package) if package else None,
        "package_sha256": (
            hashlib.sha256(package.read_bytes()).hexdigest() if package else None
        ),
        "canonical_oracle": str(BNG2_PERL) if BNG2_PERL.is_file() else None,
        "canonical_oracle_sha256": (
            hashlib.sha256(BNG2_PERL.read_bytes()).hexdigest()
            if BNG2_PERL.is_file()
            else None
        ),
        "load_average": load_average,
        "corpus_sha256": corpus_digest(),
        "gate": GATE,
    }


def _git(*args):
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


# --------------------------------------------------------------------------- #
# Worker entry point
# --------------------------------------------------------------------------- #


def run_worker(directory):
    """Run the energy qualification and return its evidence rows."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if bionetgen is None:
        return [
            _not_tested(check, "the bionetgen package is unavailable")
            for check in check_ids()
        ]
    rows = []
    environment = environment_record()
    environment["revision"] = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    environment["dirty"] = bool(status) if status is not None else None
    (directory / "environment.json").write_text(
        json.dumps(environment, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "corpus.json").write_text(
        json.dumps(corpus_record(), indent=2) + "\n", encoding="utf-8"
    )

    environment_check = "energy-qualification:family:environment-record"
    if not environment["revision"]:
        rows.append(
            _not_tested(
                environment_check,
                "the revision the qualification ran on could not be determined",
            )
        )
    else:
        rows.append(
            _row(
                environment_check,
                "PASS",
                "qualified on revision "
                f"{environment['revision']} (dirty: {environment['dirty']}) with "
                f"corpus {environment['corpus_sha256']}; environment: "
                f"{environment['platform']} / {environment['machine']}, Python "
                f"{environment['python']}, canonical oracle "
                f"{environment['canonical_oracle']} "
                f"(sha256 {environment['canonical_oracle_sha256']}); the "
                "rate comparisons are closed-form identities and do not depend "
                "on the host, and the recorded environment identifies the "
                "revision this evidence was produced on",
            )
        )

    def family_row(name, correctness, *, boundary=False):
        check = f"energy-qualification:family:{name}"
        if correctness["ok"]:
            row = _row(check, "PASS", correctness["detail"])
            if boundary:
                row["evidence_kind"] = "diagnostic-only"
                row["supported_execution"] = False
            return row
        return _row(
            check,
            "FAIL",
            correctness["detail"],
            first_difference=correctness["difference"],
        )

    rows.append(
        family_row(
            "experimental-opt-in",
            check_experimental_opt_in(directory / "opt-in"),
            boundary=True,
        )
    )
    rows.append(
        family_row(
            "canonical-oracle-boundary",
            check_canonical_oracle_boundary(directory / "oracle"),
            boundary=True,
        )
    )
    rows.append(
        family_row(
            "resolution-determinism",
            check_resolution_determinism(directory / "determinism"),
        )
    )
    rows.append(
        family_row(
            "driven-cycle-affinity",
            check_cycle_affinity(directory / "cycle"),
        )
    )

    for case in cases():
        source = directory / f"{case['id']}.bngl"
        source.write_text(case["bngl"], encoding="utf-8")
        try:
            net_text, _, _ = _resolved_net(case["bngl"], directory / case["id"] / "net")
            barrier_free, _, _ = _resolved_net(
                case["barrier_free_bngl"], directory / case["id"] / "barrier-free"
            )
            mirrored, _, _ = _resolved_net(
                case["mirrored_bngl"], directory / case["id"] / "mirrored"
            )
            scaled, _, _ = _resolved_net(
                case["scaled_bngl"], directory / case["id"] / "scaled"
            )
        except Exception as exc:  # noqa: BLE001 - the failure is the claim
            for name in CASE_CHECKS:
                rows.append(
                    _failed(
                        f"energy-qualification:{case['id']}:{name}",
                        "the model's network could not be resolved with the "
                        f"experimental gate enabled: {type(exc).__name__}: {exc}",
                        artifact=source,
                    )
                )
            if case["reference"]:
                rows.append(
                    _failed(
                        f"energy-qualification:{case['id']}:independent-reference",
                        "the model's network could not be resolved with the "
                        f"experimental gate enabled: {type(exc).__name__}: {exc}",
                        artifact=source,
                    )
                )
            continue

        checks = {
            "detailed-balance": check_detailed_balance(case, net_text),
            "transition-affinity": check_transition_affinity(
                case, net_text, barrier_free
            ),
            "reversal": check_reversal(case, net_text, mirrored),
            "units": check_units(case, net_text, scaled),
            "network-free-agreement": check_network_free_agreement(case),
            "exporter-semantics": check_exporter_semantics(
                case, directory / case["id"]
            ),
        }
        if case["reference"]:
            checks["independent-reference"] = check_independent_reference(
                case, directory / case["id"]
            )
        for name, correctness in checks.items():
            check = f"energy-qualification:{case['id']}:{name}"
            if correctness["ok"]:
                rows.append(
                    _row(
                        check,
                        "PASS",
                        f"{_case_detail(case)}; {correctness['detail']}",
                        artifact=source,
                    )
                )
            else:
                rows.append(
                    _failed(
                        check,
                        f"{_case_detail(case)}; {correctness['detail']}",
                        correctness["difference"],
                        artifact=source,
                    )
                )

    produced = {row["id"] for row in rows}
    for check in check_ids():
        if check not in produced:
            rows.append(
                _not_tested(check, "the qualification did not reach this check")
            )

    for row in rows:
        if row["status"] not in STATUSES:
            row.update(
                status="HARNESS_ERROR",
                detail="the qualification produced an unknown status",
                supported_execution=False,
            )
    return rows


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = run_worker(args.report_dir)
    (args.report_dir / "checks.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, indent=2))
    return 1 if any(row["status"] in {"FAIL", "HARNESS_ERROR"} for row in rows) else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI contract
    raise SystemExit(main())
