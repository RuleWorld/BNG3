#!/usr/bin/env python3
"""Command-line driver for GPU stochastic-simulation benchmarking.

Every run of this program prints, before any number it goes on to report:

  1. what engine binary it loaded, and from where;
  2. which accelerator backends are compiled in and which have a usable device;
  3. the structural no-fallback verdict for the backend being measured;
  4. the host's contention state, and whether the host-wide benchmark lock was
     held for the run;
  5. the A/A null band, measured in this session against this instrument.

Only then does it report an effect. An effect that falls inside the null band is
printed as indistinguishable, with the band's width shown next to it, because the
number of times a measurement like that has been read as a win on a shared host
is the reason this driver exists.

Examples
--------
Measure the host pool against the default accelerator backend:

    python3 benchmarks/gpu/run_gpu_bench.py --arms cpu:0,gpu

Measure a synthetic network of a chosen size and event density, calibrating the
density by measurement rather than by assumption:

    python3 benchmarks/gpu/run_gpu_bench.py --arms cpu:0,gpu \\
        --synthetic --reactions 256 --event-density 400

Run the instrument against itself to see its noise floor and nothing else:

    python3 benchmarks/gpu/run_gpu_bench.py --arms gpu --self-test

Check that this binary cannot produce an accelerator-labelled result that came
from the host, and exit non-zero if it can:

    python3 benchmarks/gpu/run_gpu_bench.py --verify-no-fallback

Exit status
-----------
    0   the run completed and every guard held
    2   a guard failed: a silent fallback was possible, a requested backend was
        unusable, or a device assertion did not hold
    3   usage error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpu import arms as arms_mod  # noqa: E402
from gpu import (  # noqa: E402
    BenchmarkSlot,
    ContentionTrace,
    DeviceAssertionError,
    MeasurementConfig,
    ModelSpec,
    PairedTimer,
    TimingSample,
    calibrate_event_density,
    capability_report,
    contention_caveat,
    engine_fails_closed,
    finish_host_facts,
    host_facts,
    judge,
    shape_grid,
    single_precision_device_note,
    summarise,
    write_trace,
)
from gpu.arms import BatchConfig, assert_no_silent_fallback  # noqa: E402
from gpu.engine_import import load_engine, usable_backend  # noqa: E402
from gpu.equivalence import compare_runs  # noqa: E402

BAR = "=" * 78
SUB = "-" * 78


def _p(msg: str = "") -> None:
    print(msg, flush=True)


def _heading(text: str) -> None:
    _p()
    _p(BAR)
    _p(text)
    _p(BAR)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="run_gpu_bench",
        description="Trustworthy A/B benchmarking for GPU stochastic simulation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--arms",
        default="cpu:0,gpu",
        help="comma-separated arms: cpu, cpu:N, gpu, metal, cuda",
    )
    ap.add_argument(
        "--model",
        default=None,
        help="path to a .bngl model (default: the two shipped fixtures)",
    )
    ap.add_argument("--batch", type=int, default=2000, help="trajectories per arm")
    ap.add_argument(
        "--t-end",
        type=float,
        default=None,
        help="simulation horizon (default: the model's benchmark value)",
    )
    ap.add_argument("--n-steps", type=int, default=10, help="output grid points")
    ap.add_argument(
        "--seed",
        type=int,
        default=12345,
        help="base seed; identical for both arms by construction",
    )
    ap.add_argument(
        "--rounds",
        type=int,
        default=7,
        help="paired A/B rounds (odd is better: alternation balances)",
    )
    ap.add_argument(
        "--warmups", type=int, default=2, help="untimed warmup invocations per arm"
    )
    ap.add_argument(
        "--no-null",
        action="store_true",
        help="DISABLE the A/A null (the report will say so)",
    )
    ap.add_argument(
        "--null-rounds",
        type=int,
        default=0,
        help="A/A rounds (default: same as --rounds)",
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="run arm A against itself; prints only the null band",
    )
    ap.add_argument(
        "--synthetic",
        action="store_true",
        help="generate a synthetic network instead of reading a model",
    )
    ap.add_argument(
        "--reactions", type=int, default=64, help="synthetic network reaction count"
    )
    ap.add_argument(
        "--species", type=int, default=16, help="synthetic network species count"
    )
    ap.add_argument(
        "--event-density",
        type=float,
        default=200.0,
        help="target SSA events per trajectory for a synthetic network",
    )
    ap.add_argument(
        "--sweep",
        action="store_true",
        help="sweep a ladder of synthetic reaction counts",
    )
    ap.add_argument(
        "--sweep-reactions",
        default="2,4,16,64,256,1024",
        help="reaction counts for --sweep",
    )
    ap.add_argument(
        "--equivalence",
        action="store_true",
        help="also run the statistical equivalence comparison",
    )
    ap.add_argument(
        "--alpha",
        type=float,
        default=0.001,
        help="family-wise error rate for the equivalence tests",
    )
    ap.add_argument(
        "--verify-no-fallback",
        action="store_true",
        help="probe for silent fallback and exit",
    )
    ap.add_argument(
        "--agent",
        default="gpuharness",
        help="agent name, for the host-wide benchmark lock",
    )
    ap.add_argument(
        "--no-lock",
        action="store_true",
        help="do not take the host-wide benchmark lock",
    )
    ap.add_argument(
        "--json",
        dest="json_out",
        default=None,
        help="write the full report to this path",
    )
    ap.add_argument(
        "--engine-dir",
        default=None,
        help="directory holding _bionetgen_cpp (or BIONETGEN_CPP_DIR)",
    )
    ap.add_argument(
        "--model-dir", default=None, help="directory for generated .bngl files"
    )
    return ap


#: Models used when none is named. Both are tiny by design: they are the
#: fixtures the previous GPU numbers were drawn from, and measuring them again
#: under a trustworthy instrument is how those numbers can be compared to new
#: ones.
FIXTURES = [
    ("isomerization", "models/isomerization.bngl", 20.0),
    ("gene_expr_simple", "models/gene_expr_simple.bngl", 500.0),
]


def repo_root() -> str:
    from gpu.engine_import import repo_root as _root

    return _root()


def _wrap(text: str, width: int) -> list[str]:
    """Wrap a paragraph for the fixed-width report body."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def print_capabilities(cpp: Any) -> dict[str, Any]:
    """Print and return what this host can do on an accelerator."""
    report = capability_report(cpp)
    _heading("HOST AND DEVICE CAPABILITY")
    _p(f"engine       : {report['engine_source']}")
    for entry in report["engine_backends"]:
        _p(
            f"backend      : {entry['name']:<6} compiled={entry['compiled']!s:<5} "
            f"available={entry['available']!s:<5} {entry['detail']}"
        )
    _p(f"default      : {report['default_backend']}")
    for name in ("jax", "torch"):
        info = report.get(name, {})
        if info.get("error"):
            _p(f"{name:<13}: unavailable ({info['error']})")
        else:
            _p(
                f"{name:<13}: devices={info.get('devices')} "
                f"backend={info.get('backend_reported')}"
            )
    _p()
    _p("Device limits that constrain every number in this report:")
    for key, text in report["known_device_limits"].items():
        _p(f"  - {key}: {text}")
    return report


