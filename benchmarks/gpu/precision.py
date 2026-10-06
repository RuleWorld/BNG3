"""Precision guard: what dtype actually produced these numbers.

On an accelerator that has no double-precision path, a comparison between two
runs is a comparison between two different numeric types. That is a fact about
the arithmetic, not a defect, and it changes what a validation claim may say:

* An accelerator trajectory computed in single precision cannot be bit-identical
  to a host trajectory computed in double precision, no matter how correct the
  algorithm is. Bit-equality is not merely "not expected" there, it is
  unreachable by construction, and a claim that demanded it would be demanding
  a contradiction.
* Worse, a framework configured for single precision can silently truncate a
  double-precision input at the device boundary and emit no warning at all. The
  declared Python dtype then lies about the arithmetic that ran. So the only
  trustworthy dtype evidence is read off a result object that the device
  produced, never off an input that was handed in.

This module therefore does two things the harness relies on:

1. `assert_result_dtype` reads the dtype of a real result and fails when it is
   not what the caller claims, so "float64" cannot be asserted about an array
   the device already rounded.
2. `PrecisionClaim` records, per arm, the dtype arithmetic ran in and whether a
   host reference existed, and `comparability` turns that into the strongest
   equivalence statement the data can support:

   * same dtype on both sides  -> bit-identity is a *possible* claim (still
     requires the numbers to actually match, since an RNG stream difference
     alone would break it for a stochastic algorithm);
   * different dtype, or an
     accelerator in single precision -> the strongest available claim is
     statistical, and the harness labels it as such rather than upgrading it.

Callers must pass `result_dtype` from an output object. Passing the dtype of an
input is a known trap and is documented as such on the parameter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


class PrecisionAssertionError(AssertionError):
    """Raised when a result's dtype is not what the caller claimed."""


def describe_dtype(obj: Any) -> str:
    """Best-effort dtype string for a numpy array, framework tensor, or scalar.

    Handles the three shapes that matter here: numpy arrays (`.dtype`),
    framework tensors (`.dtype` on a jax/torch tensor), and pybind11 arrays
    (which expose `.dtype` as a type object). Returns "unknown" rather than
    raising, because a caller asking about dtype must never be the thing that
    crashes a benchmark.
    """
    dtype = getattr(obj, "dtype", None)
    if dtype is None:
        return "unknown"
    name = getattr(dtype, "name", None)
    if name:
        return str(name)
    return str(dtype)


def _dtype_rank(name: str) -> int:
    """Bits of mantissa implied by a dtype name; 0 when unknown."""
    lowered = name.lower()
    for bits, token in ((64, "64"), (32, "32"), (16, "16")):
        if token in lowered:
            return bits
    if "double" in lowered:
        return 64
    if "float" in lowered:
        return 32
    return 0


def is_double(name: str) -> bool:
    return _dtype_rank(name) == 64


def is_single(name: str) -> bool:
    return _dtype_rank(name) == 32


def assert_result_dtype(result: Any, expected: str, what: str = "result") -> str:
    """Assert that a real output object has dtype `expected`; return its dtype.

    `result` must be an object the computation produced. Passing an input array
    defeats the purpose: an input can carry a double-precision type in Python
    while the device has already stored it in single precision, so the declared
    dtype is then a statement about the caller rather than about the arithmetic.

    `expected` is matched loosely ("float32" matches "float", "<f4", "32")
    because the three dtype spellings differ across the backends this harness
    talks to. The comparison is on mantissa width, which is the thing that
    actually determines whether two runs are comparable.
    """
    actual = describe_dtype(result)
    want_bits = _dtype_rank(expected)
    have_bits = _dtype_rank(actual)
    if want_bits == 0:
        raise PrecisionAssertionError(
            f"cannot interpret expected dtype {expected!r}; use a name "
            f"containing 64, 32 or 16"
        )
    if have_bits == 0:
        raise PrecisionAssertionError(
            f"{what}: dtype is unknown ({actual!r}); cannot substantiate the "
            f"claim that arithmetic ran in {expected!r}"
        )
    if have_bits != want_bits:
        raise PrecisionAssertionError(
            f"{what}: expected {expected!r} ({want_bits}-bit) but the result "
            f"object reports {actual!r} ({have_bits}-bit). A declared dtype that "
            f"disagrees with the result is a silent-precision-change signature; "
            f"the claim about what ran is unsupported."
        )
        return actual


