"""Positive and negative controls for #471 BNG2 probe consumer receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

CASE_DIR = Path(__file__).resolve().parent
ROOT = CASE_DIR.parents[4]
sys.path.insert(0, str(CASE_DIR))
sys.path.insert(0, str(ROOT))

import issue471_checks as checks  # noqa: E402
import test_record_issue471_bng2_receipts as base_fixture  # noqa: E402
from scripts.ci import record_issue471_bng2_probe_receipts as probes  # noqa: E402


def _write_fake_bng2(root: Path, bng2_root: Path) -> Path:
    script = bng2_root / "bng2/BNG2.pl"
    script.write_text(
        """#!/usr/bin/env perl
use strict;
use warnings;
my $file = $ARGV[0];
open(my $in, '<', $file) or die $!;
local $/; my $txt = <$in>; close($in);
if ($txt =~ /simulate\\(\\{/) {
    open(my $out, '>', 'probe.gdat') or die $!;
    print $out "# time A_obs\\n0.0 1.0\\n1.0 2.0\\n";
    close($out);
}
if ($txt =~ /generate_network\\(/) {
    my $net = $txt =~ /prefix=>"cust"/ ? 'cust_hpp.net' : ($txt =~ /suffix=>"hyb"/ ? 'probe_hyb.net' : ($txt =~ /generate_hybrid_model/ ? 'probe_hpp.net' : 'probe.net'));
    open(my $out, '>', $net) or die $!;
    print $out "# Created by BioNetGen 2.9.3\\nbegin species\\n  1 A() 1\\nend species\\nbegin reactions\\n  1 1 0 1\\nend reactions\\n";
    close($out);
}
exit 0;
""",
        encoding="utf-8",
    )
    return script


def _write_fake_cpp(bin_dir: Path, *, corrupt_gdat: bool = False) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "bng_cpp"
    gdat_line = "1.0 9.0" if corrupt_gdat else "1.0 2.0"
    exe.write_text(
        f"""#!/usr/bin/env python3
import sys
from pathlib import Path
txt = Path(sys.argv[1]).read_text(encoding='utf-8')
if '--version' in sys.argv:
    print('bng_cpp test')
    raise SystemExit(0)
if 'simulate(' in txt:
    Path('probe.gdat').write_text('# time A_obs\\n0.0 1.0\\n{gdat_line}\\n', encoding='utf-8')
if 'generate_network(' in txt:
    net = 'cust_hpp.net' if 'prefix=>"cust"' in txt else ('probe_hyb.net' if 'suffix=>"hyb"' in txt else ('probe_hpp.net' if 'generate_hybrid_model' in txt else 'probe.net'))
    Path(net).write_text('# Created by bng_cpp\\nbegin species\\n  1 A() 1\\nend species\\nbegin reactions\\n  1 1 0 1\\nend reactions\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return exe


def test_all_40_probe_rows_exist_and_are_implemented_in_matrix():
    matrix = json.loads((ROOT / "provenance/capability-matrix.yml").read_text())
    by_id = {row["id"]: row for row in matrix["rows"]}
    assert len(probes.PROBE_SPECS) == 40
    for row_id in probes.PROBE_SPECS:
        assert row_id in by_id
        assert by_id[row_id]["status"] == "implemented"


def test_probe_receipts_round_trip_and_reject_corrupted_consumer_and_wrong_pin(
    tmp_path: Path,
):
    repo, rev, _, bng2_root, _ = base_fixture._setup_fixture(tmp_path)
    _write_fake_bng2(repo, bng2_root)
    base_fixture._git(bng2_root, "add", "bng2/BNG2.pl")
    base_fixture._git(bng2_root, "commit", "-qm", "update mock perl oracle")
    mock_rev = base_fixture._git(bng2_root, "rev-parse", "HEAD")
    lock_path = repo / "provenance/upstreams.lock.yml"
    lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_data["sources"]["bionetgen"]["revision"] = mock_rev
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
    base_fixture._git(repo, "add", "provenance/upstreams.lock.yml")
    base_fixture._git(repo, "commit", "-qm", "pin mock bng2")
    rev = base_fixture._git(repo, "rev-parse", "HEAD")

    cpp_ok = _write_fake_cpp(tmp_path / "bin-ok")
    receipts = tmp_path / "receipts"
    artifacts = tmp_path / "artifacts"
    selected = ["builtin.exp", "operator.357", "bngl.null-reactants-and-products"]
    summary = probes.build_bng2_probe_receipts(
        root=repo,
        revision=rev,
        bng2_root=bng2_root,
        bng_cpp=cpp_ok,
        receipts_dir=receipts,
        artifacts_dir=artifacts,
        rows=selected,
    )
    assert summary["emitted_rows"] == selected
    report = checks.oracle_independence_report(repo, receipts, rev, artifacts)
    assert report["grounded_execution_rows"] == 3

    # Corrupt consumer numeric output must fail fail-closed.
    cpp_bad = _write_fake_cpp(tmp_path / "bin-bad", corrupt_gdat=True)
    with pytest.raises(ValueError, match="numeric mismatch"):
        probes.build_bng2_probe_receipts(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            bng_cpp=cpp_bad,
            receipts_dir=tmp_path / "r-bad",
            artifacts_dir=tmp_path / "a-bad",
            rows=["builtin.exp"],
        )

    # Mismatched upstream revision must fail fail-closed.
    lock_data["sources"]["bionetgen"]["revision"] = "0" * 40
    lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="locked"):
        probes.build_bng2_probe_receipts(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            bng_cpp=cpp_ok,
            receipts_dir=tmp_path / "r-pin",
            artifacts_dir=tmp_path / "a-pin",
            rows=["builtin.exp"],
            allow_dirty=True,
        )
