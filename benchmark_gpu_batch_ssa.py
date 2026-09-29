#!/usr/bin/env python3
"""Comprehensive benchmark for Batched Direct-SSA on macOS.

Compares:
1. Existing CPU implementation (single worker)
2. Existing CPU implementation (multi-core, std::thread::hardware_concurrency)
3. Metal GPU prototype

Batch sizes: 100, 1,000, 10,000
Metrics:
- Model preparation time
- Host-to-device transfer time
- Simulation time
- Device-to-host transfer time
- Total wall time
- Throughput: trajectories/sec and events/sec
- Memory usage
- Relative speedups (GPU / CPU 1W, GPU / CPU MC)
"""
import sys
import json
import time

sys.path.insert(0, 'build/cpp')
sys.path.insert(0, 'python')
import _bionetgen_cpp as cpp

BENCHMARK_MODELS = [
    {
        "id": "isomerization",
        "name": "Isomerization",
        "path": "models/isomerization.bngl",
        "t_end": 20.0,
        "n_steps": 10,
        "desc": "2 species, 2 reactions (analytical reversible equilibrium)"
    },
    {
        "id": "gene_expr_simple",
        "name": "Gene Expression",
        "path": "models/gene_expr_simple.bngl",
        "t_end": 500.0,
        "n_steps": 10,
        "desc": "2 species, 4 reactions (stochastic birth-death dynamics)"
    },
    {
        "id": "toy_jim",
        "name": "Toy-Jim Signaling",
        "path": "models/toy-jim.bngl",
        "t_end": 50.0,
        "n_steps": 10,
        "desc": "25 species, 101 reactions (receptor recruitment & phosphorylation)"
    },
    {
        "id": "egfr_net",
        "name": "EGFR Net",
        "path": "models/performance_test_models/egfr_net.bngl",
        "t_end": 0.02,
        "n_steps": 10,
        "desc": "356 species, 3749 reactions (large-scale combinatorial network)"
    }
]

BATCH_SIZES = [100, 1000, 10000]

