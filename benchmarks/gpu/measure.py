"""Paired measurement engine: alternating rounds, A/A null, honest verdicts.

The design here is defensive on purpose. Four separate lanes measuring on this
host independently concluded that a wall-clock A/B comparison on this machine
produffects effects that are indistinguishable from noise, and that noise is
large enough to invent a 10% win out of nothing. The cause is not subtle: the
host is shared, its load moves by a factor of three inside a single run, and
wall clock counts every microsecond the process spent waiting for a core.

Four properties follow, and this module implements all of them rather than
leaving them to the discipline of whoever runs the benchmark:

1. **The null is measured, not assumed.** `measure_pair` runs the instrument
   against itself by default (`arm_a` twice) and reports the resulting spread
   before any claim is made. An effect inside that band is reported as
   indistinguishable, not as a win. The null is on by default; turning it off
   requires passing `null=False`, and the report then says so.

2. **CPU time, not wall clock.** `rusage` of child processes is the timing
   signal. Wall clock on this host moves with contention in ways CPU time does
   not. Both are recorded; the verdict is taken on CPU time; and the
   wall-clock verdict is reported next to it so a divergence is visible instead
   of hidden.

3. **Paired rounds with alternating arm order.** Each round runs A then B, and
   the next round runs B then A. A monotone drift across the session therefore
   lands on both arms equally instead of on whichever ran second. The order is
   recorded in the output.

4. **Raw deltas, never min-of-K.** Every round's samples and deltas are
   retained and printed. The aggregate is the median of per-round ratios, which
   is robust to a single bad round without discarding the rest of the data the
   way a minimum does. A min-of-K estimator was measured reaching +10.5% on
   identical code.
"""

from __future__ import annotations

import json
import math
import os
import resource
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass
class TimingSample:
    """One invocation of one arm, timed three ways."""

    wall_s: float
    child_cpu_s: float
    self_cpu_s: float
    label: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "wall_s": self.wall_s,
            "child_cpu_s": self.child_cpu_s,
            "self_cpu_s": self.self_cpu_s,
            **({"extra": self.extra} if self.extra else {}),
        }


def _rusage_children() -> tuple[float, float]:
    """(user, system) CPU seconds consumed by all reaped children so far."""
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_utime, ru.ru_stime


def _rusage_self() -> tuple[float, float]:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return ru.ru_utime, ru.ru_stime


@dataclass
class Round:
    """One paired measurement: both arms, plus their order and delta."""

    index: int
    order: str  # "A,B" or "B,A"
    a: TimingSample
    b: TimingSample

    def ratios(self) -> dict[str, float]:
        """Per-metric B/A ratios for this round.

        Returns an empty dict when A's sample is zero, which makes a ratio
        meaningless rather than infinite; the caller reports the raw samples so
        a zero-denominator round is visible instead of silently dropped.
        """
        out: dict[str, float] = {}
        for key in ("wall_s", "child_cpu_s", "self_cpu_s"):
            av = getattr(self.a, key)
            bv = getattr(self.b, key)
            if av > 0.0:
                out[key] = bv / av
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "order": self.order,
            "a": self.a.as_dict(),
            "b": self.b.as_dict(),
            "ratios": self.ratios(),
        }


@dataclass
class Verdict:
    """The harness's judgement about a comparison, with its own uncertainty.

    `effect` is the median per-round ratio of B over A. `band` is the A/A null
    band: the same statistic computed with both arms running identical code.
    `clears_null` is the only thing that licenses a performance claim.
    """

    metric: str
    effect: float
    null_low: float
    null_high: float
    n_rounds: int
    n_null_rounds: int
    clears_null: bool
    verdict: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            # A TIME ratio B/A. Below 1.0 means B consumed less time than A.
            "time_ratio_b_over_a": self.effect,
            "effect_ratio_b_over_a": self.effect,
            "null_band": [self.null_low, self.null_high],
            "n_rounds": self.n_rounds,
            "n_null_rounds": self.n_null_rounds,
            "clears_null": self.clears_null,
            "verdict": self.verdict,
            "direction": direction_of(self.effect),
        }


