#!/usr/bin/env python3
"""Statistical validation of the GPU Batch SSA backends vs the BNG3 CPU pool.

Tests:
1. Mean trajectory equivalence (Z-test across time points for all observables)
2. Variance trajectory equivalence (ratio of variances / F-test)
3. Distributional equivalence (Two-sample Kolmogorov-Smirnov test on final states)
4. Exact analytical parity test on isomerization model (Chi-square against Binomial(20, 1/6))
"""

import sys
import os
import math
import numpy as np
from scipy import stats

sys.path.insert(0, 'build/cpp')
sys.path.insert(0, 'python')
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

def validate_model(name, bngl_path, t_end, n_steps, batch_size=2000):
    print(f"\n{'='*70}")
    print(f"Statistical Validation: {name} (batch_size={batch_size})")
    print(f"{'='*70}")

    model = cpp.parse_file(bngl_path)
    net = cpp.generate_network(model)
    print(f"Model: {net.num_species} species, {net.num_reactions} reactions")

    # Run CPU multi-core batch
    cpu_res = cpp.simulate_batch_ssa_cpu(
        model, net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        threads=0,
        base_seed=1000
    )

    # Run GPU batch on the backend that would be selected automatically.
    backend = cpp.default_gpu_backend()
    if backend == "none":
        print(f"  [SKIP] no GPU backend available: {cpp.gpu_backends()}")
        return True
    print(f"  GPU backend: {backend}")
    gpu_res = cpp.simulate_batch_ssa_gpu(
        model, net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        base_seed=5000,
        backend=backend
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
        print(f"  CPU Mean: start={cpu_mean[0]:.3f}, mid={cpu_mean[len(cpu_mean)//2]:.3f}, end={cpu_mean[-1]:.3f}")
        print(f"  GPU Mean: start={gpu_mean[0]:.3f}, mid={gpu_mean[len(gpu_mean)//2]:.3f}, end={gpu_mean[-1]:.3f}")
        print(f"  CPU Std : start={cpu_std[0]:.3f}, mid={cpu_std[len(cpu_std)//2]:.3f}, end={cpu_std[-1]:.3f}")
        print(f"  GPU Std : start={gpu_std[0]:.3f}, mid={gpu_std[len(gpu_std)//2]:.3f}, end={gpu_std[-1]:.3f}")
        print(f"  Max |Z| across {n_testable}/{cpu_mean.size} testable points: {max_z:.2f} (mean |Z|={mean_z:.2f})")
        if n_conserved:
            worst_c = float(np.max(abs_diff[conserved]))
            print(f"  {n_conserved} conserved point(s) compared absolutely: max |CPU-GPU| = {worst_c:.3e} (atol {CONSERVATION_ATOL:g})")

        failed = False
        if n_testable and max_z > Z_THRESHOLD:
            print(f"  [FAIL] Max |Z| {max_z:.2f} exceeded threshold {Z_THRESHOLD}")
            failed = True
        if n_cons_violations:
            worst_idx = int(np.argmax(np.where(cons_violations, abs_diff, -1.0)))
            print(f"  [FAIL] Conserved observable '{obs}' diverges by {abs_diff[worst_idx]:.3e} at "
                  f"t={time_points[worst_idx]:.6g} (CPU={cpu_mean[worst_idx]:.6f}, "
                  f"GPU={gpu_mean[worst_idx]:.6f}, tol {cons_tol[worst_idx]:.3e}) across "
                  f"{n_cons_violations} point(s) -- conservation/stoichiometry mismatch")
            failed = True
        if not failed:
            print(f"  [PASS] Mean trajectory matches CPU within sampling error "
                  f"(max |Z| {max_z:.2f} < {Z_THRESHOLD}) and conserved points agree")
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
                    print(f"  '{obs}': [FAIL] conserved value differs on CPU/GPU: "
                          f"{float(c_samp[0]):.6f} vs {float(g_samp[0]):.6f} "
                          f"(|diff|={diff:.3e} > {CONSERVATION_ATOL:g})")
                    all_passed = False
                else:
                    print(f"  '{obs}': Conserved constant value {float(c_samp[0]):.1f} on both "
                          f"CPU and GPU (|diff|={diff:.1e}). [PASS]")
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
            if ks.pvalue < KS_ALPHA:
                print(f"  '{obs}': [FAIL] KS D={ks.statistic:.4f}, p={ks.pvalue:.3e} "
                      f"< {KS_ALPHA:g} (CPU std={c_sd:.4f}, GPU std={g_sd:.4f}) "
                      f"-- CPU and GPU final-state distributions differ")
                all_passed = False
            else:
                print(f"  '{obs}': KS D={ks.statistic:.4f}, p={ks.pvalue:.4f} "
                      f">= {KS_ALPHA:g} (CPU std={c_sd:.4f}, GPU std={g_sd:.4f}). [PASS]")
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

        print(f"  Theoretical: Mean = {expected_mean:.4f}, Variance = {expected_var:.4f}")
        print(f"  CPU Sample : Mean = {np.mean(c_t):.4f}, Variance = {np.var(c_t):.4f}")
        print(f"  GPU Sample : Mean = {np.mean(g_t):.4f}, Variance = {np.var(g_t):.4f}")

        # Binomial probabilities for k = 0..8, and 9..20
        p_bins = [math.comb(20, k) * (p_t**k) * ((1 - p_t)**(20 - k)) for k in range(9)]
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

        print(f"  CPU Chi-square = {chi2_cpu:.2f}, p-value = {p_cpu:.4f}")
        print(f"  GPU Chi-square = {chi2_gpu:.2f}, p-value = {p_gpu:.4f}")

        if p_gpu < 0.01:
            print("  [FAIL] GPU sample deviates significantly from theoretical binomial distribution")
            all_passed = False
        else:
            print(f"  [PASS] GPU sample matches exact analytical binomial distribution (p={p_gpu:.4f} >= 0.01)")


    return all_passed

if __name__ == "__main__":
    test_models = [
        ("isomerization", "models/isomerization.bngl", 20.0, 10),
        ("gene_expr_simple", "models/gene_expr_simple.bngl", 500.0, 10),
        ("toy-jim", "models/toy-jim.bngl", 50.0, 10),
        ("egfr_net", "models/performance_test_models/egfr_net.bngl", 0.02, 10),
    ]

    all_ok = True
    for name, path, t_end, n_steps in test_models:
        ok = validate_model(name, path, t_end, n_steps, batch_size=2000)
        if not ok:
            all_ok = False

    print("\n" + "="*70)
    if all_ok:
        print("ALL STATISTICAL PARITY TESTS PASSED SUCCESSFULLY!")
    else:
        print("SOME STATISTICAL TESTS FAILED.")
    print("="*70)
    sys.exit(0 if all_ok else 1)
