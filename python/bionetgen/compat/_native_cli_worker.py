"""Execute native BNGL actions in a process bound to the caller's runtime."""

import json
from pathlib import Path
import sys


def main():
    source, package_file, native_file, verbose, *payload = sys.argv[1:]
    package_file = Path(package_file).resolve()
    native_file = Path(native_file).resolve()
    sys.path[:0] = [str(package_file.parent.parent), str(native_file.parent)]

    import bionetgen
    from bionetgen.model import _cpp

    if Path(bionetgen.__file__).resolve() != package_file:
        raise RuntimeError("native CLI worker imported a different Python package")
    if _cpp is None or Path(_cpp.__file__).resolve() != native_file:
        raise RuntimeError("native CLI worker imported a different native extension")
    if payload:
        options = json.loads(payload[0])
        if not isinstance(options, dict) or len(payload) not in (1, 2):
            raise ValueError("native compatibility options must be one JSON object")
        if len(payload) == 2:
            from bionetgen.compat._native_process import _write_sim_result
            from bionetgen.model import load

            result = load(source).simulate(**options)
            _write_sim_result(payload[1], result)
        else:
            from bionetgen.compat.runner import run

            run(
                source,
                out=Path(source).parent,
                suppress=verbose != "1",
                timeout=None,
                simulator="native",
                **options,
            )
    else:
        model = _cpp.parse_file(source)
        _cpp.execute(model, source, verbose=verbose == "1")


if __name__ == "__main__":
    main()
