from pathlib import Path
import subprocess
import sys


def test_architecture_dependency_ratchet():
    root = Path(__file__).parents[2]
    completed = subprocess.run(
        [sys.executable, str(root / "tools" / "check_architecture_dependencies.py")],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
