"""Small subprocess probe using the existing source/installed identity guard."""

import json
import sys
from pathlib import Path

from .inventory import sha256
from .runner import _ensure_source_python_path


def main():
    _ensure_source_python_path()
    import bionetgen
    import bionetgen.model as model

    if model._cpp is None or bionetgen.BioNetGenModel.__module__ != "bionetgen.model":
        raise RuntimeError("native package unavailable or unexpected legacy fallback")
    record = {
        "package": bionetgen.__file__,
        "native_extension": model._cpp.__file__,
        "native_sha256": sha256(Path(model._cpp.__file__)),
        "model_class": bionetgen.BioNetGenModel.__module__,
    }
    Path(sys.argv[1]).write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
