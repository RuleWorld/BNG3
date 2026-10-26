"""Repeat the Python/native issue 141 exception and concurrent-lifecycle path."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import tempfile

import bionetgen
import bionetgen.model as bionetgen_model

from tests.validation.integrated_cases import generated_cases, reuse_bngl
from tests.validation.integrated_protocol import (
    _lifecycle_construction_isolation,
    _lifecycle_mutation_baseline,
    _reuse_source_controls,
    _result_difference,
    _antlr_thread_local_cache_enabled,
)


def _native_extension_path(model_module) -> Path:
    """Use the extension already bound by bionetgen.model."""
    native = getattr(model_module, "_cpp", None)
    if native is None or not getattr(native, "__file__", None):
        raise RuntimeError("bionetgen.model did not bind a native extension")
    return Path(native.__file__).resolve()


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

    native = _native_extension_path(bionetgen_model)
    identity = {
        "native_extension": str(native),
        "native_extension_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "iterations": args.iterations,
    }
    compile_commands = json.loads(Path("build/compile_commands.json").read_text())
    parser_commands = [
        command
        for command in compile_commands
        if Path(command.get("file", "")).name in {"BNGParser.cpp", "BNGLexer.cpp"}
        and "/parser/generated/" in command.get("file", "").replace("\\", "/")
    ]
    if {Path(command["file"]).name for command in parser_commands} != {
        "BNGParser.cpp",
        "BNGLexer.cpp",
    }:
        raise RuntimeError("compile database is missing generated BNG parser sources")
    modes = {_antlr_thread_local_cache_enabled(command) for command in parser_commands}
    if len(modes) != 1:
        raise RuntimeError("lexer/parser ANTLR DFA cache modes differ")
    thread_local_dfa_cache = modes.pop()
    identity["antlr_dfa_cache_mode"] = (
        "thread-local" if thread_local_dfa_cache else "shared"
    )
    identity["antlr_parser_init"] = (
        "per-thread" if thread_local_dfa_cache else "shared call_once"
    )
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
            print(
                f"iteration={iteration} stage=lifecycle-mutation-baseline", flush=True
            )
            difference = _lifecycle_mutation_baseline(bionetgen, case, directory)
            if difference:
                raise AssertionError(f"lifecycle mutation differed: {difference}")
            print(f"iteration={iteration} stage=parameter-source-controls", flush=True)
            _reuse_source_controls(bionetgen, case, directory)
            gc.collect()
    print("completed all requested iterations", flush=True)


if __name__ == "__main__":
    main()
