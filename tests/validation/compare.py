"""Comparators for differential validation.

One module, every comparison. Consolidates and corrects the logic that was
scattered across scripts/validate_*.py.

Key correctness fix over the old scripts: the .net comparator keys reactions by
their *species strings*, not by species indices. Two networks that are identical
up to species ordering must compare equal; an extra or unmerged reaction must
compare unequal. This is what detects the over-count (blbr +26, cBNGL +2):
the test network carries reaction tuples that the reference (Perl) merged.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s.strip())


# --------------------------------------------------------------------------- #
# .net parsing
# --------------------------------------------------------------------------- #

@dataclass
class Network:
    """A parsed reaction network, comparison-ready."""

    # species index (as written) -> canonical species string
    species_by_index: dict[int, str]
    # multiset of (sorted reactant strings, sorted product strings, rate)
    reaction_multiset: Counter

    @property
    def n_species(self) -> int:
        return len(self.species_by_index)

    @property
    def n_reactions(self) -> int:
        return sum(self.reaction_multiset.values())


def parse_net(path: str | Path) -> Network | None:
    """Parse a BNG .net file into a comparison-ready Network.

    Species block lines:    <idx> <species_string> <conc> [labels]
    Reaction block lines:    <idx> <r1,r2,...> <p1,p2,...> <rate> [annotations]
    Reactant/product fields are comma-separated 1-based species indices.
    """
    path = Path(path)
    if not path.exists():
        return None

    species: dict[int, str] = {}
    raw_reactions: list[tuple[list[int], list[int], str]] = []
    section = None

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("begin "):
            section = stripped[len("begin "):].strip()
            continue
        if stripped.startswith("end "):
            section = None
            continue

        if section == "species":
            parts = _norm(stripped).split(" ")
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[0])
            except ValueError:
                continue
            species[idx] = parts[1]

        elif section == "reactions":
            parts = _norm(stripped).split(" ")
            if len(parts) < 4:
                continue
            try:
                # parts[0] is the reaction index (order-dependent; ignored)
                reactants = [int(x) for x in parts[1].split(",") if x and x != "0"]
                products = [int(x) for x in parts[2].split(",") if x and x != "0"]
            except ValueError:
                continue
            rate = parts[3]
            raw_reactions.append((reactants, products, rate))

    if not species and not raw_reactions:
        return None

    # Translate reactions to species-string keys so ordering is irrelevant.
    multiset: Counter = Counter()
    for reactants, products, rate in raw_reactions:
        try:
            r_strs = tuple(sorted(species[i] for i in reactants))
            p_strs = tuple(sorted(species[i] for i in products))
        except KeyError:
            # Reaction references a species index not in the species block;
            # fall back to raw indices so the row still participates.
            r_strs = tuple(f"?{i}" for i in sorted(reactants))
            p_strs = tuple(f"?{i}" for i in sorted(products))
        multiset[(r_strs, p_strs, _norm(rate))] += 1

    return Network(species_by_index=species, reaction_multiset=multiset)


@dataclass
class NetDiff:
    ok: bool
    n_species_ref: int
    n_species_test: int
    n_reactions_ref: int
    n_reactions_test: int
    species_only_ref: set[str]
    species_only_test: set[str]
    reactions_only_ref: list
    reactions_only_test: list

    def summary(self) -> str:
        lines = [
            f"species:   ref={self.n_species_ref} test={self.n_species_test}",
            f"reactions: ref={self.n_reactions_ref} test={self.n_reactions_test} "
            f"(delta={self.n_reactions_test - self.n_reactions_ref:+d})",
        ]
        if self.species_only_ref:
            lines.append(f"  species only in ref ({len(self.species_only_ref)}): "
                         + ", ".join(sorted(self.species_only_ref)[:5]))
        if self.species_only_test:
            lines.append(f"  species only in test ({len(self.species_only_test)}): "
                         + ", ".join(sorted(self.species_only_test)[:5]))
        if self.reactions_only_test:
            lines.append(f"  reactions only in test ({len(self.reactions_only_test)}) "
                         "— candidates for the over-count / failed merge:")
            for r, p, rate in self.reactions_only_test[:5]:
                lines.append(f"    {' + '.join(r)} -> {' + '.join(p)}  [{rate}]")
        if self.reactions_only_ref:
            lines.append(f"  reactions only in ref ({len(self.reactions_only_ref)}):")
            for r, p, rate in self.reactions_only_ref[:5]:
                lines.append(f"    {' + '.join(r)} -> {' + '.join(p)}  [{rate}]")
        return "\n".join(lines)


def compare_net(ref: Network, test: Network, *, compare_rates: bool = True) -> NetDiff:
    """Set-compare two networks by species string and reaction tuple.

    compare_rates=False drops the rate field from reaction keys (useful when an
    engine writes rates in a different but equivalent textual form). Keep it True
    by default — the over-count is detectable on topology alone.
    """
    species_ref = set(ref.species_by_index.values())
    species_test = set(test.species_by_index.values())

    if compare_rates:
        rxn_ref = ref.reaction_multiset
        rxn_test = test.reaction_multiset
    else:
        rxn_ref = Counter((r, p) for (r, p, _), n in ref.reaction_multiset.items()
                          for _ in range(n))
        rxn_test = Counter((r, p) for (r, p, _), n in test.reaction_multiset.items()
                           for _ in range(n))

    only_ref = rxn_ref - rxn_test
    only_test = rxn_test - rxn_ref

    def _explode(counter):
        out = []
        for key, n in counter.items():
            r, p = key[0], key[1]
            rate = key[2] if len(key) > 2 else ""
            out.extend([(list(r), list(p), rate)] * n)
        return out

    ok = (species_ref == species_test) and (not only_ref) and (not only_test)
    return NetDiff(
        ok=ok,
        n_species_ref=ref.n_species,
        n_species_test=test.n_species,
        n_reactions_ref=ref.n_reactions,
        n_reactions_test=test.n_reactions,
        species_only_ref=species_ref - species_test,
        species_only_test=species_test - species_ref,
        reactions_only_ref=_explode(only_ref),
        reactions_only_test=_explode(only_test),
    )


# --------------------------------------------------------------------------- #
# .gdat / trajectory parsing
# --------------------------------------------------------------------------- #

def parse_gdat(path: str | Path) -> tuple[np.ndarray, list[str]] | tuple[None, None]:
    """Parse a .gdat/.cdat file into (data, columns). First column is time."""
    path = Path(path)
    if not path.exists():
        return None, None
    lines = path.read_text().splitlines()
    if not lines:
        return None, None
    header = lines[0].strip().lstrip("#").strip()
    columns = header.split()
    rows = []
    for line in lines[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([float(x) for x in line.split()])
    if not rows:
        return None, None
    return np.asarray(rows, dtype=float), columns


@dataclass
class TrajDiff:
    ok: bool
    max_rel_err: float
    max_rel_col: str
    l2_rel_err: float
    note: str = ""

    def summary(self) -> str:
        s = (f"max rel err = {self.max_rel_err:.3e} at '{self.max_rel_col}', "
             f"L2 rel err = {self.l2_rel_err:.3e}")
        return s if not self.note else f"{s} ({self.note})"


def compare_trajectories(
    ref: np.ndarray,
    ref_cols: list[str],
    test: np.ndarray,
    test_cols: list[str],
    *,
    rtol: float = 1e-6,
    atol: float = 1e-12,
) -> TrajDiff:
    """Compare two trajectories column-by-column on shared observables.

    Aligns on the common time grid (intersection of time points, exact match).
    Relative error uses max(|ref|, atol) in the denominator so near-zero
    observables don't blow up the metric.
    """
    common = [c for c in ref_cols if c in test_cols and c.lower() != "time"]
    if not common:
        return TrajDiff(False, np.inf, "", np.inf, "no shared observable columns")

    rt = ref[:, ref_cols.index("time")] if "time" in ref_cols else ref[:, 0]
    tt = test[:, test_cols.index("time")] if "time" in test_cols else test[:, 0]

    # Align on shared time points (tolerant match).
    ridx, tidx = _align_times(rt, tt)
    if len(ridx) < 2:
        return TrajDiff(False, np.inf, "", np.inf,
                        f"insufficient shared time points (ref={len(rt)}, test={len(tt)})")

    worst = 0.0
    worst_col = ""
    sq_sum = 0.0
    n = 0
    for c in common:
        rv = ref[ridx, ref_cols.index(c)]
        tv = test[tidx, test_cols.index(c)]
        denom = np.maximum(np.abs(rv), atol)
        rel = np.abs(tv - rv) / denom
        cmax = float(np.max(rel))
        if cmax > worst:
            worst, worst_col = cmax, c
        sq_sum += float(np.sum(rel ** 2))
        n += rel.size

    l2 = float(np.sqrt(sq_sum / max(n, 1)))
    ok = worst <= rtol
    return TrajDiff(ok=ok, max_rel_err=worst, max_rel_col=worst_col, l2_rel_err=l2)


def _align_times(a: np.ndarray, b: np.ndarray, tol: float = 1e-9):
    """Return index arrays into a and b for time points present in both."""
    ai, bi = [], []
    j = 0
    for i, ta in enumerate(a):
        while j < len(b) and b[j] < ta - tol:
            j += 1
        if j < len(b) and abs(b[j] - ta) <= tol + tol * abs(ta):
            ai.append(i)
            bi.append(j)
            j += 1
    return np.asarray(ai, dtype=int), np.asarray(bi, dtype=int)


# --------------------------------------------------------------------------- #
# Stochastic ensemble comparison (SSA / PLA / PSA / NF)
# --------------------------------------------------------------------------- #

@dataclass
class EnsembleDiff:
    ok: bool
    n_violations: int
    n_points_checked: int
    worst_z: float
    worst_col: str

    def summary(self) -> str:
        return (f"ensemble: {self.n_violations}/{self.n_points_checked} points outside "
                f"mean +/- 3 SE; worst |z|={self.worst_z:.2f} at '{self.worst_col}'")


def compare_stochastic(
    ref_runs: list[tuple[np.ndarray, list[str]]],
    test_runs: list[tuple[np.ndarray, list[str]]],
    *,
    n_sigma: float = 3.0,
    max_violation_frac: float = 0.02,
) -> EnsembleDiff:
    """Distributional comparison of two stochastic ensembles.

    For each shared observable at each shared time point, check that the test
    ensemble mean lies within ref_mean +/- n_sigma * SE(ref). Pass if the
    fraction of violating points is <= max_violation_frac (allows for the few
    tail points expected at 3 sigma over many checks).
    """
    rmean, rse, rcols, rt = _ensemble_stats(ref_runs)
    tmean, _, tcols, tt = _ensemble_stats(test_runs)
    if rmean is None or tmean is None:
        return EnsembleDiff(False, 0, 0, np.inf, "")

    common = [c for c in rcols if c in tcols and c.lower() != "time"]
    ridx, tidx = _align_times(rt, tt)
    if not common or len(ridx) < 2:
        return EnsembleDiff(False, 0, 0, np.inf, "")

    violations = 0
    checked = 0
    worst_z = 0.0
    worst_col = ""
    for c in common:
        rm = rmean[ridx, rcols.index(c)]
        rs = rse[ridx, rcols.index(c)]
        tm = tmean[tidx, tcols.index(c)]
        se = np.maximum(rs, 1e-12)
        z = np.abs(tm - rm) / se
        cz = float(np.max(z))
        if cz > worst_z:
            worst_z, worst_col = cz, c
        violations += int(np.sum(z > n_sigma))
        checked += z.size

    frac = violations / max(checked, 1)
    return EnsembleDiff(
        ok=frac <= max_violation_frac,
        n_violations=violations,
        n_points_checked=checked,
        worst_z=worst_z,
        worst_col=worst_col,
    )


def _ensemble_stats(runs: list[tuple[np.ndarray, list[str]]]):
    if not runs:
        return None, None, None, None
    cols = runs[0][1]
    time = runs[0][0][:, cols.index("time")] if "time" in cols else runs[0][0][:, 0]
    stack = np.stack([r[0] for r in runs], axis=0)  # (n_runs, n_t, n_col)
    mean = stack.mean(axis=0)
    se = stack.std(axis=0, ddof=1) / np.sqrt(stack.shape[0]) if stack.shape[0] > 1 else np.zeros_like(mean)
    return mean, se, cols, time


# --------------------------------------------------------------------------- #
# Export format checks
# --------------------------------------------------------------------------- #

def check_xml_wellformed(path: str | Path) -> tuple[bool, str]:
    import xml.etree.ElementTree as ET
    try:
        ET.parse(str(path))
        return True, "well-formed"
    except ET.ParseError as e:
        return False, f"XML parse error: {e}"


def check_sbml(path: str | Path) -> tuple[bool, str]:
    """Validate SBML with libsbml if available, else fall back to well-formed."""
    try:
        import libsbml  # type: ignore
    except ImportError:
        ok, msg = check_xml_wellformed(path)
        return ok, f"{msg} (libsbml absent; well-formedness only)"
    doc = libsbml.readSBML(str(path))
    n_err = doc.getNumErrors()
    serious = sum(
        1 for i in range(n_err)
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    )
    if serious:
        return False, f"{serious} SBML error(s); first: {doc.getError(0).getMessage()}"
    return True, f"valid SBML ({n_err} non-fatal notices)"