def run_benchmark():
    print("=" * 88)
    print("BNG3 BATCHED STOCHASTIC SIMULATION (DIRECT-SSA) BENCHMARK")
    print(f"Platform: macOS Darwin arm64 | Metal Available: {cpp.is_metal_available()}")
    print(f"Batch sizes: {BATCH_SIZES}")
    print("=" * 88)

    results = []

    for model_cfg in BENCHMARK_MODELS:
        mid = model_cfg["id"]
        mname = model_cfg["name"]
        mpath = model_cfg["path"]
        t_end = model_cfg["t_end"]
        n_steps = model_cfg["n_steps"]

        print(f"\nLoading and parsing model: {mname} ({mpath})...")
        model = cpp.parse_file(mpath)
        net = cpp.generate_network(model)
        num_species = net.num_species
        num_rxns = net.num_reactions
        print(f"  Generated Network: {num_species} species, {num_rxns} reactions")

        model_results = {
            "model_id": mid,
            "model_name": mname,
            "path": mpath,
            "num_species": num_species,
            "num_reactions": num_rxns,
            "t_end": t_end,
            "n_steps": n_steps,
            "runs": []
        }

        for B in BATCH_SIZES:
            print(f"\n--- Model: {mname} | Batch size: {B:,} ---")

            # 1. CPU Single Worker
            print("  Running CPU (1 worker)...", end="", flush=True)
            cpu_sw = cpp.simulate_batch_ssa_cpu(
                model, net,
                batch_size=B,
                t_end=t_end,
                n_steps=n_steps,
                threads=1,
                base_seed=100
            )
            print(f" done ({cpu_sw['sim_time_ms']:.2f} ms sim, {cpu_sw['total_wall_time_ms']:.2f} ms wall)")

            # 2. CPU Multi-core
            print("  Running CPU (multi-core)...", end="", flush=True)
            cpu_mc = cpp.simulate_batch_ssa_cpu(
                model, net,
                batch_size=B,
                t_end=t_end,
                n_steps=n_steps,
                threads=0,
                base_seed=200
            )
            print(f" done ({cpu_mc['sim_time_ms']:.2f} ms sim, {cpu_mc['total_wall_time_ms']:.2f} ms wall)")

            # 3. Metal GPU Prototype
            print("  Running Metal GPU prototype...", end="", flush=True)
            gpu = cpp.simulate_batch_ssa_gpu(
                model, net,
                batch_size=B,
                t_end=t_end,
                n_steps=n_steps,
                base_seed=300
            )
            print(f" done ({gpu['sim_time_ms']:.2f} ms sim, {gpu['total_wall_time_ms']:.2f} ms wall)")

            # Compute speedups
            speedup_sw_sim = cpu_sw['sim_time_ms'] / max(1e-6, gpu['sim_time_ms'])
            speedup_mc_sim = cpu_mc['sim_time_ms'] / max(1e-6, gpu['sim_time_ms'])
            speedup_sw_tot = cpu_sw['total_wall_time_ms'] / max(1e-6, gpu['total_wall_time_ms'])
            speedup_mc_tot = cpu_mc['total_wall_time_ms'] / max(1e-6, gpu['total_wall_time_ms'])

            run_entry = {
                "batch_size": B,
                "cpu_sw": {
                    "model_prep_ms": cpu_sw["model_prep_time_ms"],
                    "sim_time_ms": cpu_sw["sim_time_ms"],
                    "total_wall_ms": cpu_sw["total_wall_time_ms"],
                    "total_events": cpu_sw["total_events"],
                    "traj_per_sec_sim": cpu_sw["trajectories_per_sec_sim"],
                    "traj_per_sec_tot": cpu_sw["trajectories_per_sec_total"],
                    "events_per_sec_sim": cpu_sw["events_per_sec_sim"],
                    "events_per_sec_tot": cpu_sw["events_per_sec_total"],
                    "memory_bytes": cpu_sw["memory_usage_bytes"]
                },
                "cpu_mc": {
                    "model_prep_ms": cpu_mc["model_prep_time_ms"],
                    "sim_time_ms": cpu_mc["sim_time_ms"],
                    "total_wall_ms": cpu_mc["total_wall_time_ms"],
                    "total_events": cpu_mc["total_events"],
                    "traj_per_sec_sim": cpu_mc["trajectories_per_sec_sim"],
                    "traj_per_sec_tot": cpu_mc["trajectories_per_sec_total"],
                    "events_per_sec_sim": cpu_mc["events_per_sec_sim"],
                    "events_per_sec_tot": cpu_mc["events_per_sec_total"],
                    "memory_bytes": cpu_mc["memory_usage_bytes"]
                },
                "gpu": {
                    "model_prep_ms": gpu["model_prep_time_ms"],
                    "h2d_transfer_ms": gpu["h2d_transfer_ms"],
                    "sim_time_ms": gpu["sim_time_ms"],
                    "d2h_transfer_ms": gpu["d2h_transfer_ms"],
                    "total_wall_ms": gpu["total_wall_time_ms"],
                    "total_events": gpu["total_events"],
                    "traj_per_sec_sim": gpu["trajectories_per_sec_sim"],
                    "traj_per_sec_tot": gpu["trajectories_per_sec_total"],
                    "events_per_sec_sim": gpu["events_per_sec_sim"],
                    "events_per_sec_tot": gpu["events_per_sec_total"],
                    "memory_bytes": gpu["memory_usage_bytes"]
                },
                "speedup_vs_cpu_sw_sim": speedup_sw_sim,
                "speedup_vs_cpu_mc_sim": speedup_mc_sim,
                "speedup_vs_cpu_sw_tot": speedup_sw_tot,
                "speedup_vs_cpu_mc_tot": speedup_mc_tot
            }
            model_results["runs"].append(run_entry)

            print(f"    Sim Time   : CPU-1W={cpu_sw['sim_time_ms']:8.2f} ms | CPU-MC={cpu_mc['sim_time_ms']:8.2f} ms | GPU={gpu['sim_time_ms']:8.2f} ms")
            print(f"    Wall Time  : CPU-1W={cpu_sw['total_wall_time_ms']:8.2f} ms | CPU-MC={cpu_mc['total_wall_time_ms']:8.2f} ms | GPU={gpu['total_wall_time_ms']:8.2f} ms (Prep={gpu['model_prep_time_ms']:.1f}ms, H2D={gpu['h2d_transfer_ms']:.2f}ms, D2H={gpu['d2h_transfer_ms']:.2f}ms)")
            print(f"    Traj/sec   : CPU-1W={cpu_sw['trajectories_per_sec_sim']:10.1f} | CPU-MC={cpu_mc['trajectories_per_sec_sim']:10.1f} | GPU={gpu['trajectories_per_sec_sim']:10.1f}")
            print(f"    Events/sec : CPU-1W={cpu_sw['events_per_sec_sim']:10.1e} | CPU-MC={cpu_mc['events_per_sec_sim']:10.1e} | GPU={gpu['events_per_sec_sim']:10.1e}")
            print(f"    Speedup Sim: GPU vs CPU-1W = {speedup_sw_sim:6.2f}x | GPU vs CPU-MC = {speedup_mc_sim:6.2f}x")
            print(f"    Speedup Tot: GPU vs CPU-1W = {speedup_sw_tot:6.2f}x | GPU vs CPU-MC = {speedup_mc_tot:6.2f}x")
            print(f"    GPU Memory : {gpu['memory_usage_bytes'] / (1024*1024):.2f} MB")

        results.append(model_results)

    # Save to JSON
    out_json = "benchmark_batch_ssa_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nAll benchmark results saved to {out_json}")

    return results

if __name__ == "__main__":
    run_benchmark()