def direction_of(time_ratio_b_over_a: float) -> str:
    """Name the direction of a TIME ratio B/A.

    Below 1.0 means B spent less time, so B is faster. This inversion is the
    easiest mistake to make when reading a ratio table, and getting it wrong
    flips the headline of every result, so it lives in one function that every
    caller shares.
    """
    if time_ratio_b_over_a != time_ratio_b_over_a:  # NaN
        return "not measured"
    if time_ratio_b_over_a < 1.0:
        return "B faster"
    if time_ratio_b_over_a > 1.0:
        return "B slower"
    return "no change"


def divergence_guard(verdicts: dict[str, Any], primary: str) -> dict[str, Any]:
    """Check that the contention-immune clock and wall clock tell the SAME story.

    This guard exists because host CPU time is not a neutral arbiter when one
    arm is an accelerator, and getting that wrong silently inverts a result.

    An accelerator does its arithmetic on the device. The host process pays only
    for launch, marshalling and readback. So an accelerator arm burns LESS host
    CPU than a host pool doing the same work, and a host-CPU-time verdict will
    call the device dramatically faster even when the device is slower in
    elapsed time. In a real measurement on this host the same comparison read
    0.19x on host CPU time (device "5x faster") and 2.3x on wall clock (device
    "2.3x slower") - the two clocks disagreed in DIRECTION, and either one alone
    would have been reported as the result.

    Neither clock is sufficient alone:

    * host CPU time is contention-immune but under-measures an accelerator,
      because the device's work is not host CPU;
    * wall clock captures the device's real cost but is corrupted by host
      contention, which is why it is never allowed to be the sole decider.

    So when the two disagree about direction, the run does not license a
    speedup claim at all. It reports a divergence and says what to do: state the
    host-resource cost and the elapsed-time cost separately, and never collapse
    them into one number. That is the honest description of an offload, and it
    is genuinely the finding in most cases where a device "wins" on CPU time.

    Agreement is judged on direction AND on whether each clock cleared its own
    null band, because a wall-clock ratio of 2.0 inside a 0.5-4.0 band is not
    evidence of anything even if it points the same way.
    """
    wall = verdicts.get("wall_s", {})
    cpu = verdicts.get(primary, {})
    cpu_effect = cpu.get("effect_ratio_b_over_a", float("nan"))
    wall_effect = wall.get("effect_ratio_b_over_a", float("nan"))

    # Shared with the Verdict path so the two can never disagree: the effect is
    # a TIME ratio B/A, so below 1.0 means B was faster.
    cpu_dir = direction_of(cpu_effect)
    wall_dir = direction_of(wall_effect)

    measured = cpu_dir != "not measured" and wall_dir != "not measured"
    agree = measured and cpu_dir == wall_dir

    out: dict[str, Any] = {
        "primary_metric": primary,
        "cpu_direction": cpu_dir,
        "cpu_effect": cpu_effect,
        "cpu_clears_null": cpu.get("clears_null"),
        "wall_direction": wall_dir,
        "wall_effect": wall_effect,
        "wall_clears_null": wall.get("clears_null"),
        "agree": agree,
    }

    if not measured:
        out["verdict"] = (
            "CLOCK DIVERGENCE NOT ASSESSABLE: one of the two clocks produced no "
            "usable samples, so no cross-check was possible."
        )
        out["licenses_speedup_claim"] = False
        return out

    if not agree:
        out["verdict"] = (
            f"CLOCK DIVERGENCE: {primary} says {cpu_dir} ({cpu_effect:.3f}x) but "
            f"wall clock says {wall_dir} ({wall_effect:.3f}x). The two clocks "
            f"disagree in DIRECTION. No single speedup number is licensed. This "
            f"is the expected shape for an accelerator that offloads work: the "
            f"device consumes little host CPU while still consuming elapsed "
            f"time. Report the host-resource cost and the elapsed-time cost as "
            f"two separate numbers, and do not quote the more flattering one."
        )
        out["licenses_speedup_claim"] = False
        return out

    out["verdict"] = (
        f"clocks agree ({cpu_dir}); {primary} effect {cpu_effect:.3f}x, wall "
        f"clock {wall_effect:.3f}x"
    )
    # Agreement is necessary but not sufficient: both clocks must also clear
    # their own bands before a speedup is claimable.
    if cpu.get("clears_null") and wall.get("clears_null"):
        out["licenses_speedup_claim"] = True
    else:
        out["licenses_speedup_claim"] = False
        out["verdict"] += (
            "; but not every clock cleared its own null band, so the magnitude "
            "is not yet claimable"
        )
    return out