@dataclass
class PrecisionClaim:
    """What numeric type each side of a comparison actually ran in.

    Attributes:
        host_dtype: dtype of the host-side result, read off the result object.
        device_dtype: dtype of the accelerator-side result, or None.
        closed_form_dtype: dtype a closed-form reference was computed in, if the
            validation used one. Recorded because a single-precision sample
            compared against a double-precision analytic reference can disagree
            for arithmetic reasons alone, and those must not be reported as an
            algorithmic defect.
        notes: free-form detail for the report.
    """

    host_dtype: str = "unknown"
    device_dtype: str | None = None
    closed_form_dtype: str | None = None
    notes: str = ""

    def comparability(self) -> dict[str, Any]:
        """The strongest equivalence statement this dtype pairing supports."""
        host_bits = _dtype_rank(self.host_dtype)
        dev_bits = _dtype_rank(self.device_dtype or "")

        if self.device_dtype is None:
            basis = "same-run"
            level = "exact"
            reason = (
                "no accelerator side in this comparison; only same-input "
                "reproducibility is testable"
            )
        elif dev_bits == 0 or host_bits == 0:
            basis = "undetermined"
            level = "statistical"
            reason = (
                "the arithmetic dtype of at least one side could not be read "
                "off a result object, so bit-identity cannot be claimed even in "
                "principle"
            )
        elif dev_bits == host_bits:
            basis = "same-dtype"
            level = "bit-identity-possible"
            reason = (
                f"both sides computed in {self.host_dtype!r}; bit-identity is a "
                f"meaningful claim to test, though for a stochastic algorithm a "
                f"different RNG stream alone will break it"
            )
        else:
            basis = "mixed-dtype"
            level = "statistical"
            reason = (
                f"host computed in {self.host_dtype!r}, accelerator in "
                f"{self.device_dtype!r}. Different arithmetic precisions cannot "
                f"agree bit-for-bit by construction, so bit-equality is not a "
                f"meaningful target and only distributional equivalence is "
                f"claimable."
            )

        closed_form_gap = None
        if self.closed_form_dtype:
            cf_bits = _dtype_rank(self.closed_form_dtype)
            sampled = [b for b in (dev_bits, host_bits) if b]
            # The hazard is a NARROW sampled run compared against a WIDER closed
            # form: the disagreement then comes from precision alone and must
            # not be reported as an algorithmic defect. The narrowest sampled
            # side governs, not the widest - a single-precision sample checked
            # against a double-precision reference is exposed regardless of what
            # the host side did.
            if cf_bits and sampled and min(sampled) < cf_bits:
                narrowest = min(sampled)
                closed_form_gap = (
                    f"the closed-form reference is {self.closed_form_dtype!r} "
                    f"but a sampled side ran in {narrowest}-bit arithmetic; "
                    f"disagreement with the reference is expected from "
                    f"precision alone and must not be reported as an algorithmic "
                    f"defect without first ruling precision out"
                )
            elif cf_bits and sampled and min(sampled) > cf_bits:
                closed_form_gap = (
                    f"the closed-form reference is {self.closed_form_dtype!r}, "
                    f"narrower than the {min(sampled)}-bit sampled runs; the "
                    f"reference is the less precise side here, so it bounds "
                    f"attainable agreement"
                )

        return {
            "host_dtype": self.host_dtype,
            "device_dtype": self.device_dtype,
            "closed_form_dtype": self.closed_form_dtype,
            "comparability_basis": basis,
            "strongest_claim": level,
            "reason": reason,
            "closed_form_caveat": closed_form_gap,
            "notes": self.notes,
        }

    def as_dict(self) -> dict[str, Any]:
        return self.comparability()


def single_precision_device_note() -> str:
    """The standing caveat for single-precision accelerator backends.

    Quoted verbatim in reports so a reader of a speedup number also reads the
    arithmetic that produced it.
    """
    return (
        "An accelerator trajectory computed in single precision is not "
        "bit-comparable to a double-precision host trajectory. Any host/device "
        "agreement claim for stochastic results on such a backend is therefore "
        "statistical by construction, and a throughput number measured beside it "
        "describes single-precision arithmetic."
    )


def tolerance_for(levels: list[str], n_cells: int, alpha: float = 0.001) -> float:
    """A z-threshold accounting for how many comparisons are being made.

    `levels` are the per-cell deviations actually observed (z-scores, in units
    of the pooled standard error). With `n_cells` independent-ish comparisons,
    the largest deviation expected by chance grows with log(n_cells), so a
    fixed 3.0 threshold is not comparable across models of different sizes.
    This returns the Bonferroni-style threshold

        z* = Phi^-1(1 - alpha / (2 * n_cells))

    via the inverse normal CDF, so a per-cell threshold can be tightened to
    keep the family-wise error at `alpha`. Using the correct threshold matters:
    a harness that declares a fixed threshold either cries wolf on large models
    or misses real defects on small ones.

    Returns 3.0 when the cell count is degenerate, matching the conventional
    three-sigma figure rather than dividing by zero.
    """
    n = max(1, int(n_cells))
    if n <= 1:
        return 3.0
    tail = alpha / (2.0 * n)
    if tail <= 0.0:
        return 3.0
    # Two-sided inverse normal CDF.
    return _inv_norm_cdf(1.0 - tail)


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard-normal CDF, Acklam's rational approximation.

    Accurate to about 1.15e-9 in the tails, which is far tighter than any
    threshold decision this harness makes. Implemented here rather than taken
    from a statistics package so the harness stays dependency-free.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low, p_high = 0.02425, 1.0 - 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > p_high:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )
