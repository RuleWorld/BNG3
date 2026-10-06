#!/usr/bin/env python3
"""Self-test for the GPU benchmark harness.

Every other lane's GPU number depends on this instrument being correct, and an
instrument whose own bugs are unmeasured is worse than no instrument: it
manufactures confidence. So the harness's own behaviour is tested here, on
deterministic inputs where the right answer is known in advance.

What is tested, and why each matters:

1. **The null band catches a planted null.** Feed the paired timer two arms that
   compute the same thing and confirm the band is finite and contains 1.0. If
   the band were empty or degenerate, every downstream lane's "clears null"
   verdict would be meaningless.

2. **The null band catches a planted effect.** Give arm B genuinely more work
   and confirm the effect is detected and reported as clearing the band. A null
   control that never fires is as useless as one that always fires.

3. **A planted effect inside the noise is NOT reported as a win.** Give arm B a
   marginal slowdown and confirm the verdict says indistinguishable. This is the
   specific failure the harness exists to prevent, so it is the specific thing
   that must be proven to work.

4. **A min-of-K estimator would have called it a win.** Demonstrate that the
   per-round raw spread is real and that selecting the minimum round would have
   produced a spurious speedup. A previous lane's null showed a min estimator
   reaching +10.5% on identical code, so this documents the hazard concretely.

5. **Child CPU time is preferred over wall clock,** and the harness measures
   both. Check the report carries both and marks the CPU metric primary.

6. **Device assertion rejects a host-only claim.** A claim listing only CPU
   devices must raise, and one listing a device must not. This is the structural
   guard against a silent fallback.

7. **Precision claims are not upgraded.** A single-precision device against a
   double-precision host must be reported as statistical-only, and a same-dtype
   pair must be allowed to claim more.

8. **The z-threshold scales with the number of cells tested,** so a fixed 3.0
   threshold cannot pass silently as a default.

9. **Synthetic networks have the requested reaction count,** for a range of
   shapes, and the generator is deterministic.

10. **Equivalence tests are calibrated:** identical distributions pass, a
    genuinely shifted distribution fails, and a variance-only difference (which
    a mean test cannot see) is caught by the shape test.

Run with:  python3 benchmarks/gpu/selftest.py
Exit status 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpu import (  # noqa: E402
    MeasurementConfig,
    ModelSpec,
    PairedTimer,
    TimingSample,
    judge,
    summarise,
    to_bngl,
    tolerance_for,
)
from gpu.device import DeviceAssertionError, GpuExecutionClaim  # noqa: E402
from gpu.equivalence import ks_two_sample, mean_z_test, moment_test  # noqa: E402
from gpu.precision import (
    PrecisionClaim,
    tolerance_for as precision_tolerance,
)  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check. Never raises: a failure must not abort the suite."""
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def _cpu_arm(label: str, work: float = 0.0):
    """A deterministic in-process arm: a fixed busy-wait, no wall dependence.

    The busy-wait burns host CPU on purpose. Sleeping would make the arm's
    self-CPU time approximately zero and the ratio meaningless; and varying the
    sleep would reintroduce exactly the wall-clock sensitivity the harness is
    built to avoid.
    """
    counter = 0
    deadline = work
    while counter < deadline:
        counter += 1
    return TimingSample(wall_s=0.0, child_cpu_s=0.0, self_cpu_s=0.0, label=label)


def test_null_band_catches_planted_null() -> None:
    print("\n[1] A/A null: two arms doing identical work")
    a_work, b_work = 200_000, 200_000
    timer = PairedTimer(
        runner=lambda label: (_cpu_arm(label, a_work), None),
        config=MeasurementConfig(rounds=5, warmups=0, null=True, settle_s=0.0),
    )
    report = timer.run("A", "B")
    band = report["null_summary"]["self_cpu_s"]
    verdict = report["verdicts"]["self_cpu_s"]
    check(
        "null band is finite",
        math.isfinite(band["p10"]) and math.isfinite(band["p90"]),
        f"band={band}",
    )
    check(
        "null band contains 1.0 (no phantom effect)",
        band["p10"] <= 1.0 <= band["p90"],
        f"band=[{band['p10']:.4f}, {band['p90']:.4f}]",
    )
    check(
        "verdict for identical arms is indistinguishable",
        verdict["clears_null"] is False,
        verdict["verdict"],
    )
    check(
        "null rounds were actually run",
        len(report["null_rounds"]) > 0,
        f"{len(report['null_rounds'])} null rounds",
    )


