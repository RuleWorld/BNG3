"""Statistical equivalence between two stochastic simulators.

An accelerator and a host do not produce the same random numbers. They consume
different RNG streams, they accumulate propensity sums in a different order, and
on this device they do not even share an arithmetic precision. Bit-equality
between them is therefore not merely unlikely, it is the wrong target: a test
that demanded it would fail a perfectly correct implementation and pass a
broken one that happened to share a seed.

So the harness tests distributional equivalence and says plainly that this is
what it tested. Three independent tests, because each has a different failure
mode and agreement between all three is much stronger evidence than any one:

1. **Per-observable mean z-test across the time grid.** Detects a systematic
   bias in a trajectory's expected level. Sensitive to anything that shifts a
   marginal: wrong rate law, wrong initial condition, wrong horizon.
2. **Two-sample Kolmogorov-Smirnov on the final-state distribution.** Detects a
   difference in *shape*, which the mean test is blind to. A simulator that
   produces the right mean with the wrong variance (a classic symptom of
   clamping a negative population to zero) passes test 1 and fails test 2.
3. **Final-state moment comparison, mean and variance.** A cheap, assumption-
   light sanity net that localises *which* observable moved, so a failure points
   at a mechanism instead of just a number.

Tolerance policy, stated rather than buried:
  * The z threshold is Bonferroni-corrected for the number of cells tested, via
    `precision.tolerance_for`. A fixed 3.0 is wrong: the largest of K
    independent standard normals grows like sqrt(2 ln K), so a fixed threshold
    cries wolf on a big model and misses real defects on a small one.
  * The KS test uses the asymptotic Kolmogorov distribution with the Stephens
    finite-sample correction, and reports its own effective sample size.
  * A pass is a *failure to reject*, not a demonstration of identity. The
    report says "consistent with", and the test's power is reported alongside so
    a reader can see how much agreement the data actually constrains.

This module is dependency-free: it computes the distribution functions it needs
rather than importing a statistics package, so the harness stays stdlib-only and
the numbers it prints can be audited in one file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .precision import tolerance_for


@dataclass
class EquivalenceResult:
    """Outcome of a host/device statistical comparison."""

    passed: bool
    n_trajectories_a: int
    n_trajectories_b: int
    max_abs_z: float
    z_threshold: float
    z_passes: int
    z_cells: int
    worst_observable: str | None
    ks_results: list[dict[str, Any]] = field(default_factory=list)
    moment_results: list[dict[str, Any]] = field(default_factory=list)
    alpha: float = 0.001
    notes: list[str] = field(default_factory=list)

    @property
    def strength(self) -> str:
        """How much the data actually constrains agreement.

        Reported next to the pass/fail so "consistent with" is not read as
        "demonstrated identical". Weak power means a pass is uninformative.
        """
        return _power_label(self.n_trajectories_a, self.n_trajectories_b)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "claim": (
                "statistical equivalence only: different RNG streams and "
                "different arithmetic precision mean bit-identity is not a "
                "meaningful target for this comparison"
            ),
            "n_trajectories_a": self.n_trajectories_a,
            "n_trajectories_b": self.n_trajectories_b,
            "detectable_effect_size": _detectable_effect(
                self.n_trajectories_a, self.n_trajectories_b, self.alpha
            ),
            "test_power_label": self.strength,
            "max_abs_z": self.max_abs_z,
            "z_threshold": self.z_threshold,
            "z_cells": self.z_cells,
            "z_passes": self.z_passes,
            "worst_observable": self.worst_observable,
            "ks_results": self.ks_results,
            "moment_results": self.moment_results,
            "alpha": self.alpha,
            "notes": self.notes,
        }


def _power_label(n_a: int, n_b: int) -> str:
    """Coarse label for what a two-sample comparison of this size can resolve."""
    n = min(n_a, n_b)
    if n >= 100_000:
        return "strong (can resolve ~1% mean shifts and fine distributional detail)"
    if n >= 10_000:
        return "good (can resolve ~3% mean shifts)"
    if n >= 1_000:
        return "moderate (can resolve ~10% mean shifts; small biases invisible)"
    if n >= 100:
        return "weak (only gross disagreement visible)"
    return "very weak (a pass here is close to uninformative)"


def _detectable_effect(n_a: int, n_b: int, alpha: float) -> str:
    """The mean shift a test of this size could just detect, as a string.

    For two samples of equal size n and pooled standard deviation sigma, the
    minimum detectable standardised difference at level alpha is
    (z_{1-alpha/2} + z_{1-beta}) * sqrt(2/n). With 80% power this is
    2.802 * sqrt(2/n) in units of the pooled standard deviation.
    """
    n = max(1, min(n_a, n_b))
    mdes = 2.802 * math.sqrt(2.0 / n)
    return (
        f"{mdes:.4f} pooled standard deviations "
        f"(~{100.0 * mdes:.2f}% of a pooled SD, at 80% power, alpha={alpha})"
    )


# --------------------------------------------------------------------------
# Distribution helpers (stdlib only)
# --------------------------------------------------------------------------


def _norm_sf(z: float) -> float:
    """Upper-tail probability of the standard normal, via erfc.

    erfc is accurate across the whole range here needs, including the far tail
    where a naive exp(-z^2/2) / (z sqrt(2pi)) loses most of its digits.
    """
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _norm_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def _kolmogorov_sf(lam: float) -> float:
    """Survival function of the asymptotic Kolmogorov distribution.

    Q(lam) = 2 * sum_{j>=1} (-1)^(j-1) exp(-2 j^2 lam^2). The series converges
    very fast; the tail is bounded below by the first term, so it is safe to stop
    once the terms fall under machine epsilon.
    """
    if lam <= 0.0:
        return 1.0
    total = 0.0
    for j in range(1, 101):
        term = math.exp(-2.0 * (j * lam) ** 2)
        total += (1.0 if j % 2 == 1 else -1.0) * term
        if term < 1e-18:
            break
    return max(0.0, min(1.0, 2.0 * total))


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_vals[int(pos)])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs) if xs else float("nan")


def _var(xs: Sequence[float], mean: float | None = None) -> float:
    """Sample variance (Bessel-corrected)."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean if mean is not None else _mean(xs)
    return max(0.0, (math.fsum((x - m) ** 2 for x in xs) / (n - 1)))