def summarise(values: Sequence[float]) -> dict[str, float]:
    """Location and spread of `values`, with no min-of-K anywhere.

    The median is the headline because a single round hit by host contention
    must not decide the result. The reported band is the 10th-90th percentile
    when there are enough samples, else min-max, so the band is a property of
    the data rather than an assumption about a distribution.
    """
    vals = sorted(v for v in values if v == v)  # drop NaN
    if not vals:
        return {"n": 0, "median": float("nan"), "mean": float("nan")}
    n = len(vals)
    out = {
        "n": n,
        "median": statistics.median(vals),
        "mean": statistics.fmean(vals),
        "min": vals[0],
        "max": vals[-1],
        "spread": (vals[-1] / vals[0]) if vals[0] > 0 else float("inf"),
    }
    if n >= 5:
        out["p10"] = _percentile(vals, 0.10)
        out["p90"] = _percentile(vals, 0.90)
    else:
        out["p10"] = vals[0]
        out["p90"] = vals[-1]
    return out


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile of an already-sorted sequence."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_vals[int(pos)]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _band(ratios: Sequence[float], min_halfwidth: float = 0.0) -> tuple[float, float]:
    """The instrument's own noise band, from an A/A run, as a ratio interval.

    The band is the 10th-90th percentile of the A/A per-round ratios when
    there are enough samples for a percentile to mean anything, and min-max
    otherwise. A floor of `min_halfwidth` is applied around 1.0.

    The floor matters, and it is not a fudge factor. A short A/A run on a quiet
    moment can produce a band only a fraction of a percent wide, at which point
    the verdict becomes hair-trigger: a 0.3% wobble in an effect estimate trips
    "clears null" and the harness starts reporting noise as a result. That is
    the same failure as a too-tight confidence interval - a test that rejects
    everything - and it is worse here because it manufactures speedups rather
    than defects. A band with no floor also cannot distinguish "this instrument
    is precise" from "this instrument got lucky", which are different claims
    with different consequences for how many rounds the next lane needs.

    The floor is deliberately small by default; it is a guard against a
    degenerate band, not a substitute for measuring a real one. When the host
    is genuinely contended the measured band dominates it many times over, and
    the report shows the floor as distinct from the measurement so a reader can
    see which one is binding.
    """
    vals = [r for r in ratios if r == r and r > 0.0]
    if not vals:
        return (float("nan"), float("nan"))
    if len(vals) >= 5:
        low = _percentile(sorted(vals), 0.10)
        high = _percentile(sorted(vals), 0.90)
    else:
        low, high = min(vals), max(vals)
    if low > 1.0 - min_halfwidth:
        low = 1.0 - min_halfwidth
    if high < 1.0 + min_halfwidth:
        high = 1.0 + min_halfwidth
    return (low, high)