def test_null_band_catches_planted_effect() -> None:
    print("\n[2] A/B with a planted effect: arm B does twice the work")
    # Arm B is deliberately given MORE work, so the correct verdict is that B
    # is SLOWER. The time ratio must land near 2.0 and the verdict must say so.
    # Asserting the direction explicitly is what catches an inverted label: every
    # number stays correct while the headline flips.
    timer = PairedTimer(
        runner=lambda label: (
            _cpu_arm(label, 200_000 if label == "A" else 400_000),
            None,
        ),
        config=MeasurementConfig(rounds=5, warmups=0, null=True, settle_s=0.0),
    )
    report = timer.run("A", "B")
    verdict = report["verdicts"]["self_cpu_s"]
    effect = verdict["effect_ratio_b_over_a"]
    check(
        "planted 2x extra work is detected",
        verdict["clears_null"] is True,
        f"effect={effect:.4f} band={verdict['null_band']}",
    )
    check(
        "the time ratio is near 2.0 as planted",
        1.6 < effect < 2.6,
        f"effect={effect:.4f}",
    )
    check(
        "verdict says B is SLOWER, not faster",
        "B SLOWER" in verdict["verdict"],
        verdict["verdict"],
    )
    check(
        "verdict direction field agrees with the text",
        verdict["direction"] == "B slower",
        str(verdict["direction"]),
    )


def test_effect_inside_noise_is_not_a_win() -> None:
    print("\n[3] A/B with a planted effect INSIDE the noise floor")
    # This is the case the harness exists for. A real effect is present - arm B
    # is genuinely ~10% slower - but it is smaller than the instrument's own
    # scatter, so the correct verdict is 'indistinguishable'. Reporting it as a
    # regression would be wrong in exactly the way that has produced several
    # unreadable GPU numbers in this project.
    #
    # The jitter is not decoration: without it the instrument's band collapses
    # to near zero, a 10% effect correctly clears it, and the test would be
    # asserting that a correct instrument is wrong. A real host produces the
    # scatter; the synthetic arm has to as well.
    rng = random.Random(20260903)
    state = {"n": 0}

    def jittery(label: str) -> tuple[TimingSample, None]:
        state["n"] += 1
        # +/-30% round-to-round scatter, applied to BOTH arms, standing in for
        # host contention. Arm B additionally carries a real 10% penalty.
        scatter = rng.uniform(0.7, 1.3)
        penalty = 1.10 if label != "A" else 1.0
        work = int(200_000 * scatter * penalty)
        return _cpu_arm(label, work), None

    timer = PairedTimer(
        runner=jittery,
        config=MeasurementConfig(rounds=11, warmups=0, null=True, settle_s=0.0),
    )
    report = timer.run("A", "B")
    verdict = report["verdicts"]["self_cpu_s"]
    effect = verdict["effect_ratio_b_over_a"]
    band = verdict["null_band"]
    inside = band[0] <= effect <= band[1]
    check(
        "a real 10% penalty inside a wide null band is NOT called a result",
        verdict["clears_null"] is False and inside,
        f"effect={effect:.4f} band=[{band[0]:.4f}, {band[1]:.4f}] {verdict['verdict']}",
    )
    check(
        "the verdict says so in words",
        "INDISTINGUISHABLE" in verdict["verdict"],
        verdict["verdict"],
    )

    # The specific hazard this harness exists to prevent: a min-of-K estimator
    # picking the single luckiest round would report a large spurious speedup.
    raw = [
        r["ratios"].get("self_cpu_s")
        for r in report["rounds"]
        if r["ratios"].get("self_cpu_s")
    ]
    if raw:
        best = min(raw)
        median = summarise(raw)["median"]
        print(f"        per-round ratios: {[round(x, 4) for x in raw]}")
        print(
            f"        min-of-K would report {best:.4f}x; the median reports "
            f"{median:.4f}x"
        )
        check(
            "min-of-K is visibly more optimistic than the median",
            best <= median * 0.999 or best < median,
            f"best={best:.4f} median={median:.4f}",
        )


