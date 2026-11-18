"""Differential checks for source changes in the accepted BNG2 range."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from tests.validation import compare, oracle_perl
from tests.validation.strict import require_oracle

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name",
    ["Motivating_example_cBNGL", "energy_example1"],
    ids=["invalid-compartment-product", "shared-arrhenius-normalization"],
)
def test_retained_perl_network_matches_upstream_fix(name, tmp_path, record_property):
    """Reproduce upstream #339 and #340 through BNG3's retained Perl route."""
    upstream_perl = oracle_perl._bng2_path()
    require_oracle(upstream_perl is not None, "set BNG2_PERL to the pinned BNG2.pl")
    assert upstream_perl is not None
    relative_source = Path("bng2/Models2") / f"{name}.bngl"
    upstream_root = upstream_perl.parent.parent
    source_bytes = (upstream_root / relative_source).read_bytes()
    pinned_bytes = subprocess.check_output(
        ["git", "-C", str(upstream_root), "cat-file", "blob", f"HEAD:{relative_source}"]
    )
    assert source_bytes == pinned_bytes, relative_source
    record_property("upstream_fixture", str(relative_source))
    record_property("fixture_sha256", hashlib.sha256(source_bytes).hexdigest())
    model_text = source_bytes.decode("utf-8").replace("\r\n", "\n")
    model, end, _ = model_text.partition("end model")
    assert end
    # This check compares the generated network. The retained interpreter
    # does not carry upstream release metadata for the version() directive.
    if name == "energy_example1":
        assert model.count('version("2.2.4")\n') == 1
        model = model.replace('version("2.2.4")\n', "", 1)
    text = model + end + "\ngenerate_network({overwrite=>1})\n"
    networks = {}
    for label, perl in (
        ("pinned BNG2", upstream_perl),
        ("retained Perl", ROOT / "legacy/perl/BNG2.pl"),
    ):
        work = tmp_path / label
        work.mkdir()
        staged = work / f"{name}.bngl"
        staged.write_text(text, encoding="utf-8")
        result = subprocess.run(
            ["perl", str(perl), str(staged)],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, f"{label}: {result.stdout}\n{result.stderr}"
        net = compare.parse_net(work / f"{name}.net")
        assert net is not None, label
        networks[label] = net

    diff = compare.compare_net(networks["pinned BNG2"], networks["retained Perl"])
    assert diff.ok, diff.summary()