def verify_no_fallback(
    cpp: Any, backend: str, model: Any = None, network: Any = None
) -> int:
    """Probe for silent fallback and print a verdict. Exit 2 if unsubstantiated.

    The model and network are required for the probe to mean anything: the
    fail-closed check issues a real `simulate_batch_ssa_gpu` call, and without a
    model that call would fail on its argument list instead of on backend
    selection. A probe that cannot run is reported as untested, never as a pass.
    """
    _heading("NO-FALLBACK VERIFICATION")
    probe = assert_no_silent_fallback(cpp, backend, model, network)
    _p(f"backend requested        : {probe['backend']}")
    _p(f"compiled into this binary: {probe['compiled']}")
    _p(f"usable device present    : {probe['available']} ({probe['device']})")
    _p(f"fails closed on bad ask  : {probe['fails_closed']}")
    _p(f"  probe result           : {probe['fail_closed_probe']}")
    _p(f"auto resolves to         : {probe['auto_resolves_to']}")
    _p()
    if probe["no_silent_fallback"]:
        _p("VERDICT: PASS. An accelerator result from this binary is attributable")
        _p("         to a device; a host substitution is structurally excluded.")
        return 0
    _p("VERDICT: FAIL. This binary cannot demonstrate that an accelerator result")
    _p("         came from a device. Any speedup measured with it would be")
    _p("         indistinguishable from a host run and must not be quoted.")
    return 2


def prepare_model(
    args: argparse.Namespace, cpp: Any
) -> tuple[Any, Any, dict[str, Any]]:
    """Resolve the model to measure, returning (model, network, description)."""
    if args.model:
        path = args.model
        if not os.path.isabs(path):
            path = os.path.join(repo_root(), path)
        model = cpp.parse_file(path)
        network = cpp.generate_network(model)
        t_end = args.t_end if args.t_end is not None else 10.0
        info = {
            "source": "file",
            "path": path,
            "t_end": t_end,
            "S": network.num_species,
            "R": network.num_reactions,
            "event_density_target": None,
        }
        return model, network, info

    if args.synthetic or args.sweep:
        spec = shape_models(
            args.reactions,
            args.event_density,
            species=args.species,
            t_end=args.t_end if args.t_end is not None else 1.0,
        )
        calib = calibrate_event_density(spec, directory=args.model_dir)
        model = cpp.parse_file(calib.path)
        network = cpp.generate_network(model)
        info = {
            "source": "synthetic",
            "path": calib.path,
            "t_end": calib.spec.t_end,
            "S": network.num_species,
            "R": network.num_reactions,
            "calibration": calib.as_dict(),
        }
        return model, network, info

    name, rel, default_t = FIXTURES[0]
    path = os.path.join(repo_root(), rel)
    model = cpp.parse_file(path)
    network = cpp.generate_network(model)
    info = {
        "source": "fixture",
        "path": path,
        "t_end": args.t_end if args.t_end is not None else default_t,
        "S": network.num_species,
        "R": network.num_reactions,
        "event_density_target": None,
    }
    return model, network, info


def primary_metric(report: dict[str, Any]) -> str:
    """The clock this run's verdict is taken on.

    Taken from the report rather than hardcoded, because the harness picks the
    first *usable* contention-immune clock: child CPU time for a subprocess
    arm, this process's own CPU time for an in-process one. Hardcoding
    `child_cpu_s` would print an empty verdict for an in-process arm, which is
    exactly the kind of confident-looking nothing this harness exists to stop.
    """
    return report.get("primary_metric", "child_cpu_s")


def print_null_band(report: dict[str, Any], metric: str | None = None) -> None:
    """Print the instrument's noise floor, before any effect is discussed."""
    metric = metric or primary_metric(report)
    null = report["null_summary"].get(metric, {})
    _heading("A/A NULL BAND (the instrument measured against itself)")
    if not null.get("n"):
        _p("NO NULL WAS MEASURED.")
        _p("Every number below is unlicensed. The A/A null is on by default;")
        _p("passing --no-null suppresses it, and a result produced that way must")
        _p("be reported as having no measured noise floor.")
        return
    _p(f"clock                   : {metric} (contention-immune; wall clock is")
    _p("                         recorded but never decides a verdict)")
    _p(f"null rounds              : {null['n']}")
    _p(f"ratio B/A  median        : {null['median']:.4f}")
    _p(f"ratio B/A  p10 - p90     : {null['p10']:.4f} - {null['p90']:.4f}")
    _p(f"ratio B/A  min - max     : {null['min']:.4f} - {null['max']:.4f}")
    _p(f"ratio B/A  spread        : {null['spread']:.4f}x")
    floor = report.get("null_band_floor_halfwidth", 0.0)
    if report.get("null_band_floor_applied", {}).get(metric):
        _p()
        _p(f"NOTE: this band was widened to the configured floor (+/-{floor:.1%}).")
        _p("      The instrument could not resolve better than that this run, so")
        _p("      this is a FLOOR, not a measured noise floor: more rounds or a")
        _p("      quieter host are needed before a smaller effect is claimable.")
    band_pct = 100.0 * (null["p90"] - null["p10"]) / 2.0
    _p()
    _p(f"=> On THIS host, THIS binary, THIS session, the instrument cannot")
    _p(f"   distinguish a {band_pct:.1f}% difference on {metric}. An effect smaller")
    _p("   than that band is not a result; it is the noise floor.")