def judge(
    metric: str,
    effect_ratios: Sequence[float],
    null_ratios: Sequence[float],
    min_halfwidth: float = 0.0,
) -> Verdict:
    """Compare a measurement against the instrument's A/A null band.

    A/B nulls (arm_a vs arm_a) are the right control for B/A: both arms of the
    null experience the same process-launch, cache and scheduler path, so the
    band captures exactly the noise an apparent effect would have to exceed.
    """
    usable = [r for r in effect_ratios if r == r]
    if not usable:
        # No usable samples for this metric. An in-process arm has no child
        # process to account for, so this is expected rather than exceptional;
        # it means the metric carries no information here, not that the
        # measurement failed.
        return Verdict(
            metric,
            float("nan"),
            float("nan"),
            float("nan"),
            0,
            0,
            False,
            f"NOT MEASURED on {metric}: the arm produced no usable samples for "
            f"this clock (an in-process arm has no child CPU to account for)",
        )
    effect = statistics.median(usable)
    low, high = _band(null_ratios, min_halfwidth)
    n_null = len([r for r in null_ratios if r == r])
    if low != low:  # NaN band: no usable null samples
        return Verdict(
            metric,
            effect,
            float("nan"),
            float("nan"),
            len(effect_ratios),
            n_null,
            False,
            "NO NULL (no usable A/A samples): no claim is licensed",
        )
    clears = effect < low or effect > high
    # `effect` is a TIME ratio B/A: below 1.0 means B consumed less time than A,
    # which is B being FASTER. Getting this backwards inverts the headline of
    # every result, so the direction is derived from one helper and the reason
    # is stated once here rather than re-derived at each call site.
    if not clears:
        verdict = (
            f"INDISTINGUISHABLE (time ratio {effect:.3f}x, inside the A/A band "
            f"[{low:.3f}, {high:.3f}])"
        )
    elif effect < low:
        verdict = (
            f"B FASTER ({effect:.3f}x the time of A, below the band bottom "
            f"{low:.3f}x; equivalently A is {1.0 / effect:.2f}x slower)"
        )
    else:
        verdict = (
            f"B SLOWER ({effect:.3f}x the time of A, above the band top "
            f"{high:.3f}x; equivalently A is {effect:.2f}x faster)"
        )
    return Verdict(
        metric, effect, low, high, len(effect_ratios), n_null, clears, verdict
    )


@dataclass
class MeasurementConfig:
    """Everything a measurement run needs, in one recordable object."""

    rounds: int = 7
    warmups: int = 2
    null: bool = True
    null_rounds: int = 0  # 0 -> same as `rounds`
    null_every: int = 1  # run a null round every N effect rounds
    settle_s: float = 0.05
    #: Smallest credible A/A band, as a half-width around 1.0. See `_band` for
    #: why a floor is necessary: without one a short, quiet run yields a band
    #: fractions of a percent wide and the verdict becomes hair-trigger. The
    #: report records whether the floor or the measurement bound, so a reader
    #: can tell a genuinely precise instrument from a lucky one.
    min_band_halfwidth: float = 0.01

    def as_dict(self) -> dict[str, Any]:
        return {
            "rounds": self.rounds,
            "warmups": self.warmups,
            "null": self.null,
            "null_rounds": self.null_rounds or self.rounds,
            "null_every": self.null_every,
            "min_band_halfwidth": self.min_band_halfwidth,
        }


