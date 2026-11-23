"""Run a single SBML comparison in the isolated sbmlsim-core runtime."""

import hashlib
import importlib.metadata
import json
import sys


def main() -> None:
    import sbmlsim_core

    version = importlib.metadata.version("sbmlsim-core")
    if version != "0.20.0":
        raise RuntimeError(f"unexpected sbmlsim-core version: {version}")
    case = json.load(sys.stdin)
    source = case["sbml"]
    times = case["times"]
    compiled = sbmlsim_core.compile_sbml(source)
    runtime = sbmlsim_core.Runtime()
    instance = runtime.load(compiled.wasm, compiled.description).instance()
    result = instance.simulate(
        {
            "contract": "simulation/1",
            "start": times[0],
            "end": times[-1],
            "output": {"times": times},
            "selections": case["selections"],
            "preinit": [],
            "changes": [],
            "steady_state": None,
            "steady_state_after": None,
            "before_events": False,
            "sensitivities": [],
            "settings": {
                "relative_tolerance": case["rtol"],
                "absolute_tolerance": {"scalar": case["atol"]},
                "maximum_num_steps": 20000,
                "maximum_time_step": case["max_step"],
                "initial_time_step": 0.0,
                "stiff": True,
                "linear_solver": "auto",
                "jacobian": "auto",
            },
            "seed": 1,
        }
    )
    json.dump(
        {
            "version": version,
            "sbml_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "columns": result.columns,
            "values": result.values.tolist(),
        },
        sys.stdout,
        allow_nan=False,
    )


if __name__ == "__main__":
    main()