def print_effect(report: dict[str, Any]) -> None:
    """Print per-round raw deltas and the verdict, never a bare ratio."""
    metric = primary_metric(report)
    other = "wall_s" if metric != "wall_s" else "self_cpu_s"
    _heading("RAW PER-ROUND PAIRED DELTAS (no min-of-K anywhere)")
    _p(f"deciding clock: {metric}; {other} shown alongside for divergence only")
    _p()
    _p(
        f"{'rnd':>3} {'order':>6} | {f'A {metric}':>14} {f'B {metric}':>14} {'B/A':>8}"
        f" | {f'A {other}':>12} {f'B {other}':>12} {'B/A':>8}"
    )

    def row(rnd: dict[str, Any]) -> str:
        ratios = rnd["ratios"]
        m = ratios.get(metric, float("nan"))
        o = ratios.get(other, float("nan"))
        return (
            f"{rnd['index']:>3} {rnd['order']:>6} | "
            f"{rnd['a'][metric]:>14.6f} {rnd['b'][metric]:>14.6f} {m:>8.4f}"
            f" | {rnd['a'][other]:>12.4f} {rnd['b'][other]:>12.4f} {o:>8.4f}"
        )

    for rnd in report["rounds"]:
        _p(row(rnd))
    if report["null_rounds"]:
        _p()
        _p("null rounds (arm A against itself - this is the noise floor, raw):")
        for rnd in report["null_rounds"]:
            _p(row(rnd))
    _p()
    _p("execution order (alternating, so monotone drift lands on both arms):")
    for entry in report["order_log"]:
        _p(f"  {entry}")

    _heading("VERDICT")
    primary = report["verdicts"][metric]
    _p(f"arms: {report['arm_a']} (A) vs {report['arm_b']} (B)")
    _p(f"deciding clock: {metric}")
    _p(f"  effect B/A          : {primary['effect_ratio_b_over_a']:.4f}")
    _p(
        f"  A/A null band       : [{primary['null_band'][0]:.4f}, "
        f"{primary['null_band'][1]:.4f}]"
    )
    _p(f"  rounds / null rounds: {primary['n_rounds']} / {primary['n_null_rounds']}")
    _p(f"  clears the band     : {primary['clears_null']}")
    _p(f"  verdict             : {primary['verdict']}")
    _p()
    _p("supporting metrics (reported so a divergence is visible, not hidden):")
    for name, verdict in report["verdicts"].items():
        if name == metric:
            continue
        band = verdict["null_band"]
        band_txt = "none" if band[0] != band[0] else f"[{band[0]:.4f}, {band[1]:.4f}]"
        _p(
            f"  {name:<12} effect={verdict['effect_ratio_b_over_a']:.4f} "
            f"band={band_txt} clears={verdict['clears_null']}"
        )

    divergence = report.get("clock_divergence")
    if divergence:
        _p()
        _heading("CROSS-CLOCK CHECK (does the other clock agree?)")
        _p(
            f"host-resource clock ({metric}): {divergence['cpu_direction']:<12} "
            f"effect={divergence['cpu_effect']:.4f} "
            f"clears_null={divergence['cpu_clears_null']}"
        )
        _p(
            f"elapsed-time clock (wall)  : {divergence['wall_direction']:<12} "
            f"effect={divergence['wall_effect']:.4f} "
            f"clears_null={divergence['wall_clears_null']}"
        )
        _p()
        for line in _wrap(divergence["verdict"], 74):
            _p(f"  {line}")
        if not divergence["licenses_speedup_claim"]:
            _p()
            _p("*** NO SINGLE SPEEDUP NUMBER IS LICENSED BY THIS RUN. ***")

    if not primary["clears_null"]:
        _p()
        _p("*** The effect on the deciding clock is INSIDE the measured noise")
        _p("*** floor. Reporting it as a speedup or a regression would be false.")
        _p("*** What to do instead: more rounds, a quieter host, or a model with")
        _p("*** more work per trajectory. An effect this size is not knowable")
        _p("*** from this instrument on this host.")


