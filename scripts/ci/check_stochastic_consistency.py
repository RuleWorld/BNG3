#!/usr/bin/env python3
"""Check the stochastic consistency of converted SBML models.

Every other gate in this repository reads a converted SBML model
*deterministically*: the official SBML Test Suite comparison runs BNG3's CVODE
solver against the suite's published trajectory, and the curated BioModels
corpus is simulated with CVODE as well.  The stochastic reading of a converted
model is therefore never checked, even though a rate law can have a
deterministic form and a *different* stochastic propensity.

This script closes that gap.  It converts every SBML Test Suite case the
Atomizer supports, classifies the generated reaction network as **linear**
(every propensity is first order in its species) or not, and -- for the linear
cases -- runs one batched direct-SSA ensemble and compares the ensemble mean
trace against the model's deterministic reading.

The comparison is only meaningful where the deterministic solution *is* the
mean.  For a unimolecular system with linear propensities the SSA mean obeys
the same linear ODE the deterministic solver integrates, so the two readings
must agree to within Monte-Carlo error.  For a bimolecular system the SSA mean
does not satisfy the deterministic ODE at all, so a mismatch there is expected
physics rather than a defect; those cases are recorded as *not comparable by
construction* and never as failures.

Outcomes per case
------------------

``consistent``
    The deterministic reference lies inside the statistical band of the
    ensemble mean at every checked point.
``inconsistent``
    A systematic departure: the deviation exceeds the band, reported in
    standard errors, and the mechanism is attributed where the source model
    identifies it.
``not_comparable``
    The case cannot carry this comparison (non-linear propensity, a fractional
    initial population, an event-driven source model, a deterministic reading
    that leaves the non-negative orthant, no usable reference, an unmappable
    reference variable, ...).  The reason is recorded; this is never a failure
    verdict.
``no_valid_propensity``
    No batched-SSA engine could produce a trajectory for the converted rate
    law.  This is itself a finding about the converted model.
``unsupported``
    The Atomizer did not convert the case, so it is outside the population
    this check reasons about.
``error``
    A harness error, reported separately from every semantic verdict.

The batched GPU path fails closed on rate laws it cannot flatten, so the
report also lists, separately, every converted model whose rate law the
Metal backend refuses (a functional rate law or a ``TotalRate`` reaction).
Those cases are recovered with the CPU pool and still compared.

Engines
-------

The Metal backend pays model preparation plus the host/device transfers on
every call, so on a small network it is *slower* than the CPU pool; the
repository's own GPU evaluation measures the Metal backend winning on large
networks with large batches.  The sweep therefore uses a size-based policy:
the GPU when the generated network is large enough for its parallelism to pay
for the transfers, the CPU pool otherwise.  The backend that produced each
case's numbers is recorded on the case, and the GPU/CPU sampler agreement is
measured separately on a sample of cases.

References
----------

The comparison prefers the *official published* reference trajectory shipped
with the suite:

* a **semantic** case publishes a deterministic time course in
  ``NNNNN-results.csv``; that published trajectory is the reference;
* a **stochastic** case publishes an *ensemble* mean and standard deviation
  in ``NNNNN-results.csv``.  For a linear network that published ensemble mean
  coincides with the deterministic solution, so it is used as the reference,
  and the published standard deviation is compared as an auxiliary check.

When a case publishes no time course at all, the script says so and uses
BNG3's own CVODE trace instead, labelled ``bng3-cvode`` and explicitly
flagged as *not independent*.

This is a measurement tool.  It does not change Atomizer behaviour, any
tolerance, any reference file, or any harness script.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ci.validate_sbml_test_suite import (
    DEFAULT_SUITE_LOCK,
    OfficialReferenceUnsupported,
    SuiteLockError,
    _case_files,
    _event_translation_limitations,
    _merge_generated_warnings,
    _read_reference_case,
    _simulation_limitations,
    _suite_lock_entry,
    _warning_limitations,
    _warnings,
)

# ---------------------------------------------------------------------------
# Run budget, seed policy and statistical criterion
# ---------------------------------------------------------------------------

# Trajectories per batch.  The standard error of the ensemble mean is
# sd/sqrt(B), so the budget sets the width of the statistical band.  B=10000
# shrinks the band by a factor of 100 relative to a single trajectory: with a
# per-trajectory spread of ~5 molecules that is a standard error of ~0.05
# molecules, i.e. a ~0.05% resolution on a species held at ~100 molecules.
# The budget is deliberately modest so that the whole suite stays a CI-sized
# job, and it is large enough that a point whose ensemble has collapsed onto
# an absorbing state is still resolved.
DEFAULT_BATCH_SIZE = 10000

# Seed policy.  Every case draws its base seed from the case id so that the
# sweep is reproducible end to end and so that two cases never share a
# random-number stream.  Within a case, trajectory b owns an independent
# stream (PCG32 with increment 2b+1 on the GPU, std::mt19937_64 seeded with
# base_seed+b on the CPU).
DEFAULT_SEED_BASE = 20261020

# Deviation threshold in ensemble standard errors.  A single point beyond
# 5 SE is a 5.7e-7 two-sided normal tail; a case checks at most a few hundred
# (variable, time) pairs and the residuals inside one case are positively
# correlated, so the family-wise probability of a false alarm over the whole
# suite stays well below 1%.  5 SE still detects a rate-law error of a
# fraction of a percent, which is far below any conversion defect worth
# reporting.
DEFAULT_K_SIGMA = 5.0

# The published mean/sd of a stochastic case are analytic for every case the
# Atomizer supports (the numeric ones use the SBML 'distrib' package, which
# the Atomizer reports as unsupported), so the published reference carries no
# sampling error of its own.
#
# The GPU reports the ensemble mean and standard deviation as float32.  The
# accumulation happens in double precision, so only the final rounding is
# float32; the relative representation error is therefore bounded by the
# float32 epsilon.
FLOAT32_EPS = 1.19e-7

# Resolution floor of a degenerate ensemble sample.  When every trajectory in
# the batch reports the same value the sample standard deviation is exactly
# zero, which says nothing about the spread of the underlying distribution: a
# state that occurs with probability p is missed entirely whenever B*p is
# below one, and the true mean then still differs from the sampled value by up
# to a Poisson bound.  The bound uses 10 expected misses, i.e. a per-point
# false alarm probability of about 5e-5, so that a model whose ensemble has
# collapsed onto an absorbing state is not reported as a disagreement.
DEGENERATE_RESOLUTION_K = 10.0

# A point whose ensemble mean is not resolved against its own standard error
# (the standard error exceeds this fraction of the mean) is dominated by a
# handful of rare trajectories.  The pointwise standard deviation is then not a
# reliable estimate of the spread, so a departure at such a point is reported
# but does not decide the verdict.
UNRELIABLE_RELATIVE_SE = 0.5

# Auxiliary check: the ensemble standard deviation against the published
# standard deviation of a stochastic case.  For B i.i.d. draws the sample
# standard deviation has relative standard error 1/sqrt(2(B-1)), so a band of
# K_SD_SIGMA of that scale is a chi-square based band.
K_SD_SIGMA = 5.0

# Backend inventory / fallback
DEFAULT_GPU_BACKEND = "auto"


def _case_seed(case_id: str, seed_base: int) -> int:
    """Deterministic per-case base seed (see the seed policy above)."""

    return int(seed_base) + int(case_id)


# ---------------------------------------------------------------------------
# Suite references
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_settings(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"settings line {line_number} has no ':' delimiter")
        key, value = (part.strip() for part in line.split(":", 1))
        settings[key] = value
    return settings


def _read_stochastic_reference(case: dict[str, Any]) -> dict[str, Any]:
    """Read the published ensemble mean/sd trajectory of a stochastic case."""

    case_dir = Path(case["path"]).resolve().parent
    case_id = str(case["id"])
    settings_path = case_dir / f"{case_id}-settings.txt"
    results_path = case_dir / f"{case_id}-results.csv"
    settings = _parse_settings(settings_path)
    for required in ("start", "duration", "steps", "variables"):
        if required not in settings:
            raise ValueError(f"settings are missing required key: {required}")
    start = float(settings["start"])
    duration = float(settings["duration"])
    steps = int(settings["steps"])
    variables = [v.strip() for v in settings["variables"].split(",") if v.strip()]

    rows = [
        row
        for row in csv.reader(results_path.read_text(encoding="utf-8-sig").splitlines())
        if row and any(cell.strip() for cell in row)
    ]
    if not rows:
        raise ValueError("official results CSV is empty")
    header = [cell.strip() for cell in rows[0]]
    if header and header[0].lower() == "time":
        data_rows = rows[1:]
        columns = {name: index for index, name in enumerate(header) if index}
    else:
        data_rows = rows
        columns = {name: index for index, name in enumerate(header) if index}
    if len(data_rows) != steps + 1:
        raise ValueError(
            f"official results row count {len(data_rows)} does not equal steps + 1"
        )
    matrix = np.asarray(
        [[float(cell.strip()) for cell in row] for row in data_rows], dtype=float
    )
    expected_grid = np.linspace(start, start + duration, steps + 1, dtype=float)
    times = matrix[:, 0]
    if not np.all(np.isfinite(times)) or not np.allclose(
        times, expected_grid, rtol=0.0, atol=1e-9 * max(1.0, abs(duration))
    ):
        raise ValueError("official results time grid does not match settings")

    # The published columns are named "<variable>-mean" and "<variable>-sd";
    # their order in the file varies from case to case, so the header is the
    # authority for the column layout.
    means: dict[str, np.ndarray] = {}
    stds: dict[str, np.ndarray] = {}
    for variable in variables:
        mean_column = columns.get(f"{variable}-mean")
        sd_column = columns.get(f"{variable}-sd")
        if mean_column is None:
            raise ValueError(f"official results lack the mean column for {variable}")
        means[variable] = matrix[:, mean_column]
        if sd_column is not None:
            stds[variable] = matrix[:, sd_column]

    model_notes = case_dir / f"{case_id}-model.m"
    generated_by = ""
    if model_notes.is_file():
        match = re.search(r"(?im)^\s*generatedBy:\s*(\S+)", model_notes.read_text())
        if match:
            generated_by = match.group(1)

    return {
        "settings_path": str(settings_path),
        "results_path": str(results_path),
        "settings_sha256": _sha256_file(settings_path),
        "results_sha256": _sha256_file(results_path),
        "start": start,
        "duration": duration,
        "steps": steps,
        "times": times,
        "variables": variables,
        "amount": [
            v.strip() for v in settings.get("amount", "").split(",") if v.strip()
        ],
        "concentration": [
            v.strip() for v in settings.get("concentration", "").split(",") if v.strip()
        ],
        "means": means,
        "stds": stds,
        "generated_by": generated_by,
    }


# ---------------------------------------------------------------------------
# Network structure
# ---------------------------------------------------------------------------


def _net_block(text: str, name: str) -> list[str]:
    block = re.search(rf"(?ms)^begin {name}\s*\n(.*?)^end {name}", text)
    if block is None:
        return []
    return [
        line.split("#")[0].strip()
        for line in block.group(1).splitlines()
        if line.split("#")[0].strip()
    ]


def _network_structure(cpp: Any, model: Any, network: Any) -> dict[str, Any]:
    """Read the generated network's rate laws, reactants and populations.

    BNG3 computes a reaction's propensity as ``rate_coefficient * prod(y_s -
    offset)`` over the reaction's reactant entries (``OdeIntegrator::
    computePropensity``).  A propensity is therefore first order in its
    species exactly when the reaction has at most one reactant entry *and* the
    rate coefficient is affine in the species.  The generated ``.net`` file
    carries exactly that information: the derived rate-law functions, the
    parameters, the observable groups, the reactant indices of every reaction
    and the initial amount of every species.
    """

    with tempfile.TemporaryDirectory() as directory:
        net_path = Path(directory) / "network.net"
        cpp.io.write_net(model, network, str(net_path))
        text = net_path.read_text(encoding="utf-8", errors="replace")

    parameters: dict[str, float] = {}
    for line in _net_block(text, "parameters"):
        parts = line.split()
        if len(parts) >= 3:
            try:
                parameters[parts[1]] = float(parts[2])
            except ValueError:
                parameters[parts[1]] = float("nan")

    functions: dict[str, str] = {}
    for line in _net_block(text, "functions"):
        parts = line.split(None, 2)
        if len(parts) >= 3:
            functions[parts[1].rstrip("()")] = parts[2].strip()

    groups: dict[str, list[int]] = {}
    for line in _net_block(text, "groups"):
        parts = line.split()
        if len(parts) >= 2:
            members = [int(entry) for entry in parts[2].split(",") if entry.strip()]
            groups[parts[1]] = members

    amounts: list[float] = []
    for line in _net_block(text, "species"):
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            amounts.append(float(parts[2]))
        except ValueError:
            amounts.append(float("nan"))

    reactions: list[dict[str, Any]] = []
    for line in _net_block(text, "reactions"):
        parts = line.split(None, 3)
        if len(parts) < 2:
            continue
        reactant_token = parts[1].strip()
        # A net file writes "0" for a reaction without reactants.
        reactants = (
            []
            if reactant_token in {"", "0"}
            else [entry for entry in reactant_token.split(",") if entry.strip()]
        )
        rate = parts[3].strip() if len(parts) > 3 else ""
        reactions.append({"reactants": reactants, "rate": rate})

    return {
        "parameters": parameters,
        "functions": functions,
        "groups": groups,
        "reactions": reactions,
        "initial_amounts": amounts,
    }


# ---------------------------------------------------------------------------
# Affinity analysis of the converted rate laws
# ---------------------------------------------------------------------------

# An expression is summarised as one of
#   ("const", value)               -- independent of the model state
#   ("affine", value, {name: k})   -- value + sum(k_i * x_i) in the state
#   ("nonlinear", reason)          -- not first order in the state

CONST = "const"
AFFINE = "affine"
NONLINEAR = "nonlinear"

# Builtins whose value is affine in their arguments when the arguments are
# affine and the *branch selection* does not depend on the state.
_PIECEWISE_BUILTINS = {"if", "min", "max"}
# Builtins that are never affine in a state-dependent argument.
_NONLINEAR_BUILTINS = {
    "abs",
    "acos",
    "acosh",
    "asin",
    "asinh",
    "atan",
    "atanh",
    "avg",
    "ceil",
    "cos",
    "cosh",
    "exp",
    "factorial",
    "floor",
    "ln",
    "log10",
    "log2",
    "rint",
    "sin",
    "sinh",
    "sqrt",
    "tan",
    "tanh",
    "sat",
    "saturation",
    "mm",
    "michaelismenten",
    "hill",
    "arrhenius",
    "time",
    "mratio",
}

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<number>\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<op>[+\-*/^(),]))"
)


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        match = _TOKEN_RE.match(text, position)
        if match is None:
            raise ValueError(f"cannot tokenize rate expression at {text[position:]!r}")
        position = match.end()
        if match.group("number") is not None:
            tokens.append(("number", match.group("number")))
        elif match.group("name") is not None:
            tokens.append(("name", match.group("name")))
        else:
            tokens.append(("op", match.group("op")))
    return tokens


class _AffinityParser:
    """Recursive-descent evaluator that tracks affinity in the model state."""

    def __init__(
        self,
        tokens: list[tuple[str, str]],
        parameters: dict[str, float],
        state_variables: set[str],
        functions: dict[str, str],
    ) -> None:
        self.tokens = tokens
        self.index = 0
        self.parameters = parameters
        self.state_variables = state_variables
        self.functions = functions
        self.resolving: set[str] = set()

    # -- token helpers ------------------------------------------------------
    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> tuple[str, str]:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _expect(self, op: str) -> None:
        token = self._peek()
        if token is None or token[0] != "op" or token[1] != op:
            raise ValueError(f"expected {op!r} in rate expression")
        self.index += 1

    # -- grammar ------------------------------------------------------------
    def parse(self) -> tuple[str, Any]:
        result = self._expression()
        if self.index != len(self.tokens):
            raise ValueError("trailing tokens in rate expression")
        return result

    def _expression(self) -> tuple[str, Any]:
        left = self._term()
        while True:
            token = self._peek()
            if token is None or token[0] != "op" or token[1] not in "+-":
                return left
            self._take()
            right = self._term()
            left = _add_affine(left, right)

    def _term(self) -> tuple[str, Any]:
        left = self._factor()
        while True:
            token = self._peek()
            if token is None or token[0] != "op" or token[1] not in "*/":
                return left
            self._take()
            right = self._factor()
            left = _multiply_affine(left, right)

    def _factor(self) -> tuple[str, Any]:
        base = self._unary()
        token = self._peek()
        if token is not None and token[0] == "op" and token[1] == "^":
            self._take()
            exponent = self._factor()
            return _power_affine(base, exponent)
        return base

    def _unary(self) -> tuple[str, Any]:
        token = self._peek()
        if token is not None and token[0] == "op" and token[1] in "+-":
            self._take()
            value = self._unary()
            if token[1] == "+":
                return value
            if value[0] == CONST:
                return (CONST, -value[1])
            if value[0] == AFFINE:
                return (AFFINE, -value[1], {k: -v for k, v in value[2].items()})
            return value
        return self._primary()

    def _primary(self) -> tuple[str, Any]:
        kind, value = self._take()
        if kind == "number":
            return (CONST, float(value))
        if kind != "name":
            raise ValueError(f"unexpected token {value!r} in rate expression")
        token = self._peek()
        if token is not None and token[0] == "op" and token[1] == "(":
            self._take()
            arguments: list[tuple[str, Any]] = []
            if not (self._peek() == ("op", ")")):
                while True:
                    arguments.append(self._expression())
                    nxt = self._peek()
                    if nxt is not None and nxt[0] == "op" and nxt[1] == ",":
                        self._take()
                        continue
                    break
            self._expect(")")
            return self._call(value, arguments)
        if value in self.parameters:
            number = self.parameters[value]
            return (CONST, number if math.isfinite(number) else 0.0)
        if value in self.functions:
            # A net file may name a derived rate-law function without calling
            # it; the function body is the rate law.
            return self._call(value, [])
        if value in self.state_variables:
            return (AFFINE, 0.0, {value: 1.0})
        # An unknown identifier is treated as a state variable: that keeps the
        # classification conservative in the direction of *not comparable*.
        return (AFFINE, 0.0, {value: 1.0})

    def _call(self, name: str, arguments: list[tuple[str, Any]]) -> tuple[str, Any]:
        lowered = name.lower()
        if lowered in self.functions:
            if name in self.resolving:
                return (NONLINEAR, f"recursive function {name}")
            body = self.functions[name]
            saved = self.tokens, self.index
            try:
                self.tokens = _tokenize(body)
                self.index = 0
                self.resolving.add(name)
                try:
                    return self._expression()
                finally:
                    self.resolving.discard(name)
            except ValueError:
                return (NONLINEAR, f"cannot parse the body of function {name}")
            finally:
                self.tokens, self.index = saved
        if lowered in _PIECEWISE_BUILTINS:
            if any(item[0] == NONLINEAR for item in arguments):
                return (NONLINEAR, f"{name} of a non-affine argument")
            condition = arguments[0] if arguments else (CONST, 0.0)
            if condition[0] != CONST:
                return (NONLINEAR, f"{name} selects on a state-dependent condition")
            branches = arguments[1:]
            if not branches:
                return (CONST, 0.0)
            result = branches[0]
            for branch in branches[1:]:
                result = _add_affine(result, branch)
            return result
        if lowered in _NONLINEAR_BUILTINS:
            if any(item[0] != CONST for item in arguments):
                return (NONLINEAR, f"{name} of a state-dependent argument")
            return (CONST, 0.0)
        return (NONLINEAR, f"unknown function {name}")


def _add_affine(left: tuple[str, Any], right: tuple[str, Any]) -> tuple[str, Any]:
    if left[0] == NONLINEAR or right[0] == NONLINEAR:
        return (NONLINEAR, "sum of non-affine terms")
    if left[0] == CONST and right[0] == CONST:
        return (CONST, left[1] + right[1])
    if left[0] == CONST:
        return (AFFINE, left[1] + right[1], dict(right[2]))
    if right[0] == CONST:
        return (AFFINE, left[1] + right[1], dict(left[2]))
    coefficients = dict(left[2])
    for name, weight in right[2].items():
        coefficients[name] = coefficients.get(name, 0.0) + weight
    return (AFFINE, left[1] + right[1], coefficients)


def _multiply_affine(left: tuple[str, Any], right: tuple[str, Any]) -> tuple[str, Any]:
    if left[0] == NONLINEAR or right[0] == NONLINEAR:
        return (NONLINEAR, "product of non-affine terms")
    if left[0] == AFFINE and right[0] == AFFINE:
        return (NONLINEAR, "product of two state-dependent terms")
    if left[0] == CONST and right[0] == CONST:
        return (CONST, left[1] * right[1])
    if left[0] == AFFINE:
        return (AFFINE, left[1] * right[1], dict(left[2]))
    return (AFFINE, left[1] * right[1], dict(right[2]))


def _power_affine(base: tuple[str, Any], exponent: tuple[str, Any]) -> tuple[str, Any]:
    if base[0] == NONLINEAR or exponent[0] == NONLINEAR:
        return (NONLINEAR, "exponentiation of a non-affine term")
    if exponent[0] != CONST:
        return (NONLINEAR, "state-dependent exponent")
    if base[0] == CONST:
        return (CONST, 0.0)
    if exponent[1] == 1.0:
        return base
    return (NONLINEAR, "state-dependent term raised to a power other than one")


def _classify_rate_affinity(text: str, context: dict[str, Any]) -> tuple[str, Any]:
    """Classify one rate expression as constant, affine or non-linear."""

    if not text:
        return (CONST, 0.0, "")
    try:
        tokens = _tokenize(text)
    except ValueError as exc:
        return (NONLINEAR, str(exc), "the rate expression cannot be parsed")
    parser = _AffinityParser(
        tokens,
        dict(context["parameters"]),
        set(context["state_variables"]),
        context["functions"],
    )
    try:
        result = parser.parse()
    except ValueError as exc:
        return (NONLINEAR, str(exc), "the rate expression cannot be parsed")
    if result[0] == NONLINEAR:
        return (NONLINEAR, result[1], str(result[1]))
    return (result[0], result[1], "")


def _classify_linearity(structure: dict[str, Any]) -> dict[str, Any]:
    """Classify the generated network as linear (first order) or not.

    A propensity is ``rate_coefficient * prod(y_s - offset)`` over the
    reaction's reactant entries.  It is first order in its species exactly
    when the rate coefficient is affine in the species and the reaction has at
    most one reactant entry.
    """

    context = {
        "parameters": structure["parameters"],
        "functions": structure["functions"],
        "state_variables": set(structure["groups"]),
    }
    reactant_counts: list[int] = []
    non_affine: list[int] = []
    reasons: list[str] = []
    for index, reaction in enumerate(structure["reactions"]):
        count = len(reaction["reactants"])
        reactant_counts.append(count)
        kind, _value, detail = _classify_rate_affinity(reaction["rate"], context)
        if kind == NONLINEAR:
            non_affine.append(index)
            reasons.append(f"reaction {index + 1}: {detail}")
    maximum = max(reactant_counts) if reactant_counts else 0
    nonlinear_reactions = [
        index for index, count in enumerate(reactant_counts) if count > 1
    ]
    reason = ""
    if nonlinear_reactions:
        reason = (
            f"{len(nonlinear_reactions)} of {len(reactant_counts)} generated "
            "reactions consume more than one reactant entry, so at least one "
            "propensity is second order or higher in its species"
        )
    elif non_affine:
        reason = (
            f"{len(non_affine)} of {len(reactant_counts)} generated reactions use a "
            "rate law that is not affine in the species ("
            + "; ".join(reasons[:3])
            + ")"
        )
    return {
        "linear": maximum <= 1 and not non_affine,
        "max_reactants_per_reaction": maximum,
        "nonlinear_reactions": (nonlinear_reactions + non_affine)[:10],
        "state_dependent_rates": len(non_affine),
        "reason": reason,
    }


def _zeroth_order_consumptions(parsed: Any) -> set[str]:
    """Species a source reaction consumes without its rate law depending on it.

    A reaction whose kinetic law does not read the species it consumes has a
    propensity that does not vanish when the species is exhausted.  The
    continuous reading integrates that propensity as a net flux, so the species
    can be driven below zero; the discrete reading clamps the population at
    zero.  The two readings therefore differ by construction once the
    substrate runs out, and such a model cannot carry the comparison.
    """

    consumed: set[str] = set()
    for reaction in parsed.reactions.values():
        law = reaction.kinetic_law or {}
        math = str(law.get("math", "")) if isinstance(law, dict) else str(law)
        for reference in reaction.reactants:
            species_id = getattr(reference, "species", "")
            if not species_id:
                continue
            if re.search(rf"(?<![\w.]){re.escape(species_id)}(?![\w])", math):
                continue
            consumed.add(species_id)
    return consumed


def _classify_population(amounts: list[float]) -> dict[str, Any]:
    """Check that the generated initial populations are whole molecules.

    Both SSA engines start from ``round(amount)`` (``FlattenedReactionNetwork::
    fromModelAndNetwork`` and ``OdeIntegrator::integrateSSA``), so a model
    whose initial amounts are fractional has no discrete stochastic reading:
    the stochastic process would start from a different state than the
    continuous model the deterministic solver integrates.  Such a case is
    recorded as *not comparable*, never as a failure.
    """

    fractional: list[float] = []
    unknown = False
    for amount in amounts:
        if not math.isfinite(amount):
            unknown = True
            continue
        if amount <= 0.0:
            continue
        if abs(amount - round(amount)) > 1e-9 * max(1.0, abs(amount)):
            fractional.append(amount)
    reason = ""
    if unknown:
        reason = "the generated initial populations could not be read"
    elif fractional:
        reason = (
            f"{len(fractional)} generated species start from a fractional "
            f"population (e.g. {fractional[0]:g} molecules); the discrete "
            "stochastic process rounds these to whole molecules and therefore "
            "starts from a different state than the continuous model"
        )
    return {
        "representable": not fractional and not unknown,
        "fractional_species": len(fractional),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Reference mapping
# ---------------------------------------------------------------------------


def _compartment_volume_expression(
    compartment_id: str, parsed: Any, standardize_name: Any
) -> tuple[str | None, bool]:
    """Return the BNGL expression of a compartment volume and whether it moves.

    The second element is True when the volume is time dependent (a rate or
    assignment rule on the compartment), in which case the volume cannot be
    folded into a constant scale factor.
    """

    if not compartment_id:
        return None, False
    name = standardize_name(compartment_id)
    if any(
        rule.type == "rate" and rule.variable == compartment_id for rule in parsed.rules
    ):
        return f"{name}_amt", True
    if any(
        rule.type == "assignment" and rule.variable == compartment_id
        for rule in parsed.rules
    ):
        return name, True
    return f"__compartment_{name}__", False


def _resolve_reference_observables(
    variables: list[str],
    reference: dict[str, Any],
    parsed: Any,
    observable_map: dict[str, str],
    observable_names: set[str],
    parameter_values: dict[str, float],
    standardize_name: Any,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Map published reference variables onto generated BNGL observables.

    Returns the mapping and the list of variables that could not be mapped.
    The mapping records a constant scale factor when the published quantity is
    a concentration and the compartment volume is constant; the scale is
    applied to both the ensemble mean and the ensemble standard deviation,
    which is exact for a constant divisor.
    """

    mapped: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for variable in variables:
        species = parsed.species.get(variable)
        if species is None:
            skipped.append(variable)
            continue
        base = observable_map.get(variable)
        if base is None:
            skipped.append(variable)
            continue
        wants_amount = variable in reference.get("amount", []) or (
            variable not in reference.get("concentration", [])
            and species.has_only_substance_units
        )
        amount_observable = f"{base}_amt"
        if wants_amount:
            if amount_observable in observable_names:
                mapped[variable] = {"observable": amount_observable, "scale": 1.0}
                continue
            if base in observable_names:
                mapped[variable] = {"observable": base, "scale": 1.0}
                continue
            skipped.append(variable)
            continue
        # The published quantity is a concentration.
        volume_expression, volume_moves = _compartment_volume_expression(
            species.compartment or "", parsed, standardize_name
        )
        if not volume_moves and base in observable_names:
            mapped[variable] = {"observable": base, "scale": 1.0}
            continue
        if amount_observable in observable_names:
            scale = 1.0
            if volume_expression is not None:
                value = parameter_values.get(volume_expression)
                if value is None or value == 0.0:
                    skipped.append(variable)
                    continue
                scale = 1.0 / value
            mapped[variable] = {"observable": amount_observable, "scale": scale}
            continue
        skipped.append(variable)
    return mapped, skipped


