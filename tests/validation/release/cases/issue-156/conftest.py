import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
_repo = Path(__file__).resolve().parents[5]
_tests_python = _repo / "tests" / "python"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
if str(_tests_python) not in sys.path:
    sys.path.insert(0, str(_tests_python))
