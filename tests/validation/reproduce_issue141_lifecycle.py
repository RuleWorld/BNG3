"""Repeat the Python/native issue 141 exception and concurrent-lifecycle path."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import tempfile

import bionetgen

from tests.validation.integrated_cases import generated_cases, reuse_bngl
from tests.validation.integrated_protocol import (
    _lifecycle_construction_isolation,
    _result_difference,
)


def _exception_recovery(source: Path) -> None:
    model = bionetgen.load(source)
    options = dict(method="ode", t_end=1.0, n_steps=2)
    baseline = model.simulate(**options)
    network = model._network
    for condition in (
        "__integrated_protocol_missing_name__ > 0",
        "if(time > 0, __integrated_protocol_missing_name__, 0)",
    ):
        try:
            model.simulate(stop_if=condition, **options)
        except RuntimeError as error:
            if "__integrated_protocol_missing_name__" not in str(error):
                raise
        else:
            raise AssertionError("invalid stop_if did not raise RuntimeError")
        if model._network is not network:
            raise AssertionError("exception discarded the generated network")
        actual = model.simulate(**options)
        expected = bionetgen.load(source).simulate(**options)
        difference = _result_difference(actual, expected)
        if difference:
            raise AssertionError(f"recovery differed from fresh source: {difference}")
        difference = _result_difference(baseline, model.simulate(**options))
        if difference:
            raise AssertionError(f"saved baseline changed after recovery: {difference}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=25)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")

    native = Path(bionetgen._bionetgen_cpp.__file__).resolve()
    identity = {
        "native_extension": str(native),
        "native_extension_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "iterations": args.iterations,
    }
    print(json.dumps(identity, sort_keys=True), flush=True)

    case = next(
        item
        for item in generated_cases(full=True)
        if item["id"] == "dimerization-v3-n80-r0-a0"
    )
    with tempfile.TemporaryDirectory(prefix="bng3-issue141-") as temporary:
        directory = Path(temporary)
        source = directory / "dimerization-v3-n80-r0-a0.bngl"
        source.write_text(reuse_bngl(case))
        for iteration in range(args.iterations):
            print(f"iteration={iteration} stage=exception-recovery", flush=True)
            _exception_recovery(source)
            print(f"iteration={iteration} stage=concurrent-lifecycle", flush=True)
            difference = _lifecycle_construction_isolation(bionetgen, case, directory)
            if difference:
                raise AssertionError(
                    f"concurrent construction/isolation differed: {difference}"
                )
            gc.collect()
    print("completed all requested iterations", flush=True)


if __name__ == "__main__":
    main()
