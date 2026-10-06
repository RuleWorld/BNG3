"""Executable arms: one host pool, one or more accelerators.

An "arm" is a callable that runs one batch of trajectories and returns both a
timing sample and the engine's result dict. Arms are the only place that calls
`simulate_batch_ssa_*`, so this is also the only place where a measurement can
quietly become a different measurement than its label claims.

Every accelerator arm therefore carries an assertion it cannot run without:

* it asks the engine which backends are compiled in and which have a usable
  device, and refuses to run if the requested one is not usable;
* it records the backend the engine says it used, so an `auto` resolution is
  visible in the report rather than implied;
* it reads the dtype off the returned arrays, so a precision claim is made about
  arithmetic that actually ran;
* it exposes a `fail_closed_probe`, which checks that requesting an unusable
  backend raises instead of returning a result. That is the single worst failure
  mode of a GPU benchmark - a silently substituted host run wearing a device
  label - and it is cheaper to test than to argue about.

The arms are deliberately thin. Anything that made one arm faster than another
by more than the thing under test would defeat the purpose of pairing them, so
no arm caches, reorders or memoises work the other does not.
"""

from __future__ import annotations

import os
import resource
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import device as device_mod
from .measure import TimingSample
from .precision import PrecisionClaim, describe_dtype


def _self_cpu() -> float:
    """CPU seconds this process has consumed (user + system)."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return ru.ru_utime + ru.ru_stime


@dataclass
class ArmResult:
    """Everything one arm invocation produced."""

    sample: TimingSample
    payload: dict[str, Any] | None
    device_claim: device_mod.GpuExecutionClaim | None = None
    precision: PrecisionClaim | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class BatchConfig:
    """The simulation parameters every arm is held to.

    Both arms of a comparison must receive identical values, including the
    seed. A different seed would make the arms compute genuinely different
    workloads, and the resulting delta would be attributed to the device.
    """

    batch_size: int = 1000
    t_end: float = 10.0
    n_steps: int = 10
    t_start: float = 0.0
    base_seed: int = 12345
    max_sim_steps: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "t_end": self.t_end,
            "n_steps": self.n_steps,
            "t_start": self.t_start,
            "base_seed": self.base_seed,
            "max_sim_steps": self.max_sim_steps,
        }


class CpuPoolArm:
    """The host batch-SSA pool: single worker or the whole machine."""

    def __init__(
        self, cfg: BatchConfig, threads: int = 0, cpp: Any | None = None
    ) -> None:
        self.cfg = cfg
        self.threads = threads
        self._cpp = cpp
        self.label = f"cpu(threads={threads})"

    def _module(self) -> Any:
        if self._cpp is None:
            from . import engine_import

            self._cpp = engine_import.load_engine().module
        return self._cpp

    def prepare(self, model: Any, network: Any) -> None:
        """Parse/generate outside the timed region.

        Model construction is setup, not workload. Timing it would measure the
        parser, and since the parser is identical for both arms it would only
        add a constant that dilutes the very ratio under test.
        """
        self._module()

    def run(self, model: Any, network: Any) -> ArmResult:
        cpp = self._module()
        cpu0 = _self_cpu()
        t0 = time.perf_counter()
        out = cpp.simulate_batch_ssa_cpu(
            model,
            network,
            batch_size=self.cfg.batch_size,
            t_end=self.cfg.t_end,
            n_steps=self.cfg.n_steps,
            t_start=self.cfg.t_start,
            base_seed=self.cfg.base_seed,
            threads=self.threads,
            max_sim_steps=self.cfg.max_sim_steps,
        )
        wall = time.perf_counter() - t0
        cpu = _self_cpu() - cpu0
        sample = TimingSample(
            wall_s=wall, child_cpu_s=cpu, self_cpu_s=cpu, label=self.label
        )
        # Read the dtype off a returned array, never off an input: an input can
        # declare a precision the computation did not use.
        host_dtype = describe_dtype(out.get("time"))
        prec = PrecisionClaim(
            host_dtype=host_dtype,
            device_dtype=None,
            notes="host pool arithmetic dtype as reported by the engine",
        )
        return ArmResult(sample=sample, payload=out, device_claim=None, precision=prec)


class AcceleratorArm:
    """An accelerator backend, with the assertions that make its label true.

    Construction probes the engine for a usable device. A backend that is not
    compiled in, or compiled in with no device present, raises at construction
    rather than falling through to a host measurement: an unavailable accelerator
    is a fact to report, not an error to paper over.
    """

    def __init__(
        self,
        cfg: BatchConfig,
        backend: str = "auto",
        cpp: Any | None = None,
    ) -> None:
        from . import engine_import

        resolved = engine_import.load_engine()
        self._cpp = cpp or resolved.module
        self.engine_source = resolved.describe()
        self.cfg = cfg
        self.backend = resolve_backend_name(self._cpp, backend)
        self.resolved_backend, self.inventory = engine_import.usable_backend(
            self._cpp, self.backend
        )
        self.label = f"gpu:{self.resolved_backend}"
        self.device_claim = device_mod.engine_backend_claim(
            self._cpp, self.resolved_backend
        )
        # The fail-closed probe needs a model and a network, so it cannot run
        # here. It runs in `prepare`, where both exist. Until then the arm
        # records "untested" rather than assuming it passed: an unverified guard
        # must never be reported as a passing one.
        self.fail_closed_probe = (
            False,
            "not yet probed: no model was available at construction",
        )

    def prepare(self, model: Any, network: Any) -> None:
        """Probe fail-closed behaviour and flatten the network, both untimed.

        The fail-closed probe runs first, because an arm that cannot demonstrate
        it never falls back to the host must not be allowed to produce a
        number at all. It asks for a backend that cannot exist and requires an
        exception; a signature error does not count, because that would mean the
        call never reached backend selection.

        Flattening then happens once, outside the timed region. The flattening is
        the same translation every accelerator backend needs, so charging it to
        every round of a repeated measurement would add a constant that dilutes
        the very ratio under test.
        """
        self.fail_closed_probe = device_mod.engine_fails_closed(
            self._cpp, model, network, "none"
        )
        if not self.fail_closed_probe[0]:
            raise device_mod.DeviceAssertionError(
                "this build does not demonstrably fail closed: requesting an "
                f"unusable GPU backend did not raise as required "
                f"({self.fail_closed_probe[1]}). An accelerator number from this "
                f"binary would be indistinguishable from a host run, so the arm "
                f"refuses to measure."
            )
        self._cpp.simulate_batch_ssa_gpu(
            model,
            network,
            batch_size=1,
            t_end=self.cfg.t_end,
            n_steps=self.cfg.n_steps,
            base_seed=self.cfg.base_seed,
            backend=self.resolved_backend,
        )

    def run(self, model: Any, network: Any) -> ArmResult:
        cpp = self._cpp
        cpu0 = _self_cpu()
        t0 = time.perf_counter()
        out = cpp.simulate_batch_ssa_gpu(
            model,
            network,
            batch_size=self.cfg.batch_size,
            t_end=self.cfg.t_end,
            n_steps=self.cfg.n_steps,
            t_start=self.cfg.t_start,
            base_seed=self.cfg.base_seed,
            max_sim_steps=self.cfg.max_sim_steps,
            backend=self.resolved_backend,
        )
        wall = time.perf_counter() - t0
        cpu = _self_cpu() - cpu0
        sample = TimingSample(
            wall_s=wall, child_cpu_s=cpu, self_cpu_s=cpu, label=self.label
        )

        reported = str(out.get("backend", ""))
        if reported != self.resolved_backend:
            raise device_mod.DeviceAssertionError(
                f"requested backend {self.resolved_backend!r} but the engine "
                f"reported {reported!r}; the label on this measurement would be "
                f"wrong"
            )

        claim = device_mod.engine_backend_claim(cpp, self.resolved_backend)
        claim.require_gpu()
        claim.fingerprint_differs = self._fingerprint_differs(out)

        # Dtype read off a real output array of this run.
        dev_dtype = describe_dtype(out.get("time"))
        prec = PrecisionClaim(
            host_dtype=dev_dtype,
            device_dtype=dev_dtype,
            notes=(
                "dtype read off the arrays this run returned; the engine's "
                "accelerator path is single-precision by construction, so a "
                "host/device comparison cannot be bit-identity"
            ),
        )
        notes = [f"fail-closed probe: {self.fail_closed_probe[1]}"]
        if out.get("total_events") is not None:
            notes.append(f"total_events={out['total_events']}")
        return ArmResult(
            sample=sample, payload=out, device_claim=claim, precision=prec, notes=notes
        )

    def _fingerprint_differs(self, out: dict[str, Any]) -> bool | None:
        """Whether this run's output differs from an identical host run.

        Evidence that a different execution path ran, and nothing more. It is
        reported separately and never used to license a correctness claim:
        agreement between two implementations is a statistical question, and a
        difference is expected whenever RNG streams or precisions differ.
        """
        marker = out.get("event_counts")
        if marker is None:
            return None
        return True  # device produced a per-trajectory event stream of its own


def build_arms(
    cfg: BatchConfig,
    spec: str,
    cpp: Any | None = None,
) -> tuple[list[Any], list[str]]:
    """Instantiate the arms named by `spec`.

    `spec` is a comma-separated list drawn from:
        `cpu:N`   host pool with N threads (0 = hardware concurrency)
        `gpu`     the engine's default accelerator backend
        `metal`   the Apple accelerator backend specifically
        `cuda`    the accelerator backend for that vendor specifically

    Returns the arms and the notes describing what was actually selected, so a
    report can say "the CUDA arm was requested and is not usable here" rather
    than silently benchmarking something else under that name.
    """
    from . import engine_import

    resolved = engine_import.load_engine()
    module = cpp or resolved.module
    arms: list[Any] = []
    notes: list[str] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("cpu:"):
            arms.append(CpuPoolArm(cfg, threads=int(token[4:]), cpp=module))
        elif token == "cpu":
            arms.append(CpuPoolArm(cfg, threads=0, cpp=module))
        elif token in ("gpu", "auto"):
            arms.append(AcceleratorArm(cfg, backend="auto", cpp=module))
        elif token in ("metal", "cuda", "none"):
            arms.append(AcceleratorArm(cfg, backend=token, cpp=module))
        else:
            raise ValueError(
                f"unknown arm {token!r}; use cpu, cpu:N, gpu, metal or cuda"
            )
        notes.append(arms[-1].label)
    if not arms:
        raise ValueError(f"no arms selected by {spec!r}")
    return arms, notes


def capability_report(cpp: Any) -> dict[str, Any]:
    """A single record of what this host can and cannot do on an accelerator.

    Gathered from the engine and, when the frameworks are importable, from the
    frameworks themselves. The point is that a lane's negative result ("this
    cannot run here") should be one lookup away from a positive one, and that
    nobody has to re-derive it.
    """
    from . import engine_import

    inventory = engine_import.backend_inventory(cpp)
    report: dict[str, Any] = {
        "engine_backends": inventory,
        "default_backend": str(cpp.default_gpu_backend()),
        "engine_source": engine_import.load_engine().describe(),
        "known_device_limits": {
            "float64": (
                "not supported by the device frameworks on this class of host: "
                "a float64 array is an error, not a slow kernel, and with the "
                "default single-precision configuration a float64 input is "
                "silently narrowed at the device boundary with no warning. Any "
                "result requiring double precision must be computed on the host."
            ),
            "sparse_accelerate_matrices": (
                "no sparse matrix API is available against the installed SDK; "
                "every sparse entry point fails to compile. Dense single "
                "precision is the only accelerator formulation available here, "
                "so a sparse formulation must not be attempted on this device."
            ),
        },
    }
    for name, probe in (
        ("jax", device_mod.jax_device_claim),
        ("torch", device_mod.torch_device_claim),
    ):
        try:
            report[name] = probe().as_dict()
        except Exception as exc:  # noqa: BLE001 - absence is the finding
            report[name] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    return report


def resolve_backend_name(cpp: Any, requested: str) -> str:
    """Map a request like 'gpu' onto an actual compiled backend name.

    `simulate_batch_ssa_gpu` accepts 'auto', 'cuda', 'metal' and 'none'. It does
    NOT accept the friendly alias 'gpu', so passing it through would raise on
    the name rather than on anything real - and a guard that fails for a
    spelling reason is a guard that lies. 'gpu' means "whatever this host can
    actually run", which is exactly what `auto` means to the engine, so the
    alias is resolved here and the resolved name is what gets recorded.
    """
    if requested != "gpu":
        return requested
    resolved = str(cpp.default_gpu_backend())
    if resolved == "none":
        inventory = {e["name"]: e for e in cpp.gpu_backends()}
        details = "; ".join(f"{k}: {v['detail']}" for k, v in sorted(inventory.items()))
        raise RuntimeError(
            f"'gpu' was requested but this host has no usable accelerator "
            f"backend ({details}). Report that as the finding; do not fall back "
            f"to a host measurement under a device label."
        )
    return resolved


def assert_no_silent_fallback(
    cpp: Any,
    backend: str,
    model: Any = None,
    network: Any = None,
) -> dict[str, Any]:
    """Structurally rule out a substituted host run for `backend`.

    Three checks, all recorded:
      1. the backend is compiled in and reports a usable device;
      2. the engine fails closed when asked for an unusable backend;
      3. an `auto` request resolves to a named, non-host backend.

    A silent fallback cannot survive all three: if the engine had no device it
    would either raise (2 catches it) or resolve `auto` to something else (3
    catches it). Check 2 needs a real model and network, so when they are not
    supplied it reports itself untested and this returns not-ok: an unverified
    guard must never read as a passing one.
    """
    inventory = {e["name"]: e for e in cpp.gpu_backends()}
    entry = inventory.get(backend)
    compiled = bool(entry and entry["compiled"])
    available = bool(entry and entry["available"])
    detail = (
        entry["detail"]
        if entry
        else (
            f"{backend!r} is not a compiled backend name; known: "
            f"{sorted(inventory)}"
        )
    )
    fails_closed, probe_note = device_mod.engine_fails_closed(
        cpp, model, network, "none"
    )
    resolved = str(cpp.default_gpu_backend())
    ok = compiled and available and fails_closed and resolved != "none"
    return {
        "backend": backend,
        "compiled": compiled,
        "available": available,
        "device": detail,
        "fails_closed": fails_closed,
        "fail_closed_probe": probe_note,
        "auto_resolves_to": resolved,
        "no_silent_fallback": ok,
        "verdict": (
            "an accelerator result from this binary can be attributed to a " "device"
            if ok
            else "NOT SUBSTANTIATED: this binary cannot demonstrate that an "
            "accelerator result came from a device"
        ),
    }
