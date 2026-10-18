"""Isolated public-API legs for the integration matrix; no oracle substitution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


def write_result(result, path):
    import numpy as np

    names = list(result.observables)
    values = np.column_stack([result.time] + [result.observables[n] for n in names])
    np.savetxt(path, values, header="time " + " ".join(names), fmt="%.17g")


class HarnessError(RuntimeError):
    pass


def write_legacy_result(result):
    import numpy as np

    if set(result.gdats) != {"model"}:
        raise RuntimeError(
            f"returned result lost/duplicated model output: {list(result.gdats)}"
        )
    data = result.gdats["model"]
    np.savetxt(
        "api.gdat",
        np.column_stack([data[n] for n in data.dtype.names]),
        header=" ".join(data.dtype.names),
        fmt="%.17g",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("atomizer", "api", "nf", "pybng", "compat")
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--atomize", action="store_true")
    parser.add_argument("--upstream", type=Path)
    args = parser.parse_args()
    if args.operation == "pybng":
        # -I excludes inherited PYTHONPATH and user site paths. The dedicated interpreter has dependencies, not a second BNG3.
        root = args.upstream.resolve()
        sys.path.insert(0, str(root))
        import bionetgen
        from bionetgen.modelapi import runner
        from bionetgen.main import get_conf

        get_conf()["bngpath"] = os.environ["BNGPATH"]

        package = Path(bionetgen.__file__).resolve()
        runner_path = Path(runner.__file__).resolve()
        if package.parent != root / "bionetgen" or not runner_path.is_relative_to(root):
            raise HarnessError("upstream worker imported a different bionetgen package")
        identity = {
            "package_file": str(package),
            "runner_file": str(runner_path),
            "runner_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
            "python_executable": sys.executable,
            "python_prefix": sys.prefix,
            "bngpath": os.environ["BNGPATH"],
            "simulator": "subprocess",
        }
        Path("identity.json").write_text(json.dumps(identity, indent=2) + "\n")
        # Exercise the public upstream API, force the independently built BNG2
        # rather than an optional BNGsim or a downloaded bundled executable.
        result = bionetgen.run(
            str(args.input),
            str(Path.cwd()),
            suppress=True,
            timeout=30,
            simulator="subprocess",
        )
        write_legacy_result(result)
        return

    # Only expose the repository's identity helper, never its python/ package.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.ci.check_python_package_identity import inspect_installed_package

    try:
        identity = inspect_installed_package()
    except RuntimeError as exc:
        raise HarnessError(str(exc)) from exc
    Path("identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    import bionetgen

    if args.operation == "atomizer":
        text = bionetgen.sbml_to_bngl(
            str(args.input),
            atomize=args.atomize,
            use_id=True,
            actions="",
        )
        Path("model.bngl").write_text(text)
    elif args.operation == "api":
        model = bionetgen.load(str(args.input))
        model.generate_network()
        model.write_net("model.net")
        write_result(model.simulate(method="ode", t_end=2, n_steps=10), "api.gdat")
    elif args.operation == "compat":
        result = bionetgen.run(str(args.input), str(Path.cwd()), suppress=True)
        write_legacy_result(result)
    else:
        model = bionetgen.load(str(args.input))
        result = model.simulate(method="nf", t_end=2, n_steps=10, seed=7)
        if result.construction_path != "direct":
            raise RuntimeError(f"NFsim path changed: {result.construction_path}")
        write_result(result, "nf.gdat")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        Path("worker-status.json").write_text(
            json.dumps(
                {
                    "status": (
                        "HARNESS_ERROR"
                        if isinstance(exc, (HarnessError, ImportError))
                        else "FAIL"
                    ),
                    "exception_type": type(exc).__name__,
                    "detail": str(exc),
                },
                indent=2,
            )
            + "\n"
        )
        raise