def test_cpu_time_is_primary_and_both_recorded() -> None:
    print("\n[4] Both clocks recorded; a contention-immune clock is primary")
    timer = PairedTimer(
        runner=lambda label: (_cpu_arm(label, 100_000), None),
        config=MeasurementConfig(rounds=3, warmups=0, null=True, settle_s=0.0),
    )
    report = timer.run("A", "B")
    # An in-process arm has no child process, so the harness must fall back to
    # this process's own CPU time rather than reporting an empty child-clock
    # measurement as though it were a result. Wall clock is never primary.
    check(
        "primary metric is a CPU clock, never wall clock",
        report["primary_metric"] in ("child_cpu_s", "self_cpu_s"),
        report["primary_metric"],
    )
    check(
        "primary metric rationale is recorded",
        "contention-immune" in report.get("primary_metric_rationale", ""),
        report.get("primary_metric_rationale", "")[:80],
    )
    for metric in ("child_cpu_s", "wall_s", "self_cpu_s"):
        check(
            f"{metric} present in the report",
            metric in report["verdicts"],
            f"verdicts has {sorted(report['verdicts'])}",
        )
    check(
        "raw per-round deltas are retained",
        len(report["rounds"]) >= 3 and all("ratios" in r for r in report["rounds"]),
        f"{len(report['rounds'])} rounds",
    )


def test_order_alternates() -> None:
    print("\n[5] Arm order alternates across rounds")
    timer = PairedTimer(
        runner=lambda label: (_cpu_arm(label, 10_000), None),
        config=MeasurementConfig(rounds=4, warmups=0, null=True, settle_s=0.0),
    )
    report = timer.run("A", "B")
    orders = [r["order"] for r in report["rounds"]]
    check("first round runs A then B", orders[0] == "A,B", f"orders={orders}")
    check(
        "second round runs B then A (order alternates)",
        orders[1] == "B,A",
        f"orders={orders}",
    )
    check(
        "both orders appear across the run",
        set(orders) == {"A,B", "B,A"},
        f"orders={orders}",
    )


def test_device_assertion_rejects_host_only() -> None:
    print("\n[6] Device assertion rejects a host-only claim")
    host_only = GpuExecutionClaim(
        framework="test",
        devices=["cpu"],
        result_devices=["cpu"],
        backend_reported="cpu",
    )
    try:
        host_only.require_gpu()
        check(
            "host-only device claim is rejected", False, "require_gpu() did not raise"
        )
    except DeviceAssertionError:
        check("host-only device claim is rejected", True)

    empty = GpuExecutionClaim(framework="test", devices=[], result_devices=[])
    try:
        empty.require_gpu()
        check("empty device list is rejected", False, "require_gpu() did not raise")
    except DeviceAssertionError:
        check("empty device list is rejected", True)

    real = GpuExecutionClaim(
        framework="test",
        devices=["Apple M5 Pro"],
        result_devices=["Apple M5 Pro"],
        backend_reported="metal",
    )
    try:
        real.require_gpu()
        check("genuine device claim is accepted", True)
    except DeviceAssertionError as exc:
        check("genuine device claim is accepted", False, str(exc))


def test_precision_claims_not_upgraded() -> None:
    print("\n[7] Precision: single vs double is statistical-only")
    mixed = PrecisionClaim(host_dtype="float64", device_dtype="float32")
    result = mixed.comparability()
    check(
        "mixed precision cannot claim bit-identity",
        result["strongest_claim"] == "statistical",
        f"{result['strongest_claim']}: {result['reason']}",
    )
    check(
        "mixed precision says why",
        "bit" in result["reason"].lower() or "precision" in result["reason"].lower(),
        result["reason"],
    )

    same = PrecisionClaim(host_dtype="float64", device_dtype="float64")
    check(
        "same precision permits a stronger claim",
        same.comparability()["strongest_claim"] == "bit-identity-possible",
        same.comparability()["strongest_claim"],
    )

    closed = PrecisionClaim(
        host_dtype="float64", device_dtype="float32", closed_form_dtype="float64"
    )
    check(
        "closed-form precision gap is flagged",
        closed.comparability()["closed_form_caveat"] is not None,
        str(closed.comparability()["closed_form_caveat"]),
    )


def test_z_threshold_scales_with_cells() -> None:
    print("\n[8] z-threshold scales with the number of cells tested")
    few = precision_tolerance([0], 4, 0.001)
    many = precision_tolerance([0], 4000, 0.001)
    check(
        "more cells demands a stricter per-cell threshold",
        many > few,
        f"n=4 -> {few:.4f}, n=4000 -> {many:.4f}",
    )
    check(
        "threshold matches the closed form for n=1",
        abs(precision_tolerance([0], 1, 0.001) - 3.0) < 1e-9,
        str(precision_tolerance([0], 1, 0.001)),
    )
    # Cross-check the Bonferroni z against the threshold the harness prints.
    check(
        "Bonferroni threshold is a sensible magnitude", 3.0 < many < 8.0, f"{many:.4f}"
    )