# --------------------------------------------------------------------------
# The tests
# --------------------------------------------------------------------------


def mean_z_test(
    mean_a: Sequence[float],
    std_a: Sequence[float],
    mean_b: Sequence[float],
    std_b: Sequence[float],
    names: Sequence[str],
    n_a: int,
    n_b: int,
    alpha: float = 0.001,
) -> tuple[list[dict[str, Any]], float, float, str | None]:
    """Two-sample z-test of observable means, per (observable, time) cell.

    The inputs are the per-time-grid means and standard deviations that the
    engine reports, plus the sample sizes, so this reads the engine's own
    aggregation rather than recomputing it.

    Returns (per-cell records, max |z|, threshold, worst observable name).
    """
    cells: list[dict[str, Any]] = []
    n_cells = sum(len(mean_a[o]) for o in range(len(mean_a)))
    threshold = tolerance_for([0.0], n_cells, alpha)
    # Track the worst cell by magnitude explicitly. Initialising to -inf and
    # comparing abs(z) > abs(worst) would compare against +inf and never fire,
    # which silently reports max|z| == 0 for every input and turns the whole
    # mean test into a no-op that passes everything.
    worst_magnitude = -1.0
    worst_name: str | None = None

    for o in range(len(mean_a)):
        label = names[o] if o < len(names) else f"obs{o}"
        for t in range(len(mean_a[o])):
            ma = float(mean_a[o][t])
            mb = float(mean_b[o][t])
            sa = float(std_a[o][t])
            sb = float(std_b[o][t])
            se = math.sqrt((sa * sa) / n_a + (sb * sb) / n_b) if n_a and n_b else 0.0
            if se <= 0.0:
                # Both sides have no spread at this cell; identical means mean
                # agreement, differing means mean a real difference. Only the
                # latter is reportable as a deviation.
                z = 0.0 if ma == mb else float("inf")
            else:
                z = (ma - mb) / se
            p = 0.0 if z == float("inf") else _norm_sf(abs(z))
            cells.append(
                {
                    "observable": label,
                    "time_index": t,
                    "mean_a": ma,
                    "mean_b": mb,
                    "std_a": sa,
                    "std_b": sb,
                    "z": z,
                    "two_sided_p": p,
                    "passes": abs(z) <= threshold,
                }
            )
            if abs(z) > worst_magnitude:
                worst_magnitude = abs(z)
                worst_name = label

    return cells, max(worst_magnitude, 0.0), threshold, worst_name


def ks_two_sample(
    sample_a: Sequence[float], sample_b: Sequence[float], alpha: float = 0.001
) -> dict[str, Any]:
    """Two-sample Kolmogorov-Smirnov test of two empirical CDFs.

    O(n log n) by merging the sorted samples; no dependency required. The
    Stephens finite-sample correction lam = (sqrt(ne) + 0.12 + 0.11/sqrt(ne)) D
    is applied because the asymptotic p-value is materially optimistic at the
    sample sizes a benchmark actually uses.
    """
    a = sorted(float(x) for x in sample_a)
    b = sorted(float(x) for x in sample_b)
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return {
            "statistic": float("nan"),
            "p_value": float("nan"),
            "n_a": na,
            "n_b": nb,
        }

    i = j = 0
    fa = fb = 0.0
    d = 0.0
    while i < na and j < nb:
        x = min(a[i], b[j])
        while i < na and a[i] <= x:
            i += 1
        while j < nb and b[j] <= x:
            j += 1
        fa = i / na
        fb = j / nb
        d = max(d, abs(fa - fb))
        if i >= na and j >= nb:
            break

    ne = math.sqrt(na * nb / (na + nb))
    lam = (ne + 0.12 + 0.11 / ne) * d
    p = _kolmogorov_sf(lam)
    return {
        "statistic": d,
        "p_value": p,
        "effective_n": ne,
        "n_a": na,
        "n_b": nb,
        "passes": p >= alpha,
        "note": (
            "D is the sup-norm distance between empirical CDFs; it is blind to "
            "a constant offset, which the moment test covers"
        ),
    }


def moment_test(
    values_a: Sequence[float], values_b: Sequence[float], alpha: float = 0.001
) -> dict[str, Any]:
    """Compare means and variances, so a failure names a mechanism.

    Reports relative mean error and the variance ratio. A variance ratio far
    from 1 with a mean error near 0 is the signature of a distributional shape
    difference that the mean test cannot see.
    """
    na, nb = len(values_a), len(values_b)
    if na < 2 or nb < 2:
        return {"n_a": na, "n_b": nb, "testable": False}
    ma, mb = _mean(values_a), _mean(values_b)
    va, vb = _var(values_a, ma), _var(values_b, mb)
    pooled = math.sqrt((va + vb) / 2.0)
    se = pooled * math.sqrt(1.0 / na + 1.0 / nb)
    z = (ma - mb) / se if se > 0 else (0.0 if ma == mb else float("inf"))
    mean_rel = (ma - mb) / abs(ma) if ma != 0 else (0.0 if mb == 0 else float("inf"))
    var_ratio = (vb / va) if va > 0 else float("nan")
    return {
        "testable": True,
        "n_a": na,
        "n_b": nb,
        "mean_a": ma,
        "mean_b": mb,
        "var_a": va,
        "var_b": vb,
        "mean_rel_error": mean_rel,
        "variance_ratio": var_ratio,
        "mean_z": z,
        "passes": abs(z) <= 3.0,
        "shape_flag": (
            None if not (va > 0) else abs(math.log(var_ratio)) > math.log(1.5)
        ),
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def compare_runs(
    result_a: dict[str, Any],
    result_b: dict[str, Any],
    alpha: float = 0.001,
    ks_observables: int = 4,
    max_trajectories_for_ks: int = 200_000,
) -> EquivalenceResult:
    """Run the full three-test comparison over two engine result dicts.

    `result_a` is the host run, `result_b` the other run (typically an
    accelerator run). Both are the dicts `simulate_batch_ssa_*` returns, so this
    reads `observable_means`, `observable_stds`, `final_observables`,
    `observable_names` and `batch_size` straight from the engine.

    Only the first `ks_observables` observables get a KS test: the final-state
    arrays are O(batch x observables) and a full sweep would dominate the run
    time of the very thing being measured. The chosen observables are the first
    ones, which for every model in the catalogue are its primary species, and
    the count is recorded so a reader knows how much was covered.
    """
    means_a = result_a.get("observable_means")
    means_b = result_b.get("observable_means")
    std_a = result_a.get("observable_stds")
    std_b = result_b.get("observable_stds")
    names = list(
        result_b.get("observable_names") or result_a.get("observable_names") or []
    )
    n_a = int(result_a.get("batch_size", 0))
    n_b = int(result_b.get("batch_size", 0))

    if means_a is None or means_b is None:
        return EquivalenceResult(
            passed=False,
            n_trajectories_a=n_a,
            n_trajectories_b=n_b,
            max_abs_z=float("nan"),
            z_threshold=float("nan"),
            z_passes=0,
            z_cells=0,
            worst_observable=None,
            notes=[
                "observable means are absent from at least one result; the "
                "engine did not produce the grids this test needs, so no "
                "equivalence claim is licensed"
            ],
        )

    cells, max_z, threshold, worst_name = mean_z_test(
        means_a, std_a, means_b, std_b, names, n_a, n_b, alpha
    )
    failures = [c for c in cells if not c["passes"]]

    ks_results: list[dict[str, Any]] = []
    moment_results: list[dict[str, Any]] = []
    final_a = result_a.get("final_observables")
    final_b = result_b.get("final_observables")

    if final_a is not None and final_b is not None:
        g = min(len(final_a), len(final_b), max(1, ks_observables))
        for o in range(g):
            col_a = [row[o] for row in final_a[:max_trajectories_for_ks]]
            col_b = [row[o] for row in final_b[:max_trajectories_for_ks]]
            ks = ks_two_sample(col_a, col_b, alpha)
            ks["observable"] = names[o] if o < len(names) else f"obs{o}"
            ks_results.append(ks)
            moment = moment_test(col_a, col_b, alpha)
            moment["observable"] = ks["observable"]
            moment_results.append(moment)

    notes: list[str] = []
    if ks_results:
        notes.append(
            f"KS and moment tests covered {len(ks_results)} of "
            f"{len(names) or 'unreported'} observables; the remainder are "
            f"covered only by the mean z-test"
        )
    else:
        notes.append(
            "no final-observable arrays were available, so only the mean z-test "
            "ran; shape differences in the final state would not be detected"
        )

    ks_ok = all(r.get("passes", True) for r in ks_results)
    moment_ok = all(r.get("passes", True) for r in moment_results)
    passed = not failures and ks_ok and moment_ok

    if failures:
        notes.append(
            f"{len(failures)} of {len(cells)} (observable, time) cells exceed "
            f"the Bonferroni threshold {threshold:.3f}; worst is "
            f"{worst_name} at |z|={max_z:.3f}"
        )
    else:
        notes.append(
            f"all {len(cells)} (observable, time) cells within the "
            f"Bonferroni threshold {threshold:.3f} for alpha={alpha} "
            f"corrected over {len(cells)} comparisons"
        )

    return EquivalenceResult(
        passed=passed,
        n_trajectories_a=n_a,
        n_trajectories_b=n_b,
        max_abs_z=max_z,
        z_threshold=threshold,
        z_passes=len(cells) - len(failures),
        z_cells=len(cells),
        worst_observable=worst_name,
        ks_results=ks_results,
        moment_results=moment_results,
        alpha=alpha,
        notes=notes,
    )


def binomial_chi_square(
    observed: Sequence[int], n: int, p: float, bins: int = 10
) -> dict[str, Any]:
    """Chi-square goodness-of-fit against a binomial, for analytic references.

    A closed-form reference is a genuinely independent check, but only when the
    reference's own precision is known: a single-precision sample compared to a
    double-precision analytic binomial can disagree for arithmetic reasons
    alone. The caller records the reference dtype in the precision claim; this
    function records the statistic and, crucially, how much of the expected
    count is in the sparse tail bins, since a test with expected counts below 5
    per bin is not valid in its usual form and must not be quoted as if it were.
    """
    total = sum(observed)
    if total == 0 or n <= 0:
        return {
            "statistic": float("nan"),
            "dof": 0,
            "valid": False,
            "reason": "no observations",
        }

    probs = [math.comb(n, k) * (p**k) * ((1.0 - p) ** (n - k)) for k in range(n + 1)]
    edges = [0] + [int(round(i * (n + 1) / bins)) for i in range(1, bins)]
    edges[-1] = n + 1
    chi = 0.0
    sparse = 0
    dof = 0
    detail = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        obs = sum(observed[lo : min(hi, n + 1)])
        exp = total * sum(probs[lo : min(hi, n + 1)])
        detail.append({"bin": [lo, hi - 1], "observed": obs, "expected": exp})
        if exp < 5.0:
            sparse += 1
            continue
        chi += (obs - exp) ** 2 / exp
        dof += 1
    dof = max(1, dof - 1)
    return {
        "statistic": chi,
        "dof": dof,
        "valid": sparse == 0,
        "sparse_bins": sparse,
        "bins": detail,
        "note": (
            "bins with expected count below 5 are excluded; the usual "
            "chi-square approximation is not valid there, so the excluded "
            "mass is reported rather than silently folded in"
        ),
    }
