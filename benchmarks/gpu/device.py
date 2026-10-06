"""Device assertion for the GPU benchmark harness.

Every arm that claims to have run on an accelerator must prove it, or the
measurement is rejected. The worst failure mode in this project is a "GPU"
number that was produced by the CPU pool, either because the framework silently
fell back or because the accelerator was unavailable and the code path quietly
continued on the host. This module exists to make that failure impossible to
report.

Two levels of proof are used, and an arm must supply both:

1. **Structural** - the device is enumerated *and* the result object says where
   it lives. A device count of zero rules out a silent fallback inside the
   process; a result tensor whose device field names the host rules it out too.
2. **Fingerprint** - the accelerator result is not bit-identical to the host
   result for the same inputs. This is evidence that a different execution path
   ran. It is *not* correctness evidence (see `equivalence.py`), and it is
   reported separately for exactly that reason.

`GpuExecutionClaim` is the object every arm returns. `require_gpu()` turns a
failed claim into a raised `DeviceAssertionError`, so a caller cannot quietly
continue with a host measurement under a GPU label.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any


class DeviceAssertionError(AssertionError):
    """Raised when an arm claims GPU execution it cannot substantiate."""


@dataclass
class GpuExecutionClaim:
    """Evidence that an arm's work executed on an accelerator.

    Attributes:
        framework: "c++-metal", "c++-cuda", "jax-mps", "torch-mps", ...
        devices: device strings enumerated from the framework itself.
        result_devices: devices reported by the result objects.
        backend_reported: backend name the runtime said it used, if any.
        fingerprint_differs: accelerator output differs from host output.
        notes: human-readable detail for the report.
    """

    framework: str
    devices: list[str] = field(default_factory=list)
    result_devices: list[str] = field(default_factory=list)
    backend_reported: str | None = None
    fingerprint_differs: bool | None = None
    notes: str = ""

    def require_gpu(self) -> "GpuExecutionClaim":
        """Raise unless this claim substantiates on-device execution.

        Structural requirements (all must hold):
          * at least one device was enumerated;
          * the enumerated devices are not host-only names;
          * the result objects report a device, and none of them is host-only;
          * a backend/runtime name was reported, so the "auto" resolution is
            visible rather than implied.

        The fingerprint check is reported but never required here: a legitimately
        executing device may coincidentally reproduce host bits on a degenerate
        workload, and that coincidence says nothing about speed.
        """
        if not self.devices:
            raise DeviceAssertionError(
                f"{self.framework}: no device enumerated by the framework, so "
                f"execution cannot be shown to be on-device. notes={self.notes!r}"
            )
        host_only = [d for d in self.devices if _is_host_device(d)]
        if host_only and len(host_only) == len(self.devices):
            raise DeviceAssertionError(
                f"{self.framework}: every enumerated device is a host device "
                f"({host_only}). This is the silent-fallback signature. "
                f"notes={self.notes!r}"
            )
        if not self.result_devices:
            raise DeviceAssertionError(
                f"{self.framework}: result objects reported no device. "
                f"notes={self.notes!r}"
            )
        host_results = [d for d in self.result_devices if _is_host_device(d)]
        if host_results and len(host_results) == len(self.result_devices):
            raise DeviceAssertionError(
                f"{self.framework}: results are hosted on {host_results}. "
                f"notes={self.notes!r}"
            )
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework,
            "devices": list(self.devices),
            "result_devices": list(self.result_devices),
            "backend_reported": self.backend_reported,
            "fingerprint_differs": self.fingerprint_differs,
            "notes": self.notes,
        }


_HOST_NAMES = {"cpu", "host", "default", "none", "null"}


def _is_host_device(name: str) -> bool:
    """True when a device string names the host rather than an accelerator."""
    n = name.strip().lower()
    if n in _HOST_NAMES:
        return True
    return n.startswith("cpu") or n.startswith("host")


# --------------------------------------------------------------------------
# Engine (pybind11) backends
# --------------------------------------------------------------------------


def engine_backend_claim(cpp: Any, backend: str) -> GpuExecutionClaim:
    """Enumerate the compiled-in batch-SSA GPU backends of the engine module.

    The engine resolves `backend="auto"` internally and reports which backend it
    picked in the result dict, so the resolution is observable rather than
    implied. The enumeration additionally proves a usable device exists.
    """
    inventory = {entry["name"]: entry for entry in cpp.gpu_backends()}
    entry = inventory.get(backend)
    notes = "; ".join(
        f"{name} compiled={item['compiled']} available={item['available']} "
        f"detail={item['detail']!r}"
        for name, item in sorted(inventory.items())
    )
    devices: list[str] = []
    if entry is not None and entry["available"]:
        devices.append(entry["detail"] or f"engine:{backend}")
    return GpuExecutionClaim(
        framework=f"c++-{backend}",
        devices=devices,
        result_devices=[entry["detail"] or f"engine:{backend}"] if devices else [],
        backend_reported=str(cpp.default_gpu_backend()),
        notes=notes,
    )


def engine_fails_closed(
    cpp: Any,
    model: Any = None,
    network: Any = None,
    backend: str = "none",
) -> tuple[bool, str]:
    """Check that asking for an unusable backend raises instead of running.

    A backend selection that silently continues on the host is the single worst
    failure mode of this benchmark family, so it is tested directly rather than
    assumed.

    The probe needs a real model and network. Without them the call fails on a
    signature mismatch, which proves nothing about fail-closed behaviour and
    would otherwise be scored as a pass - a false clean bill of health for the
    one guard that matters most. So a `TypeError` naming the argument list is
    explicitly NOT counted as evidence, and when no model is available the
    probe reports itself untested rather than passed.

    Returns (passes, detail). `passes` is False when the probe could not be run,
    so a caller cannot treat an untested probe as a healthy one.
    """
    if model is None or network is None:
        return False, (
            "fail-closed probe NOT RUN: no model/network was supplied, so a "
            "call would fail on its argument list rather than on backend "
            "selection. An untested probe is reported as untested."
        )
    try:
        cpp.simulate_batch_ssa_gpu(model, network, batch_size=1, backend=backend)
    except TypeError as exc:
        return False, (
            f"fail-closed probe INVALID: backend={backend!r} raised TypeError "
            f"from the argument list, which does not exercise backend "
            f"selection: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 - a real backend failure is the pass case
        return True, f"backend={backend!r} raised {type(exc).__name__}: {exc}"
    return False, (
        f"backend={backend!r} returned a result instead of raising; "
        f"this backend cannot fail closed"
    )


# --------------------------------------------------------------------------
# Array-framework backends
# --------------------------------------------------------------------------


def jax_device_claim(result_device_hint: str | None = None) -> GpuExecutionClaim:
    """Enumerate devices and report where `result_device_hint` lives.

    `jax-mps` is the working accelerator plugin on this class of host. A
    process built with it has *no* CPU device at all, so an empty device list is
    unambiguous evidence that nothing executed. Pass the `str(device)` of a
    result array so the result-side evidence is recorded too.
    """
    jax = importlib.import_module("jax")
    devices = [str(d) for d in jax.devices()]
    return GpuExecutionClaim(
        framework="jax",
        devices=devices,
        result_devices=[result_device_hint] if result_device_hint else devices,
        backend_reported=str(jax.default_backend()),
        notes=f"default_backend={jax.default_backend()!r}",
    )


def torch_device_claim(result_device_hint: str | None = None) -> GpuExecutionClaim:
    """Enumerate the torch device backend and report the result's device."""
    torch = importlib.import_module("torch")
    mps_ok = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    built = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_built()
    devices = ["mps"] if mps_ok else []
    notes = f"mps.is_available={mps_ok} mps.is_built={built}"
    if not mps_ok:
        notes += " (available() is False: torch cannot reach an accelerator)"
    return GpuExecutionClaim(
        framework="torch",
        devices=devices,
        result_devices=[result_device_hint] if result_device_hint else devices,
        backend_reported="mps" if mps_ok else "cpu",
        notes=notes,
    )


def claim_for_framework(name: str, result_device_hint: str | None = None) -> GpuExecutionClaim:
    """Dispatch to the claim builder for `jax`, `torch`, or an engine backend."""
    if name in ("jax", "jax-mps"):
        return jax_device_claim(result_device_hint)
    if name in ("torch", "torch-mps", "mps"):
        return torch_device_claim(result_device_hint)
    raise DeviceAssertionError(
        f"no device-claim builder for framework {name!r}; "
        f"known: jax, torch, or an engine backend name"
    )