class PairedTimer:
    """Runs arms in alternating paired rounds and judges the result.

    `runner(label)` executes one arm and returns `(TimingSample, payload)`. The
    payload is the arm's own result (event counts, arrays, whatever the caller
    wants to check afterwards); the timing sample is what the harness trusts.
    """

    def __init__(
        self,
        runner: Callable[[str], tuple[TimingSample, Any]],
        config: MeasurementConfig | None = None,
    ) -> None:
        self._runner = runner
        self.cfg = config or MeasurementConfig()
        self.rounds: list[Round] = []
        self.null_rounds: list[Round] = []
        self.order_log: list[str] = []

    def _run_once(self, label: str) -> tuple[TimingSample, Any]:
        """Run one arm invocation and time it three ways.

        The three clocks answer different questions and all of them are kept:

        * `self_cpu_s` is this process's own CPU consumption across the call.
          For an in-process arm - the engine's own pool, a framework call - it is
          the only meaningful clock, because no child process exists to account
          for. This is why the primary metric is named `child_cpu_s` but falls
          back to this one: on this host the two have pointed in opposite
          directions for the same binary pair, so recording both and judging on
          the contention-immune one is the point.
        * `child_cpu_s` is the CPU of reaped child processes, meaningful only
          for subprocess-based arms.
        * `wall_s` is elapsed time. Recorded, printed beside the verdict, and
          never used to license a claim.

        `report()` tolerates a metric having no usable samples, because an
        in-process arm legitimately has no child CPU to report.
        """
        if self.cfg.settle_s:
            time.sleep(self.cfg.settle_s)
        c_before = _rusage_children()
        s_before = _rusage_self()
        t0 = time.perf_counter()
        sample, payload = self._runner(label)
        wall = time.perf_counter() - t0
        c_after = _rusage_children()
        s_after = _rusage_self()

        child_cpu = (c_after[0] - c_before[0]) + (c_after[1] - c_before[1])
        self_cpu = (s_after[0] - s_before[0]) + (s_after[1] - s_before[1])

        source = "harness"
        if sample.wall_s <= 0.0:
            sample.wall_s = wall
        else:
            source = "arm"
        if sample.child_cpu_s <= 0.0:
            sample.child_cpu_s = child_cpu
        if sample.self_cpu_s <= 0.0:
            sample.self_cpu_s = self_cpu
        sample.extra["timing_source"] = source
        sample.extra["harness_wall_s"] = wall
        sample.extra["harness_child_cpu_s"] = child_cpu
        sample.extra["harness_self_cpu_s"] = self_cpu
        return sample, payload

    def _paired_round(self, index: int, label_a: str, label_b: str) -> Round:
        """Run both arms once, with the order set by the round's parity."""
        a_first = index % 2 == 0
        if a_first:
            sa, _ = self._run_once(label_a)
            sb, _ = self._run_once(label_b)
            order = "A,B"
        else:
            sb, _ = self._run_once(label_b)
            sa, _ = self._run_once(label_a)
            order = "B,A"
        self.order_log.append(f"round {index}: {order}")
        return Round(index=index, order=order, a=sa, b=sb)

    def run(self, label_a: str, label_b: str) -> dict[str, Any]:
        """Warm up, measure A vs B, measure the A/A null, and judge.

        The null is interleaved with the effect rounds rather than run as a
        separate block, so if the host load shifts mid-session the null sees the
        same shift. That is the whole point: a null measured in a quiet window
        and an effect measured in a busy one would certify anything.
        """
        for i in range(self.cfg.warmups):
            self._run_once(label_a)
            self._run_once(label_b)
            if self.cfg.null:
                self._run_once(label_a)  # warm the null path identically

        n_null = self.cfg.null_rounds or self.cfg.rounds
        every = max(1, self.cfg.null_every)
        null_budget = n_null
        for i in range(self.cfg.rounds):
            rnd = self._paired_round(i, label_a, label_b)
            self.rounds.append(rnd)
            if self.cfg.null and null_budget > 0 and (i % every == 0):
                # A/A: arm_a against itself, in the same session and the same
                # order-alternation discipline as the real comparison.
                self.null_rounds.append(self._paired_round(i, label_a, label_a))
                self.order_log[-1] += " (null)"
                null_budget -= 1
        while self.cfg.null and null_budget > 0:
            self.null_rounds.append(
                self._paired_round(len(self.null_rounds), label_a, label_a)
            )
            null_budget -= 1

        return self.report(label_a, label_b)

    def report(self, label_a: str, label_b: str) -> dict[str, Any]:
        """Judge every timing metric and return a JSON-ready report.

        The primary metric is the first *usable* contention-immune clock, in
        preference order: child CPU time for a subprocess arm, then this
        process's own CPU time for an in-process one. Wall clock is never
        primary. Naming a metric primary when it has no samples would produce a
        confident report of nothing, so the choice is made from the data.
        """
        effect_ratios = [r.ratios() for r in self.rounds]
        null_ratios = [r.ratios() for r in self.null_rounds]

        metrics = ["child_cpu_s", "self_cpu_s", "wall_s"]
        verdicts: dict[str, Any] = {}
        floor_binding: dict[str, bool] = {}
        for metric in metrics:
            eff = [d[metric] for d in effect_ratios if metric in d]
            nul = [d[metric] for d in null_ratios if metric in d]
            verdicts[metric] = judge(
                metric, eff, nul, self.cfg.min_band_halfwidth
            ).as_dict()
            raw = [r for r in nul if r == r and r > 0.0]
            if raw:
                measured_low = (
                    _percentile(sorted(raw), 0.10) if len(raw) >= 5 else min(raw)
                )
                measured_high = (
                    _percentile(sorted(raw), 0.90) if len(raw) >= 5 else max(raw)
                )
                floor_binding[metric] = (
                    measured_low > 1.0 - self.cfg.min_band_halfwidth
                    or measured_high < 1.0 + self.cfg.min_band_halfwidth
                )
            else:
                floor_binding[metric] = False

        primary = "wall_s"
        for candidate in ("child_cpu_s", "self_cpu_s"):
            summary = summarise([d[candidate] for d in effect_ratios if candidate in d])
            if summary.get("n"):
                primary = candidate

        # Cross-check the deciding clock against wall clock. Without this an
        # accelerator arm can read as dramatically faster on host CPU time
        # while being slower in elapsed time, and only one of those two numbers
        # would ever get quoted.
        divergence = divergence_guard(verdicts, primary)

        return {
            "arm_a": label_a,
            "arm_b": label_b,
            "config": self.cfg.as_dict(),
            "order_log": list(self.order_log),
            "rounds": [r.as_dict() for r in self.rounds],
            "null_rounds": [r.as_dict() for r in self.null_rounds],
            "verdicts": verdicts,
            "clock_divergence": divergence,
            "effect_summary": {
                m: summarise([d[m] for d in effect_ratios if m in d]) for m in metrics
            },
            "null_summary": {
                m: summarise([d[m] for d in null_ratios if m in d]) for m in metrics
            },
            "null_band_floor_applied": floor_binding,
            "null_band_floor_halfwidth": self.cfg.min_band_halfwidth,
            "null_band_floor_note": (
                "null_band_floor_applied[m] is true when the A/A band for metric "
                "m was widened to the configured floor rather than being set by "
                "the measurement. A floor-bound band means the instrument could "
                "not resolve better than the floor this run - more rounds or a "
                "quieter host are needed before a smaller effect becomes "
                "claimable. A measurement-bound band means the observed "
                "scatter dominates and is the real noise floor."
            ),
            "primary_metric": primary,
            "primary_metric_rationale": (
                "child CPU time is contention-immune: it counts CPU actually "
                "consumed and ignores time the process spent waiting for a "
                "core. On this host wall clock has pointed in the opposite "
                "direction to CPU time for the same binary pair, which is why "
                "wall clock is recorded but never decides a verdict."
            ),
        }


def load_average() -> tuple[float, float, float]:
    """(1, 5, 15)-minute load averages, for the report's contention record."""
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        return (float("nan"),) * 3


def host_facts() -> dict[str, Any]:
    """Everything about the host that a reader needs to judge a number.

    Recorded in every report so a measurement can never be quoted without the
    context that determines whether it means anything: the load at both ends of
    the run, the core count, and the machine.
    """
    import platform

    la_start = load_average()
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "loadavg_start": list(la_start),
        "python": sys.version.split()[0],
    }


def finish_host_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Add the end-of-run load so drift during the run is visible."""
    facts = dict(facts)
    facts["loadavg_end"] = list(load_average())
    start = facts.get("loadavg_start", [float("nan")] * 3)
    end = facts.get("loadavg_end", [float("nan")] * 3)
    try:
        facts["loadavg_drift_1min"] = end[0] - start[0]
    except (TypeError, IndexError):
        facts["loadavg_drift_1min"] = float("nan")
    return facts


def emit(payload: dict[str, Any], path: str | None) -> None:
    """Write a report as JSON, atomically, to `path` or to stdout."""
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if path:
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        os.replace(tmp, path)
    else:
        print(text)


def run_worker(argv: Sequence[str], env: dict[str, str] | None = None) -> int:
    """Run a worker script as a subprocess and return its exit status.

    Used by the batch driver so each arm's timing is a fresh process, which is
    what makes `RUSAGE_CHILDREN` meaningful: the child's CPU accounting covers
    exactly one arm invocation.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(  # noqa: S603 - argv is constructed, never shell
        list(argv), env=full_env, capture_output=True, text=True
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode
