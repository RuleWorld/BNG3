"""Qualify a built BNG3 wheel from an isolated install target."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def _run_installed(wheel: Path, model: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="bng3-wheel-qualify-") as temp:
        root = Path(temp)
        install_dir = root / "site"
        output_dir = root / "legacy-results"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(install_dir),
                str(wheel),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        probe = root / "probe.py"
        probe.write_text(
            """\
import json
from pathlib import Path
import bionetgen

model = Path(__import__('sys').argv[1]).resolve()
legacy_output = Path(__import__('sys').argv[2]).resolve()
modern = bionetgen.run(model, method='ode', t_end=1.0, n_steps=2)
legacy = bionetgen.run(
    model,
    out=legacy_output,
    method='ode',
    t_span=(2.0, 3.0),
    n_points=3,
)
legacy_data = legacy.gdats[model.stem]
print(json.dumps({
    'package_file': str(Path(bionetgen.__file__).resolve()),
    'version': bionetgen.__version__,
    'modern_time_points': len(modern.time),
    'modern_observables': sorted(modern.observables),
    'legacy_time_points': len(legacy_data),
    'legacy_time_start': float(legacy_data['time'][0]),
    'legacy_time_end': float(legacy_data['time'][-1]),
    'legacy_gdat': str(legacy_output / (model.stem + '.gdat')),
}))
""",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(install_dir)
        result = subprocess.run(
            [sys.executable, str(probe), str(model), str(output_dir)],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        report["wheel"] = str(wheel)
        report["model"] = str(model)
        report["qualification"] = "passed"
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()

    wheel = args.wheel.resolve()
    model = args.model.resolve()
    if wheel.suffix != ".whl" or not wheel.is_file():
        parser.error(f"wheel does not exist: {wheel}")
    if not model.is_file():
        parser.error(f"model does not exist: {model}")
    try:
        report = _run_installed(wheel, model)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ERROR: installed-package qualification failed: {exc}", file=sys.stderr)
        return 1
    args.json.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.json.resolve().write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
