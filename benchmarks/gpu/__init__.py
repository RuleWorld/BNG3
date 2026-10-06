"""Trustworthy benchmarking for GPU stochastic simulation in this repository.

Four properties this package exists to provide, each of which an earlier GPU
number in this project lacked:

**The instrument's noise floor is measured before any claim is made.** Every
comparison runs an A/A null by default - the same arm against itself, in the
same session, under the same order-alternation discipline - and prints the
resulting band. An effect that falls inside the band is reported as
indistinguishable rather than as a win. The null can be disabled, but only
explicitly, and a report with the null disabled says so on its face.

**Timing prefers child CPU time to wall clock.** This host is shared, and wall
clock here has pointed in the opposite direction to CPU time for the same pair
of binaries. Both are recorded; the verdict is taken on CPU time and the
wall-clock verdict is printed beside it, so a divergence is visible instead of
being resolved by picking the flattering one.

**Arms carry their own evidence.** An accelerator arm refuses to measure unless
the engine reports a usable device for the backend in question, refuses to
measure unless requesting an unusable backend raises rather than returning a
result, and records the backend name the engine actually used. A silent
substitution of a host run wearing a device label is the worst failure mode of
this benchmark family, so it is tested structurally rather than argued about.

**Equivalence is statistical, and says so.** Device and host trajectories use
different random-number streams and, on this hardware, different arithmetic
precision, so bit-identity is not a target that could be met even by a perfect
implementation. The harness runs three independent distributional tests, states
the tolerance and its derivation, and reports how much agreement the data can
actually resolve so a pass is not read as a proof of identity.

Entry points:
    `benchmarks/gpu/run_gpu_bench.py`   the command-line driver
    `verify_gpu_no_fallback`            the structural no-fallback probe
    `measure_pair`                      the paired-round engine, for other lanes

Nothing here imports an accelerator framework at module scope, and no module
outside this package imports one either. The harness is stdlib-only; the
optional accelerator frameworks stay in an optional extra, off by default.
"""

from __future__ import annotations

from .arms import (
    AcceleratorArm,
    ArmResult,
    BatchConfig,
    CpuPoolArm,
    assert_no_silent_fallback,
    build_arms,
    capability_report,
)
from .contention import (
    BenchmarkSlot,
    ContentionTrace,
    contention_caveat,
    loadavg,
    sample as sample_contention,
    write_trace,
)
from .device import (
    DeviceAssertionError,
    GpuExecutionClaim,
    engine_fails_closed,
)
from .equivalence import (
    EquivalenceResult,
    binomial_chi_square,
    compare_runs,
    ks_two_sample,
    mean_z_test,
    moment_test,
)
from .measure import (
    MeasurementConfig,
    PairedTimer,
    Round,
    TimingSample,
    Verdict,
    finish_host_facts,
    host_facts,
    judge,
    summarise,
)
from .models import (
    CalibrationResult,
    ModelSpec,
    calibrate_event_density,
    shape_grid,
    shape_models,
    to_bngl,
    write_spec,
)
from .precision import (
    PrecisionAssertionError,
    PrecisionClaim,
    assert_result_dtype,
    single_precision_device_note,
    tolerance_for,
)

__all__ = [
    # measurement
    "PairedTimer",
    "MeasurementConfig",
    "TimingSample",
    "Round",
    "Verdict",
    "judge",
    "summarise",
    "host_facts",
    "finish_host_facts",
    # arms
    "AcceleratorArm",
    "CpuPoolArm",
    "ArmResult",
    "BatchConfig",
    "build_arms",
    "capability_report",
    # device assertion
    "DeviceAssertionError",
    "GpuExecutionClaim",
    "engine_backend_claim",
    "engine_fails_closed",
    "assert_no_silent_fallback",
    # precision
    "PrecisionAssertionError",
    "PrecisionClaim",
    "assert_result_dtype",
    "single_precision_device_note",
    "tolerance_for",
    # equivalence
    "EquivalenceResult",
    "compare_runs",
    "mean_z_test",
    "ks_two_sample",
    "moment_test",
    "binomial_chi_square",
    # models
    "ModelSpec",
    "CalibrationResult",
    "to_bngl",
    "write_spec",
    "calibrate_event_density",
    "shape_grid",
    "shape_models",
    # contention
    "BenchmarkSlot",
    "ContentionTrace",
    "contention_caveat",
    "loadavg",
    "sample_contention",
    "write_trace",
]

HARNESS_VERSION = "1.0.0"
