#!/usr/bin/env python3
"""Build the CPU batch-SSA driver with the configured Ninja target flags.

Usage: build_driver_ninja.py <repo-root> <output-binary>

The driver links the same static libraries as bng_cpp. Extracting its compile
and link commands from Ninja avoids duplicating the CMake include paths,
definitions, LTO settings, and link dependencies in this benchmark helper.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path


def _link_command(words: list[str]) -> list[str]:
    start = next(
        (i for i, word in enumerate(words) if word not in {":", "&&"}),
        None,
    )
    if start is None:
        raise RuntimeError("empty Ninja link command")
    end = words.index("&&", start) if "&&" in words[start:] else len(words)
    return words[start:end]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo_root", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()

    root = args.repo_root.expanduser().resolve()
    build = root / "build"
    source = root / "benchmarks/batch_ssa/bench_batch_ssa.cpp"
    output = args.output.expanduser()
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    obj = build / "bench_batch_ssa.o"

    lines = subprocess.check_output(
        ["ninja", "-C", str(build), "-t", "commands", "bng_cpp"],
        text=True,
    ).splitlines()
    compile_words = None
    link_words = None
    for line in lines:
        words = shlex.split(line)
        if "-MT" in words and any(w.endswith("/cpp/main.cpp") for w in words):
            compile_words = words
        out_i = words.index("-o") if "-o" in words else -1
        if out_i >= 0 and out_i + 1 < len(words) and words[out_i + 1] == "cpp/bng_cpp":
            link_words = _link_command(words)
    if compile_words is None or link_words is None:
        raise RuntimeError(
            "could not extract configured compile/link commands for bng_cpp"
        )

    compile_args = []
    i = 0
    while i < len(compile_words):
        word = compile_words[i]
        if word == "-MD":
            i += 1
            continue
        if word in ("-MT", "-MF"):
            i += 2
            continue
        if word == "-o":
            compile_args.extend(["-o", str(obj)])
            i += 2
            continue
        if word == "-c":
            compile_args.extend(["-c", str(source)])
            i += 2
            continue
        compile_args.append(word)
        i += 1
    subprocess.run(compile_args, cwd=build, check=True)

    link_args = [
        str(obj) if word == "cpp/CMakeFiles/bng_cpp.dir/main.cpp.o" else word
        for word in link_words
    ]
    output_index = link_args.index("-o")
    link_args[output_index + 1] = str(output)
    subprocess.run(link_args, cwd=build, check=True)
    print(f"built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
