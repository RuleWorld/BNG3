#!/usr/bin/env python3
"""Statistical validation of the batch-SSA backends.

Two independent gates share this harness.

CPU reference gate (``--mode cpu``, default) -- runs on any machine, with no
GPU and no accelerator SDK present:

1. Conservation identities. Every observable whose final-state sample has zero
   variance must be constant at EVERY recorded timepoint and on EVERY
   trajectory, and every explicitly declared conserved total must equal the
   value its model file declares. These are integer molecule counts, so the
   assertions are exact (``== 0`` deviation), not statistical.
2. Seed reproducibility. Re-running the CPU pool with the same base seed must
   reproduce the previous batch bit-for-bit, and running it single-threaded
   must reproduce the multi-core result bit-for-bit. Per-trajectory seeds are
   ``base_seed + trajectory``, so this is a hard property of the pool rather
   than a distribution.
3. Exact analytical parity on the isomerization model, whose closed form is
   ``Binomial(N=20, p=1/6)`` over the number of A molecules in conformation T.
   Checked as a Chi-square goodness-of-fit plus first- and second-moment
   tests against the theoretical mean and variance.

GPU parity (``--mode gpu``) -- unchanged, and only meaningful where a backend
exists:

1. Mean trajectory equivalence (Z-test across time points for all observables)
2. Variance trajectory equivalence (ratio of variances / F-test)
3. Distributional equivalence (Two-sample Kolmogorov-Smirnov test on final states)
4. The same exact analytical Chi-square check applied to the GPU sample.

The CPU reference gate is the one wired into CI: it is hardware-independent,
so it is a real gate, whereas the GPU comparison can only run on a maintainer's
machine with a usable backend.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import statistics
import sys
import math
import numpy as np
from scipy import stats

sys.path.insert(0, "build/cpp")
sys.path.insert(0, "python")
try:
    import _bionetgen_cpp as cpp
except ImportError:  # installed as part of the bionetgen package
    from bionetgen import _bionetgen_cpp as cpp

# Observables whose sampling error is too small to support a Z-score are
# conserved totals (or the deterministic t=0 snapshot). They are exact integer
# molecule counts fixed by the reaction stoichiometry, so CPU and GPU must
# agree to well under one molecule. A zero-variance point has no statistical
# scale, so these are compared ABSOLUTELY against this tolerance instead of
# having their Z-score zeroed out.
# 1e-3 molecules is ~1e-8 relative at the largest total in the suite and stays
# far below float32 accumulation error over a 10,000-trajectory batch, so it
# catches any real stoichiometry bug while tolerating summation noise.
CONSERVATION_ATOL = 1e-3
CONSERVATION_RTOL = 1e-6

# Two independent samples are compared at the same p > 0.001 significance the
# mean-trajectory section already documents.
KS_ALPHA = 1e-3
Z_THRESHOLD = 3.5

# The additional GPU count-law fixture is an immigration-death process started
# empty. At every time t its count is Poisson with mean
# lambda/mu * (1 - exp(-mu*t)). These thresholds are fixed before running the
# device gate; the wrong-law control below omits death and uses Poisson(lambda*t).
POISSON_CHI2_ALPHA = 1e-3
POISSON_MEAN_Z_LIMIT = 5.0
POISSON_VARIANCE_RATIO_MIN = 0.8
POISSON_VARIANCE_RATIO_MAX = 1.2

# ─────────────────────────────────────────────────────────────────────────────
# CPU reference gate
# ─────────────────────────────────────────────────────────────────────────────

# Per-trajectory seeds are ``base_seed + trajectory`` and each trajectory owns
# its own std::mt19937_64 stream, so a base seed fully determines the batch.
# The values below are pinned rather than random: the gate must fail for a
# reason that a reader can reproduce, not because a coin came up tails.
CPU_REFERENCE_SEED = 1000
CPU_REFERENCE_BATCH = 20000

# Moment bands for the exact Binomial(20, 1/6) comparison.
#
# A one-sided tail probability IS the flake probability under the null, so the
# previous Chi-square gate at p >= 0.01 failed on ~1% of statistically perfect
# batches. 0.01 is not a usable CI threshold. At B=20000, alpha=1e-3 is 100x
# safer and still detects a >=2% relative error in the equilibrium
# probability p (measured Chi-square p of 6.3e-10 at +2%, 2.9e-3 at +0.5%).
#
# The two moment tests carry most of the power and almost none of the risk:
#   - |z| > 5 is a 5.7e-7 two-sided normal tail; it detects a >=1% relative
#     error in p, an order of magnitude more sensitively than the Chi-square.
#   - Under the null the sample variance of B i.i.d. draws follows
#     (B-1)s^2/var ~ Chi2(B-1); the [0.90, 1.10] band has a null tail
#     probability below 1e-11 at B=20000, and it is the only check here that
#     notices a variance regression at all.
# Measured over 200 independent 20,000-trajectory batches: min Chi-square
# p = 2.3e-3, max |z| = 3.60, variance ratio in [0.970, 1.030], and zero
# failures at any of these thresholds.
BINOMIAL_CHI2_ALPHA = 1e-3
MEAN_Z_LIMIT = 5.0
VARIANCE_RATIO_MIN = 0.90
VARIANCE_RATIO_MAX = 1.10

# A Pearson Chi-square approximation is unreliable for an expected cell below
# roughly 5 counts, so the binning pools the sparse tail until every cell
# clears this bar. At B=20000 the Binomial(20, 1/6) tail cell carries ~57.
MIN_EXPECTED_COUNTS = 5.0

# The models exercised by the CPU reference gate, with the exact quantities
# their .bngl files declare. `conserved` maps an observable to the constant
# its model file fixes; `partition` is a closed sum over those observables.
# Values are transcribed from the model files themselves, which is what makes
# this an analytical check rather than a re-statement of the simulation.
#
#   models/isomerization.bngl:11,60            N = 20, seed species A(conf~R) N
#   models/toy-jim.bngl:12-14,37,41,45         A_tot = K_tot = R_tot = 1
#   models/performance_test_models/egfr_net.bngl:6,81  egfr_tot = 1.8e3
#
# models/gene_expr_simple.bngl declares no conserved quantity: mRNA() and
# Protein() are both synthesized and degraded, so there is nothing to
# conserve. Its only CPU-gate coverage is the zero-variance scan, which finds
# none -- correctly, since both of its observables vary.
CPU_REFERENCE_MODELS = [
    {
        "name": "isomerization",
        "path": "models/isomerization.bngl",
        "t_end": 20.0,
        "n_steps": 10,
        "conserved": {"A_total": 20.0},
        # A_total == A_confR + A_confT: the two conformations partition the pool.
        "partition": ("A_total", ("A_confR", "A_confT")),
        "binomial": {"observable": "A_confT", "n": 20, "p": 0.2 / 1.2},
    },
    {
        "name": "gene_expr_simple",
        "path": "models/gene_expr_simple.bngl",
        "t_end": 500.0,
        "n_steps": 10,
        "conserved": {},
        "partition": None,
        "binomial": None,
    },
    {
        "name": "toy-jim",
        "path": "models/toy-jim.bngl",
        "t_end": 50.0,
        "n_steps": 10,
        "conserved": {"A_total": 1.0, "K_total": 1.0, "R_total": 1.0},
        "partition": None,
        "binomial": None,
    },
    {
        "name": "egfr_net",
        "path": "models/performance_test_models/egfr_net.bngl",
        "t_end": 0.02,
        "n_steps": 10,
        "conserved": {"Efgr_tot": 1800.0},
        "partition": None,
        "binomial": None,
    },
]


def run_cpu_batch(bngl_path, t_end, n_steps, batch_size, base_seed, threads=0):
    """Run one CPU-pool batch and return (model, network, metrics)."""
    model = cpp.parse_file(bngl_path)
    net = cpp.generate_network(model)
    res = cpp.simulate_batch_ssa_cpu(
        model,
        net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        threads=threads,
        base_seed=base_seed,
    )
    return model, net, res


def _observable_names(res):
    return list(res.get("observable_names", []))


def evaluate_poisson_count_sample(sample, expected_mean):
    """Check integer count samples against one independently declared Poisson law."""
    values = np.asarray(sample, dtype=float)
    report = {
        "status": "FAIL",
        "sample_size": int(values.size),
        "expected_mean": float(expected_mean),
        "observed_mean": None,
        "mean_z": None,
        "variance_ratio": None,
        "chi_square": None,
        "chi_square_p": None,
        "bins": 0,
        "reason": "",
    }
    if values.ndim != 1 or values.size < 2:
        report["reason"] = (
            "sample must be a one-dimensional ensemble with at least two counts"
        )
        return report
    if (
        not np.isfinite(values).all()
        or (values < 0).any()
        or not np.equal(values, np.floor(values)).all()
    ):
        report["reason"] = "sample must contain only finite non-negative integer counts"
        return report
    if not np.isfinite(expected_mean) or expected_mean <= 0.0:
        report["reason"] = "expected Poisson mean must be positive and finite"
        return report

    sample_size = values.size
    observed_mean = float(values.mean())
    sample_variance = float(values.var(ddof=1))
    mean_z = (observed_mean - expected_mean) / math.sqrt(expected_mean / sample_size)
    variance_ratio = sample_variance / expected_mean
    report.update(
        observed_mean=observed_mean,
        mean_z=float(mean_z),
        variance_ratio=float(variance_ratio),
    )

    # Keep a pooled upper tail with at least five expected observations. Pool
    # adjacent sparse lower cells as well, so Pearson's approximation is used
    # only with adequately populated bins.
    tail_start = 0
    while (
        stats.poisson.sf(tail_start, expected_mean) * sample_size >= MIN_EXPECTED_COUNTS
    ):
        tail_start += 1
    expected_counts = []
    observed_counts = []
    pending_expected = 0.0
    pending_observed = 0
    for count in range(tail_start):
        pending_expected += stats.poisson.pmf(count, expected_mean) * sample_size
        pending_observed += int(np.count_nonzero(values == count))
        if pending_expected >= MIN_EXPECTED_COUNTS:
            expected_counts.append(pending_expected)
            observed_counts.append(pending_observed)
            pending_expected = 0.0
            pending_observed = 0
    pending_expected += stats.poisson.sf(tail_start - 1, expected_mean) * sample_size
    pending_observed += int(np.count_nonzero(values >= tail_start))
    expected_counts.append(pending_expected)
    observed_counts.append(pending_observed)
    if len(expected_counts) < 2 or min(expected_counts) < MIN_EXPECTED_COUNTS:
        report["reason"] = (
            "sample budget is too small for a populated Poisson goodness-of-fit test"
        )
        return report

    chi_square, chi_square_p = stats.chisquare(observed_counts, expected_counts)
    report.update(
        chi_square=float(chi_square),
        chi_square_p=float(chi_square_p),
        bins=len(expected_counts),
    )
    reasons = []
    if chi_square_p < POISSON_CHI2_ALPHA:
        reasons.append(f"chi-square p={chi_square_p:.4g} < {POISSON_CHI2_ALPHA:g}")
    if abs(mean_z) > POISSON_MEAN_Z_LIMIT:
        reasons.append(f"|mean Z|={abs(mean_z):.3f} > {POISSON_MEAN_Z_LIMIT:g}")
    if not (POISSON_VARIANCE_RATIO_MIN <= variance_ratio <= POISSON_VARIANCE_RATIO_MAX):
        reasons.append(
            f"variance ratio={variance_ratio:.4f} outside "
            f"[{POISSON_VARIANCE_RATIO_MIN:g}, {POISSON_VARIANCE_RATIO_MAX:g}]"
        )
    report["reason"] = "; ".join(reasons)
    report["status"] = "FAIL" if reasons else "PASS"
    return report


def check_conservation_identities(name, res, spec, batch_size):
    """Exact (non-statistical) conservation checks on the CPU pool.

    Every observable whose final-state sample has zero variance is a conserved
    or permanently absent quantity: the reaction stoichiometry fixes it to an
    integer. Requiring it to be constant across the whole trajectory and every
    trajectory is therefore an exact assertion with no sampling error at all,
    which is why this part of the gate is hardware-independent.

    Returns True when every declared and discovered invariant holds.
    """
    obs_names = _observable_names(res)
    finals = np.asarray(res["final_observables"], dtype=float)
    all_passed = True

    print(f"\nConservation identities ({name}, batch_size={batch_size}):")
    for obs, value in spec["conserved"].items():
        means = np.asarray(res["observable_means"][obs], dtype=float)
        stds = np.asarray(res["observable_stds"][obs], dtype=float)
        column = finals[:, obs_names.index(obs)]

        mean_dev = float(np.max(np.abs(means - value)))
        std_dev = float(np.max(np.abs(stds)))
        final_dev = float(np.max(np.abs(column - value)))

        print(
            f"  {obs}: declared {value:g}; max |mean - {value:g}| = {mean_dev:.3e}, "
            f"max std = {std_dev:.3e}, max |final - {value:g}| = {final_dev:.3e}"
        )
        if mean_dev != 0.0 or std_dev != 0.0 or final_dev != 0.0:
            print(
                f"  [FAIL] '{obs}' does not hold the constant {value:g} its model "
                f"declares -- conservation/stoichiometry mismatch"
            )
            all_passed = False

    if spec["partition"]:
        # spec["partition"] is (total, (parts...)): the total must equal the
        # exact sum of its parts on every trajectory.
        total_obs, part_obs = spec["partition"]
        total = np.asarray(finals[:, obs_names.index(total_obs)], dtype=float)
        parts = [
            np.asarray(finals[:, obs_names.index(o)], dtype=float) for o in part_obs
        ]
        residual = total - sum(parts)
        worst = float(np.max(np.abs(residual)))
        identity = f"{total_obs} - ({' + '.join(part_obs)})"
        print(
            f"  {identity}: max |residual| = {worst:.3e} over "
            f"{finals.shape[0]} trajectories"
        )
        if worst != 0.0:
            print(
                f"  [FAIL] the declared partition does not hold exactly -- "
                f"a stoichiometry or observable-mapping bug"
            )
            all_passed = False

    # Discover every other exactly-constant observable. A batch that invents
    # variation where the stoichiometry admits none is a bug even when the
    # model file does not name the quantity.
    discovered = 0
    for idx, obs in enumerate(obs_names):
        column = finals[:, idx]
        if float(np.std(column)) != 0.0:
            continue
        if obs in spec["conserved"]:
            continue
        discovered += 1
        value = float(column[0])
        means = np.asarray(res["observable_means"][obs], dtype=float)
        stds = np.asarray(res["observable_stds"][obs], dtype=float)
        drift = float(np.max(np.abs(means - value)))
        std_dev = float(np.max(np.abs(stds)))
        print(
            f"  {obs}: undeclared but exactly constant at {value:g} "
            f"(max |mean - const| = {drift:.3e}, max std = {std_dev:.3e})"
        )
        if drift != 0.0 or std_dev != 0.0:
            print(
                f"  [FAIL] '{obs}' is constant at t_end but varies over the "
                f"trajectory -- a conservation/stoichiometry mismatch"
            )
            all_passed = False
    print(f"  {discovered} additional exactly-constant observable(s) discovered")

    if not np.all(finals >= 0.0):
        print(
            "  [FAIL] a final-state observable is negative -- molecule counts "
            "cannot be negative"
        )
        all_passed = False
    if float(np.max(np.abs(finals - np.round(finals)))) != 0.0:
        print("  [FAIL] a final-state observable is not an integer molecule count")
        all_passed = False

    if all_passed:
        print("  [PASS] every conserved/constant observable is exactly conserved")
    return all_passed


def check_seed_reproducibility(name, bngl_path, t_end, n_steps, batch_size, base_seed):
    """The CPU pool must be reproducible for a given seed and thread count.

    Trajectory b draws from ``std::mt19937_64`` seeded with
    ``base_seed + b``, so a base seed determines the entire batch. If the pool
    let any cross-trajectory state leak, or accumulated into shared state
    without synchronisation, this comparison would diverge.
    """
    print(f"\nSeed reproducibility ({name}, base_seed={base_seed}):")
    all_passed = True

    _, _, first = run_cpu_batch(bngl_path, t_end, n_steps, batch_size, base_seed)
    _, _, repeat = run_cpu_batch(bngl_path, t_end, n_steps, batch_size, base_seed)
    _, _, single = run_cpu_batch(
        bngl_path, t_end, n_steps, batch_size, base_seed, threads=1
    )

    def _identical(a, b):
        if a.shape != b.shape:
            return False
        return bool(np.array_equal(a, b))

    finals_exact = _identical(
        np.asarray(first["final_observables"]),
        np.asarray(repeat["final_observables"]),
    )
    print(f"  same seed twice: final states bit-identical = {finals_exact}")
    if not finals_exact:
        all_passed = False
        print("  [FAIL] the CPU pool is not reproducible for a fixed base seed")

    finals_exact = _identical(
        np.asarray(first["final_observables"]),
        np.asarray(single["final_observables"]),
    )
    print(f"  threads=0 vs threads=1: final states bit-identical = {finals_exact}")
    if not finals_exact:
        all_passed = False
        print(
            "  [FAIL] the multi-core pool and the single-worker pool disagree "
            "for a fixed base seed"
        )

    aggregate_exact = True
    for key in ("observable_means", "observable_stds"):
        for obs in _observable_names(first):
            if not _identical(
                np.asarray(first[key][obs]), np.asarray(single[key][obs])
            ):
                aggregate_exact = False
                print(
                    f"  [FAIL] {key}['{obs}'] differs between the multi-core and "
                    f"single-worker pools"
                )
    print(
        f"  threads=0 vs threads=1: trajectory means/stds identical = {aggregate_exact}"
    )
    if not aggregate_exact:
        all_passed = False

    if all_passed:
        print(
            "  [PASS] the CPU pool is reproducible for a fixed seed and "
            "independent of the thread count"
        )
    return all_passed


def check_analytical_binomial(name, res, spec, batch_size):
    """Chi-square plus moment tests against the model's closed-form binomial.

    `spec["binomial"]` names an observable whose equilibrium distribution is
    exactly ``Binomial(n, p)``. For the isomerization model each of the N
    molecules flips R<->T independently with rates kRT=0.20 and kTR=1.00, so
    the stationary probability of conformation T is 0.20/1.20 = 1/6 and the
    number of T molecules is Binomial(N, 1/6).
    """
    cfg = spec["binomial"]
    obs_names = _observable_names(res)
    finals = np.asarray(res["final_observables"], dtype=float)
    sample = finals[:, obs_names.index(cfg["observable"])]

    n_mol = cfg["n"]
    p_t = cfg["p"]
    expected_mean = n_mol * p_t
    expected_var = n_mol * p_t * (1.0 - p_t)

    print(
        f"\nExact analytical parity check ({name}): "
        f"{cfg['observable']} ~ Binomial({n_mol}, {p_t:.6f})"
    )
    print(f"  Theoretical: mean = {expected_mean:.4f}, variance = {expected_var:.4f}")
    print(
        f"  CPU sample : mean = {sample.mean():.4f}, "
        f"variance = {sample.var(ddof=1):.4f}, n = {sample.size}"
    )

    all_passed = True

    # Build cells that partition k = 0..n and preserve the total probability
    # exactly: individual bins for the head, one pooled bin for the sparse
    # tail. The pooled tail probability is the remainder rather than a summed
    # term, so the expected counts always add up to batch_size and SciPy's
    # sum-check cannot fail.
    pmf = [
        math.comb(n_mol, k) * (p_t**k) * ((1.0 - p_t) ** (n_mol - k))
        for k in range(n_mol + 1)
    ]

    # Widest head whose every cell carries at least MIN_EXPECTED_COUNTS, so the
    # pooled tail is never thinner than the head cells it replaces.
    head = 1
    while head < n_mol and pmf[head + 1] * batch_size >= MIN_EXPECTED_COUNTS:
        head += 1
    while head > 1 and pmf[head] * batch_size < MIN_EXPECTED_COUNTS:
        head -= 1

    # Cells 0..head-1 are exact bins; cell `head` pools every k >= head.
    # Guard against a k < 0 sample value, which cannot occur for a molecule
    # count but would otherwise be silently mis-binned.
    cell_probabilities = pmf[:head] + [sum(pmf[head:])]
    expected_counts = np.asarray(cell_probabilities) * batch_size

    if expected_counts.min() < MIN_EXPECTED_COUNTS:
        print(
            f"  [FAIL] the Chi-square binning has a cell with only "
            f"{expected_counts.min():.2f} expected counts; raise the batch size "
            f"so every cell reaches {MIN_EXPECTED_COUNTS:g}"
        )
        return False

    def _counts(values):
        cells = np.zeros(len(cell_probabilities))
        for value in values:
            k = int(round(value))
            if k < 0:
                raise ValueError(f"negative molecule count {value!r}")
            cells[k if k < head else head] += 1
        return cells

    observed_counts = _counts(sample)
    chi2, p_value = stats.chisquare(observed_counts, expected_counts)
    print(
        f"  Chi-square ({len(cell_probabilities)} cells, "
        f"df = {len(cell_probabilities) - 1}) = {chi2:.3f}, "
        f"p = {p_value:.4g} (threshold {BINOMIAL_CHI2_ALPHA:g}, "
        f"min expected cell {expected_counts.min():.1f})"
    )
    if p_value < BINOMIAL_CHI2_ALPHA:
        print(
            "  [FAIL] the CPU sample deviates significantly from the theoretical "
            "binomial distribution"
        )
        all_passed = False

    sem = math.sqrt(expected_var / sample.size)
    z = (sample.mean() - expected_mean) / sem
    print(
        f"  Mean Z-score = {z:+.3f} (threshold |Z| <= {MEAN_Z_LIMIT:g}, "
        f"SEM = {sem:.4f} molecules)"
    )
    if abs(z) > MEAN_Z_LIMIT:
        print("  [FAIL] the sample mean is inconsistent with the theoretical mean")
        all_passed = False

    variance_ratio = sample.var(ddof=1) / expected_var
    print(
        f"  Variance ratio = {variance_ratio:.4f} (allowed "
        f"[{VARIANCE_RATIO_MIN:g}, {VARIANCE_RATIO_MAX:g}])"
    )
    if not (VARIANCE_RATIO_MIN <= variance_ratio <= VARIANCE_RATIO_MAX):
        print(
            "  [FAIL] the sample variance is inconsistent with the theoretical variance"
        )
        all_passed = False

    if all_passed:
        print(
            f"  [PASS] the CPU sample matches the exact analytical "
            f"Binomial({n_mol}, {p_t:.6f}) distribution"
        )
    return all_passed


def run_cpu_reference_gate():
    """Hardware-independent evidence that the batch SSA is correct."""
    print("=" * 70)
    print("Batch SSA CPU reference gate (no GPU required)")
    print("=" * 70)

    all_ok = True
    for spec in CPU_REFERENCE_MODELS:
        name = spec["name"]
        print(f"\n{'=' * 70}")
        print(
            f"CPU reference validation: {name} "
            f"(batch_size={CPU_REFERENCE_BATCH}, seed={CPU_REFERENCE_SEED})"
        )
        print(f"{'=' * 70}")

        _, net, res = run_cpu_batch(
            spec["path"],
            spec["t_end"],
            spec["n_steps"],
            CPU_REFERENCE_BATCH,
            CPU_REFERENCE_SEED,
        )
        print(
            f"Model: {net.num_species} species, {net.num_reactions} reactions, "
            f"{len(_observable_names(res))} observables"
        )

        results = [check_conservation_identities(name, res, spec, CPU_REFERENCE_BATCH)]

        if spec["binomial"]:
            results.append(
                check_analytical_binomial(name, res, spec, CPU_REFERENCE_BATCH)
            )

        results.append(
            check_seed_reproducibility(
                name,
                spec["path"],
                spec["t_end"],
                spec["n_steps"],
                CPU_REFERENCE_BATCH,
                CPU_REFERENCE_SEED,
            )
        )

        if not all(results):
            all_ok = False

    print("\n" + "=" * 70)
    if all_ok:
        print("ALL CPU REFERENCE PARITY TESTS PASSED SUCCESSFULLY!")
    else:
        print("SOME CPU REFERENCE TESTS FAILED.")
    print("=" * 70)
    return all_ok


def check_device_result(result, backend, batch_size, expected_times):
    """Check actual device identity and complete, finite output before statistics."""
    if backend is not None:
        assert result["backend"] == backend, "requested GPU backend did not execute"
    assert result["batch_size"] == batch_size, "incomplete GPU batch"
    np.testing.assert_array_equal(result["time"], expected_times)
    names = result["observable_names"]
    assert names and len(set(names)) == len(names), "missing/duplicate observables"
    assert np.shape(result["final_observables"]) == (batch_size, len(names))
    assert np.isfinite(result["final_observables"]).all()
    assert np.ndim(result["final_species"]) == 2
    assert np.shape(result["final_species"])[0] == batch_size
    assert np.isfinite(result["final_species"]).all()
    assert (np.asarray(result["final_species"]) >= 0).all()
    assert np.shape(result["event_counts"]) == (batch_size,)
    counts = np.asarray(result["event_counts"])
    assert np.isfinite(counts).all() and (counts >= 0).all()
    assert (counts == np.floor(counts)).all()
    assert result["total_events"] == sum(int(value) for value in counts)
    for key in ("observable_means", "observable_stds"):
        assert set(result[key]) == set(names)
        for values in result[key].values():
            assert np.shape(values) == np.shape(expected_times)
            assert np.isfinite(values).all()
            if key == "observable_stds":
                assert (np.asarray(values) >= 0).all()


def validate_immigration_death_gpu(backend, *, receipt=None):
    """Qualify zero- and first-order device propensities against a Poisson law."""
    model_path = Path("tests/fixtures/gpu_batch_ssa/gpu_immigration_death.bngl")
    immigration_rate = 4.0
    death_rate = 0.7
    t_end = 2.0
    n_steps = 4
    batch_size = 5000
    base_seed = 240474
    expected_times = np.linspace(0.0, t_end, n_steps + 1).astype(np.float32)
    model = cpp.parse_file(str(model_path))
    network = cpp.generate_network(model)

    def run(batch, seed):
        return cpp.simulate_batch_ssa_gpu(
            model,
            network,
            batch_size=batch,
            t_end=t_end,
            n_steps=n_steps,
            t_start=0.0,
            base_seed=seed,
            backend=backend,
        )

    result = run(batch_size, base_seed)
    check_device_result(result, backend, batch_size, expected_times)
    if result["observable_names"] != ["A_count"]:
        raise AssertionError(f"unexpected observables: {result['observable_names']}")

    mean_trajectory = np.asarray(result["observable_means"]["A_count"], dtype=float)
    std_trajectory = np.asarray(result["observable_stds"]["A_count"], dtype=float)
    if mean_trajectory[0] != 0.0 or std_trajectory[0] != 0.0:
        raise AssertionError("the empty initial population changed at the t=0 sample")
    time_checks = []
    for index, time in enumerate(expected_times[1:], start=1):
        expected_mean = (
            immigration_rate / death_rate * (1.0 - math.exp(-death_rate * float(time)))
        )
        mean_z = (mean_trajectory[index] - expected_mean) / math.sqrt(
            expected_mean / batch_size
        )
        variance_ratio = std_trajectory[index] ** 2 / expected_mean
        time_checks.append(
            {
                "time": float(time),
                "expected_mean": expected_mean,
                "observed_mean": float(mean_trajectory[index]),
                "mean_z": float(mean_z),
                "variance_ratio": float(variance_ratio),
            }
        )
        if abs(mean_z) > POISSON_MEAN_Z_LIMIT:
            raise AssertionError(
                f"t={time:g}: Poisson mean Z={mean_z:.3f} exceeds "
                f"{POISSON_MEAN_Z_LIMIT:g}"
            )
        if not (
            POISSON_VARIANCE_RATIO_MIN <= variance_ratio <= POISSON_VARIANCE_RATIO_MAX
        ):
            raise AssertionError(
                f"t={time:g}: Poisson variance ratio {variance_ratio:.4f} is outside "
                f"[{POISSON_VARIANCE_RATIO_MIN:g}, {POISSON_VARIANCE_RATIO_MAX:g}]"
            )

    expected_final_mean = (
        immigration_rate / death_rate * (1.0 - math.exp(-death_rate * t_end))
    )
    final_sample = np.asarray(result["final_observables"], dtype=float)[:, 0]
    final_fit = evaluate_poisson_count_sample(final_sample, expected_final_mean)
    if final_fit["status"] != "PASS":
        raise AssertionError(f"GPU count sample failed the Poisson law: {final_fit}")

    # This control intentionally omits death. Its Poisson(lambda*t) law must
    # fall outside the acceptance bands for the declared immigration-death law.
    wrong_mean = immigration_rate * t_end
    wrong_sample = np.random.default_rng(20261120).poisson(wrong_mean, size=batch_size)
    wrong_fit = evaluate_poisson_count_sample(wrong_sample, expected_final_mean)
    if wrong_fit["status"] != "FAIL":
        raise AssertionError("the no-death wrong-law control passed the Poisson gate")

    # Device trajectories are keyed by trajectory index. Repetition after an
    # unrelated batch and changing the batch boundary must preserve every
    # corresponding trajectory exactly.
    interleaved = run(17, base_seed + 1)
    check_device_result(interleaved, backend, 17, expected_times)
    repeated = run(batch_size, base_seed)
    for key in ("final_observables", "final_species", "event_counts"):
        np.testing.assert_array_equal(result[key], repeated[key])

    prefix_sizes = (63, 64, 65, 255, 256, 257)
    for prefix_size in prefix_sizes:
        prefix = run(prefix_size, base_seed)
        check_device_result(prefix, backend, prefix_size, expected_times)
        for key in ("final_observables", "final_species", "event_counts"):
            np.testing.assert_array_equal(result[key][:prefix_size], prefix[key])

    if receipt is not None:
        receipt.update(
            {
                "status": "PASS",
                "backend": result["backend"],
                "batch_size": batch_size,
                "base_seed": base_seed,
                "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
                "initial_population": 0,
                "immigration_rate": immigration_rate,
                "death_rate": death_rate,
                "time_checks": time_checks,
                "final_count_law": "Poisson(lambda/mu * (1-exp(-mu*t)))",
                "final_count_fit": final_fit,
                "no_death_wrong_law_rejected": True,
                "repeated_after_interleaving": True,
                "trajectory_index_prefix_equal_at_batch_sizes": list(prefix_sizes),
            }
        )
    return True


def validate_public_simulate_ssa_route(backend, *, receipt=None):
    """Exercise the public convenience batch route on a physical device.

    ``simulate_ssa(batch_size=N, n_steps>0)`` must return the device result and
    the full ``[time][species]`` grid.  CPU and device RNGs use different draw
    ordering, so the device/device mean comparison below is distributional
    with a prespecified Bonferroni threshold and fixed budgets, never pathwise.
    """
    if backend in (None, "none"):
        raise AssertionError("the public route requires an explicit GPU backend")
    model_path = "models/toy-jim.bngl"
    t_end = 10.0
    n_steps = 10
    batch_size = 1000
    seed = 474474
    expected_times = np.linspace(0.0, t_end, n_steps + 1).astype(np.float32)
    alpha = 0.001
    comparisons = 6
    z_limit = float(statistics.NormalDist().inv_cdf(1.0 - alpha / (2 * comparisons)))

    model = cpp.parse_file(model_path)
    network = cpp.generate_network(model)

    def run_convenience(base_seed):
        return cpp.simulate_ssa(
            model,
            network,
            t_end=t_end,
            n_steps=n_steps,
            t_start=0.0,
            seed=base_seed,
            batch_size=batch_size,
            batch_gpu_preferred=True,
            batch_gpu_backend=backend,
        )

    result = run_convenience(seed)
    if result.get("backend") != backend:
        raise AssertionError(
            f"public batch route did not report device execution: {result.get('backend')}"
        )
    np.testing.assert_array_equal(result["time"], expected_times)
    concentrations = np.asarray(result["concentrations"], dtype=float)
    if concentrations.shape != (n_steps + 1, network.num_species):
        raise AssertionError(
            f"device result has a collapsed species grid: {concentrations.shape}"
        )
    for name, values in result["batch_std_devs"].items():
        if np.asarray(values).shape != (n_steps + 1,):
            raise AssertionError(f"collapsed std-dev trajectory for {name}")
    for name in ("A_total", "K_total", "R_total", "L_total"):
        conserved = np.asarray(result["observables"][name], dtype=float)
        if conserved.shape != (n_steps + 1,) or not np.allclose(
            conserved, conserved[0], rtol=0.0, atol=1e-5
        ):
            raise AssertionError(f"{name} conservation law failed on the device grid")
    replay = run_convenience(seed)
    for name in result["observables"]:
        np.testing.assert_array_equal(
            np.asarray(result["observables"][name]),
            np.asarray(replay["observables"][name]),
        )
    np.testing.assert_array_equal(
        np.asarray(result["batch_std_devs"]["A_total"]),
        np.asarray(replay["batch_std_devs"]["A_total"]),
    )

    # Independent CPU SSA pool reference (separate RNG & implementation).
    reference = cpp.simulate_batch_ssa_cpu(
        model,
        network,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        t_start=0.0,
        base_seed=seed + 1,
        threads=0,
    )
    check_device_result(reference, None, batch_size, expected_times)
    checks = []
    for name in ("Rec_A", "Rec_K"):
        device_mean = np.asarray(result["observables"][name], dtype=float)
        device_std = np.asarray(result["batch_std_devs"][name], dtype=float)
        reference_mean = np.asarray(reference["observable_means"][name], dtype=float)
        reference_std = np.asarray(reference["observable_stds"][name], dtype=float)
        for index in (2, 5, 10):
            standard_error = math.sqrt(
                device_std[index] ** 2 / batch_size
                + reference_std[index] ** 2 / batch_size
            )
            if standard_error == 0.0:
                # Both samples are degenerate at this time point: an exact
                # equality check is the only meaningful comparison.
                passed = abs(device_mean[index] - reference_mean[index]) <= 1e-6
                z = None
            else:
                z = (device_mean[index] - reference_mean[index]) / standard_error
                passed = abs(z) <= z_limit
            checks.append(
                {
                    "observable": name,
                    "time": float(expected_times[index]),
                    "mean_z": z,
                    "pass": bool(passed),
                }
            )
    if not all(item["pass"] for item in checks):
        raise AssertionError(f"distributional device/CPU comparison failed: {checks}")

    if receipt is not None:
        receipt.update(
            {
                "status": "PASS",
                "backend": backend,
                "model": "toy-jim-public-route",
                "batch_size": batch_size,
                "n_steps": n_steps,
                "seed": seed,
                "reference_seed": seed + 1,
                "comparison": f"distributional, {backend} device vs independent CPU SSA pool",
                "alpha": alpha,
                "bonferroni_comparisons": comparisons,
                "z_limit": z_limit,
                "checks": checks,
                "device_grid_shape": list(concentrations.shape),
                "seed_replay": True,
            }
        )
    return True


def validate_model(
    name, bngl_path, t_end, n_steps, batch_size=2000, *, backend="auto", receipt=None
):
    print(f"\n{'=' * 70}")
    print(f"Statistical Validation: {name} (batch_size={batch_size})")
    print(f"{'=' * 70}")

    model = cpp.parse_file(bngl_path)
    net = cpp.generate_network(model)
    print(f"Model: {net.num_species} species, {net.num_reactions} reactions")

    # Run CPU multi-core batch
    cpu_res = cpp.simulate_batch_ssa_cpu(
        model,
        net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        threads=0,
        base_seed=1000,
    )
    expected_times = np.linspace(0.0, t_end, n_steps + 1).astype(np.float32)
    check_device_result(cpu_res, None, batch_size, expected_times)

    # Run GPU batch on the backend that would be selected automatically.
    backend = cpp.default_gpu_backend() if backend == "auto" else backend
    if backend == "none":
        print(f"  [SKIP] no GPU backend available: {cpp.gpu_backends()}")
        return True
    print(f"  GPU backend: {backend}")
    gpu_res = cpp.simulate_batch_ssa_gpu(
        model,
        net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        base_seed=5000,
        backend=backend,
    )
    check_device_result(gpu_res, backend, batch_size, expected_times)
    assert gpu_res["observable_names"] == cpu_res["observable_names"]
    repeated = cpp.simulate_batch_ssa_gpu(
        model,
        net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        base_seed=5000,
        backend=backend,
    )
    check_device_result(repeated, backend, batch_size, expected_times)
    for key in ("final_observables", "final_species", "event_counts"):
        np.testing.assert_array_equal(gpu_res[key], repeated[key])
    for key in ("observable_means", "observable_stds"):
        for observable in gpu_res["observable_names"]:
            np.testing.assert_array_equal(
                gpu_res[key][observable], repeated[key][observable]
            )
    if receipt is not None:
        receipt.update(
            {
                "backend": gpu_res["backend"],
                "batch_size": batch_size,
                "model_sha256": hashlib.sha256(
                    Path(bngl_path).read_bytes()
                ).hexdigest(),
                "cpu_base_seed": 1000,
                "gpu_base_seed": 5000,
                "species": net.num_species,
                "reactions": net.num_reactions,
                "cpu_wall_time_ms": cpu_res["total_wall_time_ms"],
                "gpu_wall_time_ms": gpu_res["total_wall_time_ms"],
                "gpu_sim_time_ms": gpu_res["sim_time_ms"],
                "gpu_events": gpu_res["total_events"],
                "seed_reproducible": True,
            }
        )

    time_points = cpu_res["time"]
    obs_names = cpu_res.get("observable_names", [])

    print(f"Time points: {len(time_points)}, Observables: {len(obs_names)}")

    all_passed = True

    # 1. Compare trajectory means and stddevs over time
    for obs in obs_names:
        cpu_mean = np.array(cpu_res["observable_means"][obs])
        gpu_mean = np.array(gpu_res["observable_means"][obs])
        cpu_std = np.array(cpu_res["observable_stds"][obs])
        gpu_std = np.array(gpu_res["observable_stds"][obs])

        sem_cpu = cpu_std / math.sqrt(batch_size)
        sem_gpu = gpu_std / math.sqrt(batch_size)
        pooled_sem = np.sqrt(sem_cpu**2 + sem_gpu**2)
        abs_diff = np.abs(gpu_mean - cpu_mean)

        # A point with no sampling error carries no statistical scale, so a
        # Z-score there is undefined. Zeroing it (as this test previously did)
        # silently reported any CPU/GPU divergence at those points as a pass --
        # and those are exactly the conserved quantities that would expose a
        # stoichiometry bug. Compare them absolutely against a conservation
        # tolerance instead.
        testable = pooled_sem > 1e-6
        z_scores = np.full_like(cpu_mean, np.nan)
        z_scores[testable] = abs_diff[testable] / pooled_sem[testable]

        finite_z = z_scores[np.isfinite(z_scores)]
        n_testable = int(np.count_nonzero(testable))
        max_z = float(np.max(finite_z)) if finite_z.size else 0.0
        mean_z = float(np.mean(finite_z)) if finite_z.size else 0.0

        # Conservation check for the degenerate (zero-sampling-error) points.
        conserved = ~testable
        cons_tol = CONSERVATION_ATOL + CONSERVATION_RTOL * np.abs(cpu_mean)
        cons_violations = conserved & (abs_diff > cons_tol)
        n_conserved = int(np.count_nonzero(conserved))
        n_cons_violations = int(np.count_nonzero(cons_violations))

        print(f"\nObservable '{obs}':")
        print(
            f"  CPU Mean: start={cpu_mean[0]:.3f}, mid={cpu_mean[len(cpu_mean) // 2]:.3f}, end={cpu_mean[-1]:.3f}"
        )
        print(
            f"  GPU Mean: start={gpu_mean[0]:.3f}, mid={gpu_mean[len(gpu_mean) // 2]:.3f}, end={gpu_mean[-1]:.3f}"
        )
        print(
            f"  CPU Std : start={cpu_std[0]:.3f}, mid={cpu_std[len(cpu_std) // 2]:.3f}, end={cpu_std[-1]:.3f}"
        )
        print(
            f"  GPU Std : start={gpu_std[0]:.3f}, mid={gpu_std[len(gpu_std) // 2]:.3f}, end={gpu_std[-1]:.3f}"
        )
        print(
            f"  Max |Z| across {n_testable}/{cpu_mean.size} testable points: {max_z:.2f} (mean |Z|={mean_z:.2f})"
        )
        if n_conserved:
            worst_c = float(np.max(abs_diff[conserved]))
            print(
                f"  {n_conserved} conserved point(s) compared absolutely: max |CPU-GPU| = {worst_c:.3e} (atol {CONSERVATION_ATOL:g})"
            )

        failed = False
        if n_testable and max_z > Z_THRESHOLD:
            print(f"  [FAIL] Max |Z| {max_z:.2f} exceeded threshold {Z_THRESHOLD}")
            failed = True
        if n_cons_violations:
            worst_idx = int(np.argmax(np.where(cons_violations, abs_diff, -1.0)))
            print(
                f"  [FAIL] Conserved observable '{obs}' diverges by {abs_diff[worst_idx]:.3e} at "
                f"t={time_points[worst_idx]:.6g} (CPU={cpu_mean[worst_idx]:.6f}, "
                f"GPU={gpu_mean[worst_idx]:.6f}, tol {cons_tol[worst_idx]:.3e}) across "
                f"{n_cons_violations} point(s) -- conservation/stoichiometry mismatch"
            )
            failed = True
        if not failed:
            # Report only the checks that actually ran. `max_z` defaults to 0.0
            # when no point is testable, so a message that always cites it
            # claims a mean-trajectory Z-test on a model where every observable
            # is conserved and the Z-test examined nothing. Measured on
            # models/toy-jim.bngl, 6 of 9 observables are exactly that case.
            # The conserved-point comparison above still ran and is the
            # stronger check; it is what this PASS is reporting.
            if n_testable:
                print(
                    f"  [PASS] Mean trajectory matches CPU within sampling error "
                    f"(max |Z| {max_z:.2f} < {Z_THRESHOLD}) and conserved points agree"
                )
            else:
                print(
                    f"  [PASS] Conserved points agree; the mean-trajectory Z-test "
                    f"examined nothing because all {cpu_mean.size} points have zero "
                    f"sampling error (max |Z| reported as 0.00 is the empty-set "
                    f"default, not a measurement)"
                )
        all_passed = all_passed and not failed

    # 2. Compare final distributions using Two-Sample Kolmogorov-Smirnov Test
    if "final_observables" in cpu_res and "final_observables" in gpu_res:
        cpu_finals = np.array(cpu_res["final_observables"])
        gpu_finals = np.array(gpu_res["final_observables"])

        print("\nTwo-Sample Kolmogorov-Smirnov Tests at t_end:")
        for idx, obs in enumerate(obs_names):
            c_samp = cpu_finals[:, idx]
            g_samp = gpu_finals[:, idx]

            c_const = float(np.std(c_samp)) < 1e-6
            g_const = float(np.std(g_samp)) < 1e-6

            if c_const and g_const:
                # Both samples are a single repeated value, so KS carries no
                # information. The meaningful check is that the conserved value
                # itself agrees between CPU and GPU.
                diff = abs(float(c_samp[0]) - float(g_samp[0]))
                if diff > CONSERVATION_ATOL:
                    print(
                        f"  '{obs}': [FAIL] conserved value differs on CPU/GPU: "
                        f"{float(c_samp[0]):.6f} vs {float(g_samp[0]):.6f} "
                        f"(|diff|={diff:.3e} > {CONSERVATION_ATOL:g})"
                    )
                    all_passed = False
                else:
                    print(
                        f"  '{obs}': Conserved constant value {float(c_samp[0]):.1f} on both "
                        f"CPU and GPU (|diff|={diff:.1e}). [PASS]"
                    )
                continue

            # At least one sample varies, so run the real two-sample KS test.
            # A degenerate sample on one side is a genuine distributional
            # difference and must be allowed to fail here.
            # Molecule counts are discrete and heavily tied, so the exact KS
            # method does not apply; the asymptotic method is valid and
            # conservative for discrete samples.
            ks = stats.ks_2samp(c_samp, g_samp, method="asymp")
            c_sd = float(np.std(c_samp))
            g_sd = float(np.std(g_samp))
            if not np.isfinite([ks.statistic, ks.pvalue]).all() or ks.pvalue < KS_ALPHA:
                print(
                    f"  '{obs}': [FAIL] KS D={ks.statistic:.4f}, p={ks.pvalue:.3e} "
                    f"< {KS_ALPHA:g} (CPU std={c_sd:.4f}, GPU std={g_sd:.4f}) "
                    f"-- CPU and GPU final-state distributions differ"
                )
                all_passed = False
            else:
                print(
                    f"  '{obs}': KS D={ks.statistic:.4f}, p={ks.pvalue:.4f} "
                    f">= {KS_ALPHA:g} (CPU std={c_sd:.4f}, GPU std={g_sd:.4f}). [PASS]"
                )
    # 3. If isomerization, also test against analytical Binomial(N=20, p=1/6) using Chi-Square test
    if name == "isomerization":
        print("\nExact Analytical Parity Check for Isomerization (Binomial(20, 1/6)):")
        t_idx = list(obs_names).index("A_confT")
        c_t = cpu_finals[:, t_idx]
        g_t = gpu_finals[:, t_idx]

        N_mol = 20
        p_t = 0.2 / 1.2  # 1/6
        expected_mean = N_mol * p_t
        expected_var = N_mol * p_t * (1.0 - p_t)

        print(
            f"  Theoretical: Mean = {expected_mean:.4f}, Variance = {expected_var:.4f}"
        )
        print(f"  CPU Sample : Mean = {np.mean(c_t):.4f}, Variance = {np.var(c_t):.4f}")
        print(f"  GPU Sample : Mean = {np.mean(g_t):.4f}, Variance = {np.var(g_t):.4f}")

        # Binomial probabilities for k = 0..8, and 9..20
        p_bins = [
            math.comb(20, k) * (p_t**k) * ((1 - p_t) ** (20 - k)) for k in range(9)
        ]
        p_bins.append(1.0 - sum(p_bins))  # 9-20
        expected_counts = np.array(p_bins) * batch_size

        def get_bin_counts(sample):
            counts = np.zeros(10)
            for val in sample:
                k = int(round(val))
                if k < 9:
                    counts[k] += 1
                else:
                    counts[9] += 1
            return counts

        c_counts = get_bin_counts(c_t)
        g_counts = get_bin_counts(g_t)

        chi2_cpu, p_cpu = stats.chisquare(c_counts, expected_counts)
        chi2_gpu, p_gpu = stats.chisquare(g_counts, expected_counts)
        assert np.isfinite(
            [chi2_cpu, p_cpu, chi2_gpu, p_gpu]
        ).all(), "nonfinite analytical comparison"

        print(f"  CPU Chi-square = {chi2_cpu:.2f}, p-value = {p_cpu:.4f}")
        print(f"  GPU Chi-square = {chi2_gpu:.2f}, p-value = {p_gpu:.4f}")

        if p_gpu < 0.01:
            print(
                "  [FAIL] GPU sample deviates significantly from theoretical binomial distribution"
            )
            all_passed = False
        else:
            print(
                f"  [PASS] GPU sample matches exact analytical binomial distribution (p={p_gpu:.4f} >= 0.01)"
            )

    return all_passed


def run_gpu_parity_gate(*, backend="auto", require_device=False, report=None):
    print("=" * 70)
    print("Batch SSA GPU parity gate")
    print("=" * 70)

    inventory = cpp.gpu_backends()
    selected = cpp.default_gpu_backend() if backend == "auto" else backend
    if report is None:
        report = {}
    report.update(backend=selected, inventory=inventory, models=[], status="NOT_TESTED")
    if not any(item["name"] == selected and item["available"] for item in inventory):
        print(
            f"[NOT_TESTED] requested GPU backend unavailable: {selected}; {inventory}"
        )
        return not require_device

    test_models = [
        ("isomerization", "models/isomerization.bngl", 20.0, 10),
        ("gene_expr_simple", "models/gene_expr_simple.bngl", 500.0, 10),
        ("toy-jim", "models/toy-jim.bngl", 50.0, 10),
        ("egfr_net", "models/performance_test_models/egfr_net.bngl", 0.02, 10),
    ]

    all_ok = True
    for name, path, t_end, n_steps in test_models:
        receipt = {"model": name, "status": "FAIL"}
        report["models"].append(receipt)
        try:
            ok = validate_model(
                name,
                path,
                t_end,
                n_steps,
                batch_size=2000,
                backend=selected,
                receipt=receipt,
            )
        except Exception as exc:
            receipt["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[FAIL] {name}: {receipt['error']}")
            ok = False
        receipt["status"] = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False

    receipt = {"model": "gpu_immigration_death", "status": "FAIL"}
    report["models"].append(receipt)
    try:
        validate_immigration_death_gpu(selected, receipt=receipt)
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] gpu_immigration_death: {receipt['error']}")
        all_ok = False

    receipt = {"model": "toy-jim-public-route", "status": "FAIL"}
    report["models"].append(receipt)
    try:
        validate_public_simulate_ssa_route(selected, receipt=receipt)
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] toy-jim-public-route: {receipt['error']}")
        all_ok = False
    report["status"] = "PASS" if all_ok else "FAIL"

    print("\n" + "=" * 70)
    if all_ok:
        print("ALL STATISTICAL PARITY TESTS PASSED SUCCESSFULLY!")
    else:
        print("SOME STATISTICAL TESTS FAILED.")
    print("=" * 70)
    return all_ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("cpu", "gpu", "all"),
        default="all",
        help=(
            "'cpu' runs the hardware-independent CPU reference gate against "
            "exact analytical results and needs no GPU; 'gpu' runs the "
            "CPU-vs-GPU comparison and skips when no backend is available; "
            "'all' (the default, and what a bare invocation has always run) "
            "runs both."
        ),
    )
    parser.add_argument("--backend", choices=("auto", "cuda", "metal"), default="auto")
    parser.add_argument(
        "--require-device",
        action="store_true",
        help="Fail instead of skipping when the requested GPU is unavailable",
    )
    parser.add_argument(
        "--json", type=Path, help="Write hardware qualification receipts"
    )
    args = parser.parse_args(argv)
    if args.mode == "cpu" and (args.require_device or args.backend != "auto"):
        parser.error("--backend and --require-device require --mode gpu or all")

    report = {
        "schema_version": 1,
        "command": [sys.executable, *sys.argv],
        "native_module": str(Path(cpp.__file__).resolve()),
        "native_sha256": hashlib.sha256(Path(cpp.__file__).read_bytes()).hexdigest(),
        "source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "source_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        ),
        "gpu": {},
    }

    def gpu_gate():
        return run_gpu_parity_gate(
            backend=args.backend,
            require_device=args.require_device,
            report=report["gpu"],
        )

    def save_report():
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report, indent=2) + "\n")

    if args.mode == "gpu":
        ok = gpu_gate()
        save_report()
        return 0 if ok else 1

    ok = run_cpu_reference_gate()
    report["cpu_passed"] = ok
    if args.mode == "all":
        ok = gpu_gate() and ok
    save_report()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
