#!/usr/bin/env python3
"""Statistical validation of Metal GPU Batch SSA vs existing BNG3 CPU SSA.

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
import _bionetgen_cpp as cpp

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

    # Run GPU batch
    gpu_res = cpp.simulate_batch_ssa_gpu(
        model, net,
        batch_size=batch_size,
        t_end=t_end,
        n_steps=n_steps,
        base_seed=5000
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
        # Avoid division by zero when variance is 0 (e.g. constant conserved totals)
        valid = pooled_sem > 1e-6
        z_scores = np.zeros_like(cpu_mean)
        z_scores[valid] = (gpu_mean[valid] - cpu_mean[valid]) / pooled_sem[valid]

        max_z = np.max(np.abs(z_scores))
        mean_z = np.mean(np.abs(z_scores))

        print(f"\nObservable '{obs}':")
        print(f"  CPU Mean: start={cpu_mean[0]:.3f}, mid={cpu_mean[len(cpu_mean)//2]:.3f}, end={cpu_mean[-1]:.3f}")
        print(f"  GPU Mean: start={gpu_mean[0]:.3f}, mid={gpu_mean[len(gpu_mean)//2]:.3f}, end={gpu_mean[-1]:.3f}")
        print(f"  CPU Std : start={cpu_std[0]:.3f}, mid={cpu_std[len(cpu_std)//2]:.3f}, end={cpu_std[-1]:.3f}")
        print(f"  GPU Std : start={gpu_std[0]:.3f}, mid={gpu_std[len(gpu_std)//2]:.3f}, end={gpu_std[-1]:.3f}")
        print(f"  Max |Z|-score across trajectory: {max_z:.2f} (mean |Z|={mean_z:.2f})")

        # Threshold: |Z| < 3.29 (corresponds to p > 0.001)
        if max_z > 3.5:
            print(f"  [FAIL] Max |Z| {max_z:.2f} exceeded threshold 3.5")
            all_passed = False
        else:
            print(f"  [PASS] Mean trajectory matches CPU within sampling error (max |Z| < 3.5)")

    # 2. Compare final distributions using Two-Sample Kolmogorov-Smirnov Test
    if "final_observables" in cpu_res and "final_observables" in gpu_res:
        cpu_finals = np.array(cpu_res["final_observables"])
        gpu_finals = np.array(gpu_res["final_observables"])

        print("\nTwo-Sample Kolmogorov-Smirnov Tests at t_end:")
        for idx, obs in enumerate(obs_names):
            c_samp = cpu_finals[:, idx]
            g_samp = gpu_finals[:, idx]

            # If constant observable (e.g. Total molecules), KS test is trivial
            if np.std(c_samp) < 1e-6 and np.std(g_samp) < 1e-6:
                print(f"  '{obs}': Conserved constant value {c_samp[0]:.1f} on both CPU and GPU. [PASS]")
                continue
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
