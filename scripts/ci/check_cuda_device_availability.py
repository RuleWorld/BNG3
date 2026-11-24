#!/usr/bin/env python3
"""Record the current CUDA device and hosted-runner availability.

The script never claims a CUDA result.  It records the observable facts that
decide whether the CUDA lanes of #474 can run: a local NVIDIA device, a CUDA
compiler, a self-hosted runner visible through authenticated ``gh``, and any
existing runs of the device-qualification workflow.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKFLOW = "gpu-device-qualification.yml"


def _run(argv: list[str]) -> dict:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip()[:2000],
        "stderr": proc.stderr.strip()[:2000],
    }


def probe() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    nvcc = shutil.which("nvcc")
    runners = _run(
        ["gh", "api", "repos/RuleWorld/BNG3/actions/runners", "--jq", ".total_count"]
    )
    runs = _run(
        [
            "gh",
            "api",
            f"repos/RuleWorld/BNG3/actions/workflows/{WORKFLOW}/runs",
            "--jq",
            ".total_count",
        ]
    )
    device_available = bool(nvidia_smi) and bool(nvcc)
    runner_available = bool(runners["ok"] and runners.get("stdout", "").strip() != "0")
    existing_runs = (
        int(runs["stdout"])
        if runs["ok"] and runs.get("stdout", "").strip().isdigit()
        else None
    )
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "local_device": {
            "nvidia_smi": nvidia_smi,
            "nvcc": nvcc,
            "available": device_available,
        },
        "hosted_runner": {
            "api": runners,
            "available": runner_available,
        },
        "workflow": {
            "path": f".github/workflows/{WORKFLOW}",
            "runs": runs,
            "total_runs": existing_runs,
        },
        "verdict": {
            "cuda_execution_available": device_available or runner_available,
            "status": "AVAILABLE" if (device_available or runner_available) else "BLOCKED",
            "detail": (
                "No local NVIDIA device/CUDA compiler and no usable hosted CUDA "
                "runner were observed; CUDA device execution is externally blocked."
                if not (device_available or runner_available)
                else "CUDA execution resources were observed; qualification may run."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    result = probe()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "CUDA execution "
        + result["verdict"]["status"]
        + ": "
        + result["verdict"]["detail"]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