def test_synthetic_shapes() -> None:
    print("\n[9] Synthetic network shapes are exact and deterministic")
    for species, reactions in ((4, 4), (8, 32), (16, 64), (64, 1024), (3, 5)):
        spec = ModelSpec(name="t", species=species, reactions=reactions)
        text = to_bngl(spec)
        rules = [line for line in text.splitlines() if "->" in line]
        check(
            f"R={reactions} S={species} emits exactly {reactions} reactions",
            len(rules) == reactions,
            f"got {len(rules)}",
        )
        again = to_bngl(ModelSpec(name="t", species=species, reactions=reactions))
        check(f"R={reactions} S={species} is deterministic", text == again)

    try:
        to_bngl(ModelSpec(name="t", species=1, reactions=4))
        check("single-species chain is rejected", False, "no error raised")
    except ValueError:
        check("single-species chain is rejected", True)


def test_equivalence_tests_are_calibrated() -> None:
    print("\n[10] Equivalence tests detect real differences and tolerate none")
    # Identical distributions must pass.
    a = [10, 11, 12, 13, 14] * 40
    b = list(a)
    ks = ks_two_sample(a, b)
    check(
        "identical samples pass KS",
        ks["passes"] and ks["statistic"] == 0.0,
        f"D={ks['statistic']}",
    )
    mom = moment_test(a, b)
    check("identical samples pass the moment test", mom["passes"], str(mom))

    # A pure location shift must fail.
    shifted = [x + 50 for x in a]
    mom_shift = moment_test(a, shifted)
    check(
        "a large location shift fails the moment test",
        not mom_shift["passes"],
        f"mean_rel_err={mom_shift['mean_rel_error']}",
    )
    ks_shift = ks_two_sample(a, shifted)
    check(
        "a large location shift fails KS",
        not ks_shift["passes"],
        f"D={ks_shift['statistic']} p={ks_shift['p_value']}",
    )

    # A pure scale change: same mean, different variance. A mean-only test is
    # blind to this, which is exactly why the KS and moment tests exist.
    tight = [10 + (i % 3) for i in range(200)]
    wide = [10 + (i % 40) for i in range(200)]
    mom_scale = moment_test(tight, wide)
    check(
        "a variance-only difference is flagged",
        mom_scale["shape_flag"] is not None or not mom_scale["passes"],
        f"var_ratio={mom_scale['variance_ratio']}",
    )

    # Mean z-test: a detectable shift must be caught, agreement must not fire.
    # With n=1000 per side and std 2.0, a shift of 2.0 is half a pooled
    # standard deviation of the *sampling mean*, so z is large; that is the
    # test working, and it is why the harness also reports the sample size.
    names = ["Obs"]
    mean_same = [[50.0, 50.0, 50.0]]
    std_same = [[2.0, 2.0, 2.0]]
    _, max_z, _, _ = mean_z_test(
        mean_same, std_same, mean_same, std_same, names, 1000, 1000, 0.001
    )
    check("identical means give max|z| == 0", max_z == 0.0, f"max_z={max_z}")
    mean_shift = [[50.0, 52.0, 50.0]]
    _, max_z2, thr2, worst2 = mean_z_test(
        mean_same, std_same, mean_shift, std_same, names, 1000, 1000, 0.001
    )
    check("a mean shift is detected", max_z2 > 1.0, f"max_z={max_z2}")
    check(
        "the worst cell is attributed to an observable",
        worst2 == "Obs",
        f"worst={worst2}",
    )
    check(
        "the detected shift exceeds the Bonferroni threshold",
        max_z2 > thr2,
        f"max_z={max_z2:.3f} threshold={thr2:.3f}",
    )
    # A shift well inside the sampling noise must NOT fire.
    tiny_shift = [[50.0001, 50.0, 50.0]]
    _, max_z3, _, _ = mean_z_test(
        mean_same, std_same, tiny_shift, std_same, names, 1000, 1000, 0.001
    )
    check("a sub-threshold shift does not fire", max_z3 < thr2, f"max_z={max_z3:.4f}")