def run_one(
    args: argparse.Namespace,
    cpp: Any,
    model: Any,
    network: Any,
    info: dict[str, Any],
    trace: ContentionTrace,
    capabilities: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Measure one model and return (report, exit status)."""
    cfg = BatchConfig(
        batch_size=args.batch,
        t_end=info["t_end"],
        n_steps=args.n_steps,
        base_seed=args.seed,
    )
    _heading("MODEL UNDER TEST")
    _p(f"source         : {info['source']}  {info.get('path', '')}")
    _p(f"species/reacts : S={info['S']} R={info['R']}")
    _p(f"batch          : {cfg.batch_size} trajectories")
    _p(f"horizon        : t_end={cfg.t_end:g}  n_steps={cfg.n_steps}")
    _p(f"seed           : {cfg.base_seed} (identical for every arm)")
    if info.get("calibration"):
        cal = info["calibration"]
        _p(
            f"calibration    : target {cal['target_density']:.1f} ev/traj -> "
            f"achieved {cal['achieved_density']:.1f} ev/traj "
            f"({cal['iterations']} probe rounds, converged={cal['converged']})"
        )
        if not cal["converged"]:
            _p("                 (density is MEASURED, not assumed; a target the")
            _p("                  network cannot reach is reported, not hidden)")
    elif info.get("event_density_target") is None and info["source"] == "fixture":
        _p("density        : measured from the run itself (see total_events below)")
    trace.mark()

    arm_list, arm_notes = arms_mod.build_arms(cfg, args.arms, cpp=cpp)
    _p(f"arms           : {', '.join(arm_notes)}")

    # Prepare every arm outside the timed region: parsing, network generation
    # and device flattening are setup, not workload, and are identical for both
    # arms, so charging them to the measurement only dilutes the ratio.
    for arm in arm_list:
        arm.prepare(model, network)
    trace.mark()

    payload_a = None
    device_reports: list[dict[str, Any]] = []
    precision_notes: list[str] = []

    if args.self_test:
        # Arm A against itself. Nothing else is measured; the point is the band.
        arm = arm_list[0]
        timer = PairedTimer(
            runner=lambda _label: (arm.run(model, network).sample, None),
            config=MeasurementConfig(
                rounds=args.rounds,
                warmups=args.warmups,
                null=True,
                null_rounds=args.null_rounds or args.rounds,
            ),
        )
        _p()
        _p("SELF-TEST: arm A measured against itself. No effect is reported;")
        _p("only the instrument's noise floor.")
        report = timer.run(arm.label, arm.label)
        report["self_test"] = True
        trace.mark()
        print_null_band(report)
        return {"self_test": report, "info": info}, 0

    if len(arm_list) < 2:
        _p("only one arm selected: nothing to compare. Pass two arms, e.g. cpu:0,gpu")
        return {}, 3

    arm_a, arm_b = arm_list[0], arm_list[1]

    def runner(label: str):
        """Run the arm named `label`, capturing its result and assertions."""
        arm = arm_b if label == arm_b.label else arm_a
        result = arm.run(model, network)
        if arm is arm_a:
            payload_a_local = result
            return result.sample, result
        return result.sample, result

    last: dict[str, Any] = {}

    def runner_traced(label: str):
        trace.mark()
        sample, payload = runner(label)
        last[label] = payload
        return sample, payload

    timer = PairedTimer(
        runner=runner_traced,
        config=MeasurementConfig(
            rounds=args.rounds,
            warmups=args.warmups,
            null=not args.no_null,
            null_rounds=args.null_rounds,
        ),
    )
    _p()
    _p(
        f"measuring {arm_a.label} against {arm_b.label}, {args.rounds} paired rounds,"
        f" order alternating."
    )
    report = timer.run(arm_a.label, arm_b.label)

    # Collect the assertions and precision facts from the last invocation of
    # each arm; they are properties of the arm, not of the round.
    for arm in arm_list:
        claim = getattr(arm, "device_claim", None)
        if claim is not None:
            entry = claim.as_dict()
            entry["fail_closed_probe"] = getattr(arm, "fail_closed_probe", None)
            device_reports.append(entry)
    if arm_b.device_claim is not None:
        try:
            arm_b.device_claim.require_gpu()
        except DeviceAssertionError as exc:
            _p(f"DEVICE ASSERTION FAILED: {exc}")
            report["device_assertion_failure"] = str(exc)
            return {"report": report, "info": info}, 2

    equivalence = None
    if args.equivalence:
        a_payload = last.get(arm_a.label)
        b_payload = last.get(arm_b.label)
        if a_payload and b_payload:
            equivalence = compare_runs(
                a_payload.payload, b_payload.payload, alpha=args.alpha
            ).as_dict()
            equivalence["device_precision"] = single_precision_device_note()

    result_a = last.get(arm_a.label)
    result_b = last.get(arm_b.label)
    payload = {
        "harness_version": __import__("gpu").HARNESS_VERSION,
        "host": finish_host_facts(host_facts()),
        "capabilities": capabilities,
        "model": info,
        "config": {
            **cfg.as_dict(),
            "arms": arm_notes,
            "rounds": args.rounds,
            "warmups": args.warmups,
            "null_enabled": not args.no_null,
        },
        "measurement": report,
        "device_assertions": device_reports,
        "equivalence": equivalence,
        "total_events": {
            arm_a.label: getattr(result_a, "payload", {})
            and result_a.payload.get("total_events"),
            arm_b.label: getattr(result_b, "payload", {})
            and result_b.payload.get("total_events"),
        },
    }
    if result_a and result_a.payload and result_a.payload.get("total_events"):
        events = result_a.payload["total_events"]
        payload["events_per_trajectory"] = events / float(cfg.batch_size)
        _p(
            f"measured density: {payload['events_per_trajectory']:.1f} SSA events "
            f"per trajectory ({events} events over {cfg.batch_size} trajectories)"
        )
    if result_a and result_a.precision is not None:
        payload["host_precision"] = result_a.precision.comparability()
        if result_b and result_b.precision is not None:
            payload["device_precision"] = result_b.precision.comparability()
    payload["contention"] = trace.summary()

    print_null_band(report)
    print_effect(report)
    _p()
    _p("host contention during this run:")
    _p(f"  {trace.summary().get('interpretation', 'not recorded')}")

    if args.equivalence and equivalence is not None:
        _heading("STATISTICAL EQUIVALENCE")
        _p(f"claim                    : {equivalence['claim']}")
        _p(
            f"trajectories per side    : {equivalence['n_trajectories_a']} / "
            f"{equivalence['n_trajectories_b']}"
        )
        _p(f"test power               : {equivalence['test_power_label']}")
        _p(f"detectable difference    : {equivalence['detectable_effect_size']}")
        _p(f"max |z| across cells     : {equivalence['max_abs_z']:.4f}")
        _p(f"threshold (Bonferroni)   : {equivalence['z_threshold']:.4f}")
        _p(
            f"cells passing            : {equivalence['z_passes']} / "
            f"{equivalence['z_cells']}"
        )
        for note in equivalence["notes"]:
            _p(f"  - {note}")
        for ks in equivalence["ks_results"]:
            _p(
                f"  KS {ks['observable']:<16} D={ks['statistic']:.5f} "
                f"p={ks['p_value']:.4g} passes={ks['passes']}"
            )
        for mom in equivalence["moment_results"]:
            if mom.get("testable"):
                _p(
                    f"  moment {mom['observable']:<13} "
                    f"mean_rel_err={mom['mean_rel_error']:.5f} "
                    f"var_ratio={mom['variance_ratio']:.4f} "
                    f"passes={mom['passes']}"
                )
        _p()
        _p("This is distributional agreement at the power stated above. It is not")
        _p("a demonstration that the two arms are the same computation: they use")
        _p("different random streams and, on this device, different precision.")

    status = 0
    primary = report["verdicts"][primary_metric(report)]
    if not primary["clears_null"] and not args.no_null:
        # Not a failure: a null result is a valid result. The exit status
        # reflects whether the run was trustworthy, not whether it found a win.
        payload["outcome"] = "INDISTINGUISHABLE_FROM_NOISE"
    elif primary["clears_null"]:
        payload["outcome"] = primary["verdict"]
    return payload, status


def run_sweep(
    args: argparse.Namespace,
    cpp: Any,
    trace: ContentionTrace,
    capabilities: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Sweep a ladder of synthetic reaction counts and report the crossover."""
    counts = [int(x) for x in args.sweep_reactions.split(",") if x.strip()]
    _heading("SYNTHETIC LADDER: reactions vs measured effect")
    _p("Each rung calibrates its own event density by measurement, then measures")
    _p("the same pair of arms. The crossover, if there is one, appears as the")
    _p("first rung whose effect clears its own null band.")
    _p()
    _p(
        f"{'R':>6} {'ev/traj':>8} {'B/A cpu':>9} {'null band':>18} {'clears':>7}  verdict"
    )
    rungs: list[dict[str, Any]] = []
    status = 0
    for r in counts:
        spec = shape_models(
            r,
            args.event_density,
            species=args.species,
            t_end=args.t_end if args.t_end is not None else 1.0,
        )
        calib = calibrate_event_density(spec, directory=args.model_dir)
        sub = argparse.Namespace(**vars(args))
        sub.synthetic = True
        sub.reactions = r
        info = {
            "source": "synthetic",
            "path": calib.path,
            "t_end": calib.spec.t_end,
            "S": 0,
            "R": r,
            "calibration": calib.as_dict(),
        }
        model = cpp.parse_file(calib.path)
        network = cpp.generate_network(model)
        info["S"] = network.num_species
        payload, st = run_one(sub, cpp, model, network, info, trace, capabilities)
        status |= st
        meas = payload.get("measurement") or {}
        verdict = meas.get("verdicts", {}).get(primary_metric(meas))
        if verdict is None:
            continue
        band = verdict["null_band"]
        eff = verdict["effect_ratio_b_over_a"]
        clr = verdict["clears_null"]
        dens = payload.get("events_per_trajectory")
        rungs.append(
            {
                "R": r,
                "events_per_trajectory": dens,
                "effect": eff,
                "band": band,
                "clears": clr,
                "achieved_density": calib.achieved_density,
            }
        )
        _p(
            f"{r:>6} {(dens or 0):>8.1f} {eff:>9.4f} "
            f"{f'[{band[0]:.3f}, {band[1]:.3f}]':>18} {str(clr):>7}  "
            f"{verdict['verdict']}"
        )
        trace.mark()
    return {"sweep": rungs}, status


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rounds < 1:
        _p("--rounds must be >= 1")
        return 3
    if args.warmups < 0:
        _p("--warmups must be >= 0")
        return 3

    engine_dir = args.engine_dir or os.environ.get("BIONETGEN_CPP_DIR")
    try:
        resolved = load_engine(engine_dir)
    except RuntimeError as exc:
        _p(str(exc))
        return 2
    cpp = resolved.module

    trace = ContentionTrace()
    trace.mark()

    capabilities = print_capabilities(cpp)

    if args.verify_no_fallback:
        # The alias 'gpu' is not a backend name the engine accepts, so it is
        # resolved to the concrete backend first. Passing 'gpu' straight through
        # would fail on the spelling rather than on anything real, which is
        # exactly the kind of guard failure this check exists to rule out.
        requested = "auto"
        for token in args.arms.split(","):
            token = token.strip()
            if token in ("gpu", "metal", "cuda", "auto"):
                requested = token
                break
        try:
            backend = arms_mod.resolve_backend_name(cpp, requested)
        except RuntimeError as exc:
            _p(str(exc))
            _p("This is the finding: no accelerator is usable on this host, so no")
            _p("GPU number can be produced here. Report it; do not substitute a")
            _p("host measurement under a device label.")
            return 2
        # The probe needs a real model and network; a cheap fixture is used
        # because the check is about backend selection, not about the model.
        try:
            probe_model = cpp.parse_file(os.path.join(repo_root(), FIXTURES[0][1]))
            probe_network = cpp.generate_network(probe_model)
        except Exception as exc:  # noqa: BLE001
            _p(f"could not load a model for the fail-closed probe: {exc}")
            return 2
        return verify_no_fallback(cpp, backend, probe_model, probe_network)

    # The host-wide lock is taken for the whole measurement, not per round:
    # a lock released between rounds would serialise nothing.
    with BenchmarkSlot(
        agent=args.agent,
        what=f"gpu bench {args.arms} batch={args.batch}",
        enabled=not args.no_lock,
    ) as slot:
        trace.lock_path = slot.path
        trace.lock_held = bool(slot.token)
        trace.lock_detail = slot.detail
        _p()
        _p(f"benchmark lock: {slot.detail}")

        if args.sweep:
            payload, status = run_sweep(args, cpp, trace, capabilities)
        else:
            try:
                model, network, info = prepare_model(args, cpp)
            except Exception as exc:  # noqa: BLE001 - surface model errors plainly
                _p(f"could not prepare the model: {type(exc).__name__}: {exc}")
                return 2
            try:
                payload, status = run_one(
                    args, cpp, model, network, info, trace, capabilities
                )
            except DeviceAssertionError as exc:
                _p(f"device assertion failed: {exc}")
                return 2
        trace.mark()

        contention = trace.summary()
        caveat = contention_caveat(contention)
        if caveat:
            payload["contention_caveat"] = caveat
        payload["host"] = finish_host_facts(host_facts())
        payload["benchmark_lock"] = {
            "held": trace.lock_held,
            "detail": trace.lock_detail,
        }

        _heading("OUTCOME")
        if args.sweep:
            for rung in payload.get("sweep", []):
                _p(
                    f"R={rung['R']:<6} effect={rung['effect']:.4f} "
                    f"band=[{rung['band'][0]:.3f}, {rung['band'][1]:.3f}] "
                    f"clears={rung['clears']}"
                )
        elif "self_test" in payload:
            st_rep = payload["self_test"]
            clock = primary_metric(st_rep)
            st = st_rep["null_summary"].get(clock, {})
            _p(
                f"self-test noise floor on {clock}: "
                f"{st.get('p10', float('nan')):.4f} - "
                f"{st.get('p90', float('nan')):.4f}"
            )
        else:
            _p(f"{payload.get('outcome', 'no outcome recorded')}")
            _p()
            _p("Read this result as follows: the effect and the null band above")
            _p("were measured in the same session on the same binary. An effect")
            _p("inside the band is not a result. An effect outside it is a result")
            _p("at the sample size and precision stated, not a law.")
        if caveat:
            _p()
            _p(f"CONTENTION CAVEAT: {caveat}")

        from gpu.measure import emit

        emit(payload, args.json_out)
        if args.json_out:
            _p()
            _p(f"full report written to {args.json_out}")
            write_trace(trace, args.json_out.replace(".json", "") + "_contention.json")

    return status


if __name__ == "__main__":
    sys.exit(main())