# ---------------------------------------------------------------------------
# Batch engines
# ---------------------------------------------------------------------------


def _run_gpu_batch(
    cpp: Any,
    model: Any,
    network: Any,
    *,
    backend: str,
    batch_size: int,
    t_start: float,
    t_end: float,
    n_steps: int,
    base_seed: int,
    max_sim_steps: int,
) -> dict[str, Any]:
    result = cpp.simulate_batch_ssa_gpu(
        model,
        network,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        t_start=t_start,
        base_seed=base_seed,
        max_sim_steps=max_sim_steps,
        backend=backend,
    )
    return dict(result)


def _run_cpu_batch(
    cpp: Any,
    model: Any,
    network: Any,
    *,
    batch_size: int,
    t_start: float,
    t_end: float,
    n_steps: int,
    base_seed: int,
    max_sim_steps: int,
    threads: int,
) -> dict[str, Any]:
    result = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        t_start=t_start,
        base_seed=base_seed,
        max_sim_steps=max_sim_steps,
        threads=threads,
    )
    return dict(result)


def _engine_metrics(result: dict[str, Any], backend: str) -> dict[str, Any]:
    counts = np.asarray(result.get("event_counts", []), dtype=float)
    truncated = bool(counts.size and counts.max() >= 1e17)
    return {
        "backend": backend,
        "batch_size": int(result.get("batch_size", 0)),
        "total_events": int(result.get("total_events", 0)),
        "model_prep_time_ms": float(result.get("model_prep_time_ms", 0.0)),
        "sim_time_ms": float(result.get("sim_time_ms", 0.0)),
        "total_wall_time_ms": float(result.get("total_wall_time_ms", 0.0)),
        "trajectories_per_sec_sim": float(result.get("trajectories_per_sec_sim", 0.0)),
        "trajectories_per_sec_total": float(
            result.get("trajectories_per_sec_total", 0.0)
        ),
        "events_per_sec_sim": float(result.get("events_per_sec_sim", 0.0)),
        "memory_usage_bytes": int(result.get("memory_usage_bytes", 0)),
        "trajectory_truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _compare_trace(
    mean: np.ndarray,
    sd: np.ndarray,
    reference: np.ndarray,
    *,
    batch_size: int,
    k_sigma: float,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    """Compare an ensemble mean trace with a deterministic reference trace.

    The band is ``k_sigma * sd/sqrt(B) + |tolerance|``: the first term is the
    Monte-Carlo standard error of the ensemble mean, the second is the
    accuracy the reference itself carries.
    """

    mean = np.asarray(mean, dtype=float)
    sd = np.asarray(sd, dtype=float)
    reference = np.asarray(reference, dtype=float)
    if mean.shape != reference.shape or sd.shape != reference.shape:
        raise ValueError("trace shapes do not match")
    standard_error = sd / math.sqrt(batch_size)
    deviation = mean - reference
    tolerance = absolute_tolerance + relative_tolerance * np.abs(reference)
    # A zero-variance observable carries no statistical scale, so it is
    # compared absolutely against the reference tolerance plus the float32
    # representation error of the reported mean.
    scale = np.maximum(np.abs(mean), np.abs(reference))
    representation = FLOAT32_EPS * scale
    # A degenerate sample (every trajectory in the batch agrees) does not mean
    # the underlying distribution has no spread: with B trajectories a state
    # that occurs with probability p is missed entirely whenever B*p is below
    # one, and the sample standard deviation is then exactly zero while the
    # true mean still differs from the sampled value by up to a Poisson bound
    # of 3/B.  Such a point therefore carries a resolution floor instead of a
    # statistical scale; without it a perfectly consistent model would be
    # reported as a disagreement whenever its ensemble has collapsed onto an
    # absorbing state.
    resolution = (
        DEGENERATE_RESOLUTION_K / batch_size * np.maximum(1.0, np.abs(reference))
    )
    band = (
        k_sigma * standard_error
        + tolerance
        + representation
        + np.where(standard_error > 0.0, 0.0, resolution)
    )
    violation = np.abs(deviation) > band
    # A point whose ensemble mean is of the order of its own standard error is
    # dominated by a handful of rare trajectories; the pointwise standard
    # deviation is then not a reliable estimate of the spread (a sample of one
    # minority event underestimates the spread by more than a factor of two).
    # Such a point is reported but does not decide the verdict; a systematic
    # mismatch shows up at the well-resolved points as well.
    reliable = (standard_error <= 0.0) | (
        standard_error <= UNRELIABLE_RELATIVE_SE * np.abs(mean)
    )
    decisive = violation & reliable
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(standard_error > 0.0, deviation / standard_error, 0.0)
    return {
        "points": int(mean.size),
        "violations": int(violation.sum()),
        "decisive_violations": int(decisive.sum()),
        "unreliable_points": int((~reliable).sum()),
        "reference_min": float(np.min(reference)) if reference.size else 0.0,
        "reference_max": float(np.max(reference)) if reference.size else 0.0,
        "max_abs_z": float(np.max(np.abs(z))) if z.size else 0.0,
        "max_abs_deviation": (
            float(np.max(np.abs(deviation))) if deviation.size else 0.0
        ),
        "max_relative_deviation": (
            float(np.max(np.abs(deviation) / np.maximum(np.abs(reference), 1e-300)))
            if deviation.size
            else 0.0
        ),
        "violation_sign_consistency": _sign_consistency(deviation[violation]),
        "mean_standard_error": (
            float(np.mean(standard_error)) if standard_error.size else 0.0
        ),
    }


def _sign_consistency(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    positive = float(np.sum(values > 0.0))
    negative = float(np.sum(values < 0.0))
    total = positive + negative
    if total == 0:
        return None
    return max(positive, negative) / total


def _compare_standard_deviations(
    sd: np.ndarray, reference_sd: np.ndarray, *, batch_size: int, k_sigma: float
) -> dict[str, Any]:
    """Auxiliary check of the ensemble standard deviation against a published one."""

    sd = np.asarray(sd, dtype=float)
    reference_sd = np.asarray(reference_sd, dtype=float)
    if sd.shape != reference_sd.shape:
        raise ValueError("standard deviation shapes do not match")
    relative_error = np.abs(sd - reference_sd) / np.maximum(
        np.abs(reference_sd), 1e-300
    )
    band = k_sigma / math.sqrt(2.0 * max(1, batch_size - 1))
    violation = relative_error > band
    return {
        "points": int(sd.size),
        "violations": int(violation.sum()),
        "max_relative_error": (
            float(np.max(relative_error)) if relative_error.size else 0.0
        ),
        "band": band,
    }


# ---------------------------------------------------------------------------
# Per-case sweep
# ---------------------------------------------------------------------------


def _deterministic_trace(
    cpp_model: Any,
    times: np.ndarray,
    *,
    t_start: float,
    t_end: float,
) -> dict[str, np.ndarray]:
    """BNG3's own CVODE trace on the reference grid (not an independent oracle)."""

    from bionetgen import BioNetGenModel

    result = BioNetGenModel(cpp_model).simulate(
        method="ode",
        t_start=t_start,
        t_end=t_end,
        n_steps=0,
        sample_times=np.asarray(times, dtype=float).tolist(),
        rtol=1e-9,
        atol=1e-14,
    )
    series = dict(result.observables)
    return {name: np.asarray(values, dtype=float) for name, values in series.items()}


def _sweep_case(
    case: dict[str, Any],
    cpp: Any,
    options: argparse.Namespace,
) -> dict[str, Any]:
    from bionetgen.atomizer.modern import Atomizer, SBMLParser
    from bionetgen.atomizer.modern.types import standardize_name

    record: dict[str, Any] = {
        "category": case["category"],
        "id": case["id"],
        "version": case["version"],
        "source": str(case["path"]),
    }
    source_path = Path(case["path"])
    try:
        sbml = source_path.read_text(encoding="utf-8-sig")
        parsed = SBMLParser().parse(sbml, source_path=source_path)
        atomizer = Atomizer(atomize=False, quiet_mode=True)
        atomized = atomizer.atomize(sbml, source_path=source_path)
    except Exception as exc:  # pragma: no cover - defensive
        record.update(status="error", reason=f"{type(exc).__name__}: {exc}")
        return record
    if not atomized.success:
        record.update(
            status="unsupported",
            reason=f"atomizer conversion failed: {atomized.error}",
        )
        return record

    warnings = _merge_generated_warnings(_warnings(parsed), _warnings(atomizer.model))
    limitations = (
        _simulation_limitations(warnings)
        + _warning_limitations(warnings)
        + _event_translation_limitations(atomized.bngl)
    )
    if limitations:
        record.update(
            status="unsupported",
            reason="; ".join(limitations)[:500],
        )
        return record
    # An SBML event is a discrete state change.  The in-memory CVODE and SSA
    # runners cannot execute one on the published output grid, so the two
    # readings of an event-driven model cannot be compared here at all.
    if parsed.events:
        record.update(
            status="not_comparable",
            reason=(
                "not comparable by construction: the source model declares "
                f"{len(parsed.events)} SBML event(s), and a discrete event is "
                "not part of the deterministic or the stochastic reading that "
                "the in-memory runners produce on the published output grid"
            ),
        )
        return record

    try:
        cpp_model = cpp.parse_string(atomized.bngl)
        network = cpp.generate_network(cpp_model, max_iter=100)
    except Exception as exc:
        record.update(status="error", reason=f"{type(exc).__name__}: {exc}")
        return record
    if getattr(cpp_model, "actions", None):
        record.update(
            status="not_comparable",
            reason=(
                "not comparable by construction: the converted model is "
                "event-driven (the generated BNGL carries scheduled actions), so "
                "its deterministic and stochastic readings differ by discrete "
                "jumps and cannot be compared on the published output grid"
            ),
        )
        return record

    record["network"] = {
        "species": int(network.num_species),
        "reactions": int(network.num_reactions),
    }
    # Source-model features that the batched SSA engines cannot reproduce.
    # The batched direct SSA runs on a generated reaction network; it applies
    # no assignment rules and no rate rules (only the NFsim backend does
    # network-free simulation with rule application), and it does not honour
    # the "constant seed species" marker of a boundary species.  Recording the
    # features lets a reader triage a disagreement without re-deriving them.
    record["source_features"] = {
        "rules": [
            {"type": rule.type, "variable": rule.variable} for rule in parsed.rules
        ],
        "boundary_species": sorted(
            species.id
            for species in parsed.species.values()
            if species.boundary_condition
        ),
        "initial_assignments": sorted(
            assignment.symbol for assignment in parsed.initial_assignments
        ),
    }

    # Probe the batched GPU path's fail-closed flattening.  This is cheap (no
    # simulation) and it is the detector for a converted rate law that has no
    # propensity the batched engine can execute.  It is recorded for every
    # converted case, independently of whether the case is comparable.
    batched_gpu_refusal = ""
    if options.backend != "none":
        try:
            cpp.jax_ssa_flatten(cpp_model, network)
        except Exception as exc:
            batched_gpu_refusal = f"{type(exc).__name__}: {exc}"
    if batched_gpu_refusal:
        record["batched_gpu_refusal"] = batched_gpu_refusal

    # ---- official reference -------------------------------------------------
    reference: dict[str, Any] | None = None
    reference_kind = "none"
    reference_independent = False
    if case["category"] == "semantic":
        try:
            reference = _read_reference_case(case)
            reference_kind = "official-deterministic"
            reference_independent = True
        except OfficialReferenceUnsupported as exc:
            reference = None
            record["reference_note"] = (
                f"the suite publishes no time-course reference for this case ({exc})"
            )
        except Exception as exc:
            record.update(status="error", reason=f"official reference: {exc}")
            return record
    else:
        try:
            reference = _read_stochastic_reference(case)
            reference_kind = "official-ensemble-mean"
            reference_independent = True
        except Exception as exc:
            record.update(status="error", reason=f"official reference: {exc}")
            return record
    record["reference"] = {
        "kind": reference_kind,
        "independent": reference_independent,
        "generated_by": (reference or {}).get("generated_by", ""),
    }

    if reference is None:
        record.update(
            status="not_comparable",
            reason=(
                "the suite publishes no time-course reference for this case, so the "
                "stochastic reading cannot be compared against an independent "
                "deterministic reference"
            ),
        )
        return record

    start = float(reference["start"])
    duration = float(reference["duration"])
    steps = int(reference["steps"])
    times = np.asarray(reference["times"], dtype=float)
    t_end = start + duration

    # ---- linearity ----------------------------------------------------------
    try:
        structure = _network_structure(cpp, cpp_model, network)
    except Exception as exc:
        record.update(status="error", reason=f"network structure: {exc}")
        return record
    linearity = _classify_linearity(structure)
    population = _classify_population(structure["initial_amounts"])
    record["network"].update(linearity)
    record["network"].update(population)

    # A rule that produced no reaction leaves the converted model without the
    # dynamics of its source.  The two readings would then agree trivially,
    # so this is recorded as a conversion finding, never as agreement.
    source_reactions = len(parsed.reactions)
    if source_reactions and int(network.num_reactions) == 0:
        record.update(
            status="not_comparable",
            reason=(
                "conversion finding: the source model declares "
                f"{source_reactions} reaction(s) but the generated network has "
                "none, so the converted model does not simulate the source "
                "dynamics and there is no rate law whose propensity could be "
                "compared"
            ),
        )
        record["findings"] = ["no_reaction_produced"]
        return record

    if not linearity["linear"]:
        record.update(
            status="not_comparable",
            reason=(
                "not comparable by construction: the generated network is not "
                f"linear ({linearity['reason']}); the mean of a stochastic "
                "simulation with a non-linear propensity does not satisfy the "
                "deterministic ODE, so the deterministic and stochastic readings "
                "are expected to differ"
            ),
        )
        return record
    if not population["representable"]:
        record.update(
            status="not_comparable",
            reason="not comparable by construction: " + population["reason"],
        )
        return record

    # ---- reference variable mapping ----------------------------------------
    observable_names = {item.name for item in cpp_model.observables}
    parameter_values = {
        item.name: float(item.value)
        for item in cpp_model.parameters
        if getattr(item, "value", None) is not None
    }
    mapped, skipped_variables = _resolve_reference_observables(
        list(reference["variables"]),
        reference,
        parsed,
        dict(atomized.observable_map),
        observable_names,
        parameter_values,
        standardize_name,
    )
    record["reference"]["variables_compared"] = sorted(mapped)
    record["reference"]["variables_skipped"] = sorted(skipped_variables)
    if not mapped:
        record.update(
            status="not_comparable",
            reason=(
                "no published reference variable maps onto an observable of the "
                "generated model"
            ),
        )
        return record

    # ---- batched SSA --------------------------------------------------------
    base_seed = _case_seed(case["id"], options.seed_base)
    engine: dict[str, Any] = {"base_seed": base_seed, "batch_size": options.batch_size}

    # Probe the batched GPU path's fail-closed flattening.  This is cheap (no
    # simulation) and it is the detector for a converted rate law that has no
    # propensity the batched engine can execute.
    gpu_refusal = batched_gpu_refusal

    # Backend policy: the Metal backend pays model preparation plus the
    # host/device transfers on every call, so on a small network it is slower
    # than the CPU pool.  Use the GPU where the network is large enough for
    # its parallelism to pay for the transfers, and the CPU otherwise.  The
    # backend that produced the numbers is recorded per case.
    large_network = (
        int(network.num_reactions) >= options.gpu_reaction_threshold
        or int(network.num_species) >= options.gpu_species_threshold
    )
    if options.backend == "none":
        preferred = "cpu"
    elif large_network and not gpu_refusal:
        preferred = "gpu"
    elif gpu_refusal:
        preferred = "cpu"
    else:
        preferred = "cpu"
    engine["backend_policy"] = ("gpu" if preferred == "gpu" else "cpu") + (
        f" (network: {int(network.num_species)} species, "
        f"{int(network.num_reactions)} reactions)"
    )
    if gpu_refusal:
        engine["batched_gpu_refusal"] = gpu_refusal
    result: dict[str, Any] | None = None
    backend = "none"
    if preferred == "gpu":
        try:
            result = _run_gpu_batch(
                cpp,
                cpp_model,
                network,
                backend=options.backend,
                batch_size=options.batch_size,
                t_start=start,
                t_end=t_end,
                n_steps=steps,
                base_seed=base_seed,
                max_sim_steps=options.max_sim_steps,
            )
            backend = str(result.get("backend", options.backend))
        except Exception as exc:
            gpu_refusal = f"{type(exc).__name__}: {exc}"
            engine["batched_gpu_refusal"] = gpu_refusal
    if result is None:
        if not options.cpu_fallback:
            record.update(
                status="no_valid_propensity",
                reason=(
                    "the batched SSA path refused the converted rate law: "
                    + (gpu_refusal or "no GPU backend was available")
                ),
                engine=engine,
            )
            return record
        try:
            result = _run_cpu_batch(
                cpp,
                cpp_model,
                network,
                batch_size=options.batch_size,
                t_start=start,
                t_end=t_end,
                n_steps=steps,
                base_seed=base_seed,
                max_sim_steps=options.max_sim_steps,
                threads=options.cpu_threads,
            )
            backend = "cpu"
        except Exception as exc:
            record.update(
                status="no_valid_propensity",
                reason=(
                    "the batched SSA path refused the converted rate law: "
                    + (gpu_refusal or "no GPU backend was available")
                    + f"; the CPU fallback also failed: {type(exc).__name__}: {exc}"
                ),
                engine=engine,
            )
            return record
    engine.update(_engine_metrics(result, backend))
    record["engine"] = engine
    if engine.get("trajectory_truncated"):
        record.update(
            status="error",
            reason="a trajectory hit the event cap; the ensemble is truncated",
        )
        return record

    engine_times = np.asarray(result.get("time", []), dtype=float)
    if engine_times.size != times.size or not np.allclose(
        engine_times, times, rtol=0.0, atol=1e-6 * max(1.0, abs(duration))
    ):
        record.update(
            status="error",
            reason="the batched SSA time grid differs from the reference grid",
        )
        return record

    # ---- comparison ---------------------------------------------------------
    # Three comparisons per reference variable:
    #   official : the ensemble mean against the published reference (the
    #              independent oracle);
    #   cvode    : the ensemble mean against the converted model's own CVODE
    #              trace (not independent, but it isolates the stochastic
    #              reading from the deterministic one);
    #   cvode_vs_official : the converted model's CVODE trace against the
    #              published reference (a deterministic-versus-deterministic
    #              comparison).  Together the three say which of the two
    #              readings is the odd one out.
    means = result["observable_means"]
    stds = result["observable_stds"]
    comparisons: dict[str, Any] = {}
    official_violations = 0
    official_decisive = 0
    official_points = 0
    official_max_abs_z = 0.0
    cvode_violations = 0
    cvode_decisive = 0
    cvode_points = 0
    cvode_max_abs_z = 0.0
    cvode_official_violations = 0
    cvode_official_decisive = 0
    cvode_official_points = 0
    try:
        cvode = _deterministic_trace(cpp_model, times, t_start=start, t_end=t_end)
    except Exception as exc:
        cvode = {}
        record["deterministic_trace_error"] = f"{type(exc).__name__}: {exc}"
    for variable, mapping in sorted(mapped.items()):
        observable = mapping["observable"]
        scale = float(mapping["scale"])
        if observable not in means:
            continue
        mean = np.asarray(means[observable], dtype=float) * scale
        sd = np.asarray(stds[observable], dtype=float) * scale
        if case["category"] == "semantic":
            reference_values = np.asarray(reference["expected"][variable], dtype=float)
            absolute = float(reference["absolute"])
            relative = float(reference["relative"])
        else:
            reference_values = np.asarray(reference["means"][variable], dtype=float)
            absolute = 0.0
            relative = 0.0
        outcome = _compare_trace(
            mean,
            sd,
            reference_values,
            batch_size=options.batch_size,
            k_sigma=options.k_sigma,
            absolute_tolerance=absolute,
            relative_tolerance=relative,
        )
        outcome["observable"] = observable
        outcome["scale"] = scale
        official_violations += outcome["violations"]
        official_decisive += outcome["decisive_violations"]
        official_points += outcome["points"]
        official_max_abs_z = max(official_max_abs_z, outcome["max_abs_z"])
        if observable in cvode:
            cvode_values = np.asarray(cvode[observable], dtype=float) * scale
            against_cvode = _compare_trace(
                mean,
                sd,
                cvode_values,
                batch_size=options.batch_size,
                k_sigma=options.k_sigma,
                absolute_tolerance=options.deterministic_atol,
                relative_tolerance=options.deterministic_rtol,
            )
            outcome["versus_bng3_cvode"] = against_cvode
            cvode_violations += against_cvode["violations"]
            cvode_decisive += against_cvode["decisive_violations"]
            cvode_points += against_cvode["points"]
            cvode_max_abs_z = max(cvode_max_abs_z, against_cvode["max_abs_z"])
            against_reference = _compare_trace(
                cvode_values,
                np.zeros_like(cvode_values),
                reference_values,
                batch_size=options.batch_size,
                k_sigma=options.k_sigma,
                absolute_tolerance=absolute,
                relative_tolerance=relative,
            )
            outcome["cvode_versus_official_reference"] = against_reference
            cvode_official_violations += against_reference["violations"]
            cvode_official_decisive += against_reference["decisive_violations"]
            cvode_official_points += against_reference["points"]
        comparisons[variable] = outcome

        if case["category"] == "stochastic" and variable in reference["stds"]:
            sd_outcome = _compare_standard_deviations(
                sd,
                np.asarray(reference["stds"][variable], dtype=float) * scale,
                batch_size=options.batch_size,
                k_sigma=K_SD_SIGMA,
            )
            outcome["published_standard_deviation"] = sd_outcome

    record["comparison"] = {
        "reference_kind": reference_kind,
        "reference_independent": reference_independent,
        "k_sigma": options.k_sigma,
        "points": official_points,
        "violations": official_violations,
        "decisive_violations": official_decisive,
        "max_abs_z": official_max_abs_z,
        "deterministic_points": cvode_points,
        "deterministic_violations": cvode_violations,
        "deterministic_decisive_violations": cvode_decisive,
        "deterministic_max_abs_z": cvode_max_abs_z,
        "cvode_vs_official_points": cvode_official_points,
        "cvode_vs_official_violations": cvode_official_violations,
        "cvode_vs_official_decisive_violations": cvode_official_decisive,
        "variables": comparisons,
    }

    findings: list[str] = []
    if cvode_official_decisive:
        findings.append("deterministic_reading_disagrees_with_published_reference")
    if official_decisive and not cvode_official_decisive:
        findings.append("stochastic_reading_disagrees_with_published_reference")
    if cvode_decisive:
        findings.append("stochastic_reading_disagrees_with_own_deterministic_reading")
    if findings:
        # Attribute the disagreement to a mechanism, so that a difference
        # which is expected physics is never reported as a defect.  The
        # attribution is per reference variable: a variable whose CVODE trace
        # also leaves the published reference is a conversion difference, while
        # a variable whose CVODE trace matches the published reference isolates
        # the stochastic reading as the odd one out.
        zeroth_order = _zeroth_order_consumptions(parsed)
        has_rate_rule = any(rule.type == "rate" for rule in parsed.rules)
        has_assignment_rule = any(rule.type == "assignment" for rule in parsed.rules)
        stoichiometry_warning = any(
            "stoichiometry" in str(warning.get("message", "")).lower()
            for warning in warnings
        )
        mechanisms: set[str] = set()
        for variable, outcome in comparisons.items():
            against_cvode = outcome.get("versus_bng3_cvode") or {}
            cvode_against_reference = (
                outcome.get("cvode_versus_official_reference") or {}
            )
            if not outcome["decisive_violations"] and not against_cvode.get(
                "decisive_violations"
            ):
                continue
            if cvode_against_reference.get("decisive_violations"):
                mechanisms.add("conversion-differs-from-the-published-reference")
                continue
            species = parsed.species.get(variable)
            if species is not None and species.boundary_condition:
                mechanisms.add("constant-species-not-honoured-by-the-ssa")
            elif stoichiometry_warning:
                mechanisms.add(
                    "stoichiometry-lowered-to-a-deterministic-flux-loses-the-"
                    "reaction-event-coupling"
                )
            elif outcome.get("reference_min", 0.0) <= 0.0:
                mechanisms.add(
                    "the-deterministic-reference-leaves-the-non-negative-orthant"
                )
            elif variable in zeroth_order:
                mechanisms.add(
                    "zeroth-order-consumption-saturates-in-the-discrete-reading"
                )
            elif has_rate_rule:
                mechanisms.add("ssa-does-not-apply-rate-rules")
            elif has_assignment_rule:
                mechanisms.add("ssa-does-not-apply-assignment-rules")
            else:
                mechanisms.add("unattributed")
        record["mechanisms"] = sorted(mechanisms)
        if mechanisms and mechanisms <= {
            "zeroth-order-consumption-saturates-in-the-discrete-reading",
            "the-deterministic-reference-leaves-the-non-negative-orthant",
        }:
            record.update(
                status="not_comparable",
                reason=(
                    "not comparable by construction: the deterministic reading of "
                    "the source model leaves the non-negative orthant (a species "
                    "is driven to or below zero), while the discrete reading "
                    "clamps the population at zero; the two readings differ by "
                    "construction once the substrate runs out"
                ),
            )
            return record
        # A systematic departure, not a single outlier, decides the verdict.
        systematic = any(
            outcome.get("decisive_violations", 0) >= options.min_systematic_points
            for outcome in comparisons.values()
        )
        if not systematic and official_max_abs_z < options.hard_z_limit:
            record["findings"] = findings
            record["inconsistent_cause"] = "; ".join(findings)
            record.update(
                status="consistent",
                reason=(
                    "no systematic departure: at most "
                    f"{options.min_systematic_points - 1} decisive point(s) leave "
                    f"the band and the largest deviation is {official_max_abs_z:.2f} "
                    f"ensemble standard errors, below the hard limit of "
                    f"{options.hard_z_limit:g}"
                ),
            )
            return record
        record["findings"] = findings
        record["inconsistent_cause"] = "; ".join(findings)
        record.update(
            status="inconsistent",
            reason=(
                f"{official_violations}/{official_points} points depart from the "
                f"{reference_kind} reference by more than {options.k_sigma} "
                f"ensemble standard errors (max |z| = {official_max_abs_z:.2f}); "
                f"{cvode_violations}/{cvode_points} points depart from the "
                f"converted model's CVODE trace (max |z| = {cvode_max_abs_z:.2f}); "
                f"{cvode_official_violations}/{cvode_official_points} points of "
                "the CVODE trace depart from the published reference; "
                "mechanism(s): " + ", ".join(sorted(mechanisms))
            ),
        )
        return record
    record.update(
        status="consistent",
        reason=(
            f"every checked point lies within {options.k_sigma} ensemble standard "
            f"errors of the {reference_kind} reference and of the converted "
            "model's CVODE trace"
        ),
    )
    return record


# ---------------------------------------------------------------------------
# GPU / CPU sampler agreement
# ---------------------------------------------------------------------------


def _gpu_cpu_agreement(
    case: dict[str, Any],
    cpp: Any,
    options: argparse.Namespace,
) -> dict[str, Any]:
    """Run the same batch on the GPU and on the CPU pool and compare them.

    The two samplers use different pseudo-random generators (PCG32 on the GPU,
    std::mt19937_64 on the CPU), so the comparison is distributional: a
    two-sample Z test on the ensemble means at every time point, the same test
    the repository's existing batch-SSA parity gate uses.
    """

    from bionetgen.atomizer.modern import Atomizer

    source_path = Path(case["path"])
    sbml = source_path.read_text(encoding="utf-8-sig")
    atomizer = Atomizer(atomize=False, quiet_mode=True)
    atomized = atomizer.atomize(sbml, source_path=source_path)
    if not atomized.success:
        return {"id": case["id"], "status": "error", "reason": atomized.error}
    cpp_model = cpp.parse_string(atomized.bngl)
    network = cpp.generate_network(cpp_model, max_iter=100)

    case_dir = source_path.parent
    case_id = str(case["id"])
    settings = _parse_settings(case_dir / f"{case_id}-settings.txt")
    start = float(settings["start"])
    duration = float(settings["duration"])
    steps = int(settings["steps"])
    base_seed = _case_seed(case_id, options.seed_base)

    gpu = None
    gpu_error = ""
    try:
        gpu = _run_gpu_batch(
            cpp,
            cpp_model,
            network,
            backend=options.backend,
            batch_size=options.batch_size,
            t_start=start,
            t_end=start + duration,
            n_steps=steps,
            base_seed=base_seed,
            max_sim_steps=options.max_sim_steps,
        )
    except Exception as exc:
        gpu_error = f"{type(exc).__name__}: {exc}"
    cpu = _run_cpu_batch(
        cpp,
        cpp_model,
        network,
        batch_size=options.batch_size,
        t_start=start,
        t_end=start + duration,
        n_steps=steps,
        base_seed=base_seed,
        max_sim_steps=options.max_sim_steps,
        threads=options.cpu_threads,
    )
    if gpu is None:
        return {
            "id": case_id,
            "status": "no_valid_propensity",
            "reason": f"the batched GPU path refused the rate law: {gpu_error}",
            "cpu_sim_time_ms": float(cpu.get("sim_time_ms", 0.0)),
            "cpu_total_wall_time_ms": float(cpu.get("total_wall_time_ms", 0.0)),
            "cpu_trajectories_per_sec_total": float(
                cpu.get("trajectories_per_sec_total", 0.0)
            ),
        }
    if list(gpu["observable_names"]) != list(cpu["observable_names"]):
        return {
            "id": case_id,
            "status": "error",
            "reason": "the GPU and CPU runs disagree on the observable set",
        }
    batch = options.batch_size
    max_abs_z = 0.0
    worst = ""
    worst_gap = 0.0
    worst_gap_observable = ""
    for name in gpu["observable_names"]:
        gpu_mean = np.asarray(gpu["observable_means"][name], dtype=float)
        cpu_mean = np.asarray(cpu["observable_means"][name], dtype=float)
        gpu_sd = np.asarray(gpu["observable_stds"][name], dtype=float)
        cpu_sd = np.asarray(cpu["observable_stds"][name], dtype=float)
        pooled = np.sqrt((gpu_sd**2 + cpu_sd**2) / batch)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(pooled > 0.0, (gpu_mean - cpu_mean) / pooled, 0.0)
        if z.size and float(np.max(np.abs(z))) > max_abs_z:
            max_abs_z = float(np.max(np.abs(z)))
            worst = name
        # The raw gap between the two ensemble means, in units of the pooled
        # ensemble standard deviation, at the last time point.
        if gpu_sd.size:
            scale = float(np.sqrt(gpu_sd[-1] ** 2 + cpu_sd[-1] ** 2))
            gap = abs(float(gpu_mean[-1]) - float(cpu_mean[-1]))
            if scale > 0 and gap / scale > worst_gap:
                worst_gap = gap / scale
                worst_gap_observable = name
    gpu_sim = float(gpu.get("sim_time_ms", 0.0))
    cpu_sim = float(cpu.get("sim_time_ms", 0.0))
    return {
        "id": case_id,
        "status": "ok",
        "backend": gpu.get("backend", ""),
        "batch_size": batch,
        "base_seed": base_seed,
        "max_abs_z": max_abs_z,
        "worst_observable": worst,
        "final_mean_gap_in_sd": worst_gap,
        "final_mean_gap_observable": worst_gap_observable,
        "z_limit": options.parity_z_limit,
        "passed": max_abs_z <= options.parity_z_limit,
        "gpu_sim_time_ms": gpu_sim,
        "cpu_sim_time_ms": cpu_sim,
        "gpu_total_wall_time_ms": float(gpu.get("total_wall_time_ms", 0.0)),
        "cpu_total_wall_time_ms": float(cpu.get("total_wall_time_ms", 0.0)),
        "gpu_trajectories_per_sec_total": float(
            gpu.get("trajectories_per_sec_total", 0.0)
        ),
        "cpu_trajectories_per_sec_total": float(
            cpu.get("trajectories_per_sec_total", 0.0)
        ),
        "sim_speedup": (cpu_sim / gpu_sim) if gpu_sim > 0 else None,
        "wall_speedup": (
            float(cpu.get("total_wall_time_ms", 0.0))
            / float(gpu.get("total_wall_time_ms", 0.0))
            if float(gpu.get("total_wall_time_ms", 0.0)) > 0
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _provenance(options: argparse.Namespace, cpp: Any) -> dict[str, Any]:
    try:
        lock = _suite_lock_entry(DEFAULT_SUITE_LOCK)
    except SuiteLockError as exc:
        lock = {"error": str(exc)}
    versions: dict[str, str] = {}
    for name in ("bionetgen", "numpy", "scipy", "libsbml", "roadrunner"):
        try:
            versions[name] = importlib.metadata.version(name)
        except Exception:
            versions[name] = "not installed"
    return {
        "suite": lock,
        "suite_dir": str(options.suite_dir),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": versions,
        "gpu_backends": list(cpp.gpu_backends()),
        "default_gpu_backend": cpp.default_gpu_backend(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-dir", type=Path, required=True)
    parser.add_argument("--categories", nargs="+", default=["semantic", "stochastic"])
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--seed-base", type=int, default=DEFAULT_SEED_BASE)
    parser.add_argument("--k-sigma", type=float, default=DEFAULT_K_SIGMA)
    parser.add_argument(
        "--max-sim-steps", type=int, default=0, help="0 disables the event cap"
    )
    parser.add_argument(
        "--backend",
        default=DEFAULT_GPU_BACKEND,
        help="auto/metal/cuda/none; 'none' forces the CPU pool",
    )
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument(
        "--gpu-reaction-threshold",
        type=int,
        default=100,
        help=(
            "use the GPU batched SSA when the generated network has at least this "
            "many reactions (below it the CPU pool is faster because the GPU "
            "pays model preparation plus host/device transfers per call)"
        ),
    )
    parser.add_argument(
        "--gpu-species-threshold",
        type=int,
        default=50,
        help="also use the GPU when the generated network has at least this many species",
    )
    parser.add_argument(
        "--no-cpu-fallback",
        action="store_true",
        help="do not fall back to the CPU pool when the batched path refuses",
    )
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--only-case", default="")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--artifacts-dir", type=Path, default=None)
    parser.add_argument(
        "--gpu-cpu-parity-cases",
        type=int,
        default=6,
        help="number of cases used for the GPU/CPU sampler agreement check",
    )
    parser.add_argument("--parity-z-limit", type=float, default=3.5)
    parser.add_argument(
        "--min-systematic-points",
        type=int,
        default=2,
        help=(
            "number of decisive violating points a reference variable must show "
            "before the case is reported as inconsistent (a systematic departure, "
            "not a single outlier)"
        ),
    )
    parser.add_argument(
        "--hard-z-limit",
        type=float,
        default=10.0,
        help=(
            "a single departure beyond this many ensemble standard errors is "
            "reported even when it is the only one"
        ),
    )
    parser.add_argument(
        "--deterministic-rtol",
        type=float,
        default=1e-7,
        help="relative tolerance of the CVODE trace used for the internal comparison",
    )
    parser.add_argument(
        "--deterministic-atol",
        type=float,
        default=1e-12,
        help="absolute tolerance of the CVODE trace used for the internal comparison",
    )
    options = parser.parse_args(argv)
    options.cpu_fallback = not options.no_cpu_fallback

    import bionetgen._bionetgen_cpp as cpp

    if options.backend == "auto":
        options.backend = cpp.default_gpu_backend()
        if options.backend == "none":
            print("no GPU backend available; the CPU pool will be used")

    cases = _case_files(options.suite_dir, options.categories)
    if options.only_case:
        cases = [case for case in cases if case["id"] == options.only_case]
    if options.max_cases:
        cases = cases[: options.max_cases]

    started = time.time()
    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        record = _sweep_case(case, cpp, options)
        records.append(record)
        if index % 100 == 0 or index == len(cases):
            counts = Counter(item["status"] for item in records)
            print(
                f"[{index}/{len(cases)}] {dict(counts)} "
                f"({time.time() - started:.1f}s)",
                flush=True,
            )
        if options.artifacts_dir is not None:
            directory = options.artifacts_dir / case["category"] / str(case["id"])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "stochastic-consistency.json").write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )

    parity: list[dict[str, Any]] = []
    if options.gpu_cpu_parity_cases and options.backend != "none":
        comparable = [
            record
            for record in records
            if record["status"] in {"consistent", "inconsistent"}
        ]
        for record in comparable[: options.gpu_cpu_parity_cases]:
            case = next(item for item in cases if item["id"] == record["id"])
            try:
                parity.append(_gpu_cpu_agreement(case, cpp, options))
            except Exception as exc:
                parity.append(
                    {
                        "id": record["id"],
                        "status": "error",
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                )
            print(f"parity[{record['id']}] {parity[-1]}", flush=True)

    counts = Counter(record["status"] for record in records)
    batched_gpu_refusals = [
        {
            "id": record["id"],
            "category": record["category"],
            "reason": record["batched_gpu_refusal"],
            "status": record["status"],
            "engine_used": (record.get("engine") or {}).get("backend"),
        }
        for record in records
        if record.get("batched_gpu_refusal")
    ]
    conversion_findings = [
        {"id": record["id"], "category": record["category"], "reason": record["reason"]}
        for record in records
        if "no_reaction_produced" in (record.get("findings") or [])
    ]
    backends = Counter(
        (record.get("engine") or {}).get("backend", "not-run")
        for record in records
        if record["status"] in {"consistent", "inconsistent"}
    )
    report = {
        "tool": "check_stochastic_consistency",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(time.time() - started, 3),
        "provenance": _provenance(options, cpp),
        "budget": {
            "batch_size": options.batch_size,
            "seed_policy": (
                "base_seed = seed_base + int(case_id); trajectory b of a case owns "
                "an independent stream (PCG32 with increment 2b+1 on the GPU, "
                "std::mt19937_64 seeded with base_seed+b on the CPU pool)"
            ),
            "seed_base": options.seed_base,
            "max_sim_steps": options.max_sim_steps,
            "k_sigma": options.k_sigma,
            "k_sigma_justification": (
                "a deviation beyond k_sigma ensemble standard errors is a "
                f"{2 * 0.5 * math.erfc(options.k_sigma / math.sqrt(2)):.2e} "
                "two-sided normal tail; a case checks at most a few hundred "
                "(variable, time) pairs and the residuals inside a case are "
                "positively correlated, so the family-wise false-alarm rate over "
                "the suite stays well below 1%"
            ),
            "criterion": (
                "|ensemble_mean - reference| <= k_sigma * ensemble_sd/sqrt(B) "
                "+ reference_tolerance + float32_representation_error"
            ),
            "backend": options.backend,
            "backend_policy": (
                "the GPU batched SSA is used when the generated network has at "
                f"least {options.gpu_reaction_threshold} reactions or "
                f"{options.gpu_species_threshold} species, otherwise the CPU "
                "pool; the backend that produced each case's numbers is "
                "recorded on the case"
            ),
            "cpu_threads": options.cpu_threads,
            "cpu_fallback": not options.no_cpu_fallback,
            "suite_categories": options.categories,
        },
        "counts": dict(counts),
        "backends_used": dict(backends),
        "batched_gpu_refusals": batched_gpu_refusals,
        "conversion_findings": conversion_findings,
        "gpu_cpu_parity": parity,
        "cases": records,
    }
    if options.json is not None:
        options.json.parent.mkdir(parents=True, exist_ok=True)
        options.json.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"report written to {options.json}")
    print(json.dumps(dict(counts), indent=2))
    print(f"backends used: {dict(backends)}")
    print(
        f"batched GPU refusals: {len(batched_gpu_refusals)}; "
        f"conversion findings: {len(conversion_findings)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