def test_direction_labels_are_not_inverted() -> None:
    print("\n[11] Ratio direction labels (a TIME ratio, not a speed ratio)")
    # `effect` is B's TIME divided by A's time. Below 1 means B spent LESS time,
    # i.e. B was FASTER. Inverting this flips the headline of every result
    # while leaving every number correct, which is the most dangerous kind of
    # reporting bug: nothing looks wrong.
    from gpu.measure import direction_of

    check(
        "a time ratio below 1 is 'B faster'",
        direction_of(0.2) == "B faster",
        direction_of(0.2),
    )
    check(
        "a time ratio above 1 is 'B slower'",
        direction_of(5.0) == "B slower",
        direction_of(5.0),
    )
    check("exactly 1 is no change", direction_of(1.0) == "no change", direction_of(1.0))
    check(
        "NaN is not measured",
        direction_of(float("nan")) == "not measured",
        direction_of(float("nan")),
    )

    fast = judge("t", [0.2], [0.95, 1.1])
    slow = judge("t", [5.0], [0.95, 1.1])
    check(
        "judge calls a low time ratio FASTER", "B FASTER" in fast.verdict, fast.verdict
    )
    check(
        "judge calls a high time ratio SLOWER", "B SLOWER" in slow.verdict, slow.verdict
    )
    check(
        "the verdict states the equivalent factor the other way round",
        "5.00x slower" in fast.verdict,
        fast.verdict,
    )


def test_clock_divergence_blocks_a_claim() -> None:
    print("\n[12] Cross-clock check refuses to license a one-sided number")
    from gpu.measure import divergence_guard

    # The real failure mode: an accelerator burns almost no host CPU while
    # still consuming elapsed time, so the clocks point opposite ways and only
    # the flattering one gets quoted.
    disagreeing = {
        "child_cpu_s": {"effect_ratio_b_over_a": 0.2, "clears_null": True},
        "wall_s": {"effect_ratio_b_over_a": 2.5, "clears_null": True},
    }
    out = divergence_guard(disagreeing, "child_cpu_s")
    check("opposite directions are detected", out["agree"] is False, str(out))
    check(
        "no speedup is licensed on disagreement",
        out["licenses_speedup_claim"] is False,
        str(out),
    )
    check(
        "the reason names the offload mechanism",
        "offload" in out["verdict"] or "host CPU" in out["verdict"],
        out["verdict"],
    )

    agreeing = {
        "child_cpu_s": {"effect_ratio_b_over_a": 0.2, "clears_null": True},
        "wall_s": {"effect_ratio_b_over_a": 0.25, "clears_null": True},
    }
    check(
        "agreement plus both clearing licenses a claim",
        divergence_guard(agreeing, "child_cpu_s")["licenses_speedup_claim"] is True,
        str(divergence_guard(agreeing, "child_cpu_s")),
    )

    # Agreeing in direction is not enough if one clock is still inside its band.
    weak = {
        "child_cpu_s": {"effect_ratio_b_over_a": 0.2, "clears_null": True},
        "wall_s": {"effect_ratio_b_over_a": 0.25, "clears_null": False},
    }
    check(
        "agreement inside the wall-clock band licenses nothing",
        divergence_guard(weak, "child_cpu_s")["licenses_speedup_claim"] is False,
        str(divergence_guard(weak, "child_cpu_s")),
    )

    missing = {"child_cpu_s": {"effect_ratio_b_over_a": 0.2, "clears_null": True}}
    check(
        "an unmeasurable clock blocks the claim too",
        divergence_guard(missing, "child_cpu_s")["licenses_speedup_claim"] is False,
        str(divergence_guard(missing, "child_cpu_s")),
    )


def main() -> int:
    print("=" * 78)
    print("GPU BENCHMARK HARNESS SELF-TEST")
    print("=" * 78)
    test_null_band_catches_planted_null()
    test_null_band_catches_planted_effect()
    test_effect_inside_noise_is_not_a_win()
    test_cpu_time_is_primary_and_both_recorded()
    test_order_alternates()
    test_device_assertion_rejects_host_only()
    test_precision_claims_not_upgraded()
    test_z_threshold_scales_with_cells()
    test_synthetic_shapes()
    test_equivalence_tests_are_calibrated()
    test_direction_labels_are_not_inverted()
    test_clock_divergence_blocks_a_claim()

    print()
    print("=" * 78)
    print(f"SELF-TEST: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("=" * 78)
        for failure in FAILED:
            print(f"  FAILED: {failure}")
        return 1
    print("The harness's own noise floor, planted-effect detection, and")
    print("guard behaviour are all verified. Numbers it produces can be read.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
