"""Source-derived regression for legacy network-graph label trimming."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PERL_INCLUDE = REPO / "legacy" / "perl" / "Perl2"
NETWORK_GRAPH = PERL_INCLUDE / "Visualization" / "NetworkGraph.pm"

pytestmark = pytest.mark.skipif(
    shutil.which("perl") is None or not NETWORK_GRAPH.is_file(),
    reason="legacy Perl visualization modules are unavailable",
)


def _unprettify(value: str) -> str:
    result = subprocess.run(
        [
            "perl",
            f"-I{PERL_INCLUDE}",
            "-MVisualization::NetworkGraph",
            "-e",
            "print Viz::unprettify($ARGV[0]);",
            value,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_legacy_network_graph_trims_only_synthetic_empty_side_zeros():
    """The dca95a6a fix must preserve molecule names containing boundary zeros."""

    assert _unprettify("0->A()") == "->A"
    assert _unprettify("A()->0") == "A->"
    assert _unprettify("0A()->B()") == "0A->B"
    assert _unprettify("A()->B0()") == "A->B0"
