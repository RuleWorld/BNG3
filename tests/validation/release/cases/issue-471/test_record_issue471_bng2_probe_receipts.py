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
my $hybrid_bngl = "# Created by BioNetGen 2.9.3\\nbegin model\\nbegin parameters\\n  k 0.5\\n  k_pop 100\\nend parameters\\nbegin molecule types\\n  A()\\n  A_pop() population\\n  B()\\nend molecule types\\nbegin observables\\n  Molecules A_obs A() A_pop()\\n  Molecules B_obs B()\\nend observables\\nbegin species\\n  A_pop() 10\\nend species\\nbegin reaction rules\\n  R1_v1: A_pop() -> B() k\\n  _MapRule0: A() -> A_pop() k_pop\\nend reaction rules\\nend model\\n\\n## model actions ##\\nwriteXML()\\n";
my $hybrid_xml = "<?xml version=\\"1.0\\" encoding=\\"UTF-8\\"?>\\n<sbml xmlns=\\"http://www.sbml.org/sbml/level3\\" level=\\"3\\" version=\\"1\\"><model id=\\"probe_hpp\\"><ListOfParameters><Parameter id=\\"k\\" type=\\"Constant\\" value=\\"0.5\\"/><Parameter id=\\"k_pop\\" type=\\"Constant\\" value=\\"100\\"/></ListOfParameters><ListOfMoleculeTypes><MoleculeType id=\\"A\\"/><MoleculeType id=\\"A_pop\\" population=\\"1\\"/><MoleculeType id=\\"B\\"/></ListOfMoleculeTypes><ListOfSpecies><Species id=\\"S1\\" concentration=\\"10\\" name=\\"A_pop()\\"><ListOfMolecules><Molecule id=\\"S1_M1\\" name=\\"A_pop\\"/></ListOfMolecules></Species></ListOfSpecies><ListOfReactionRules><ReactionRule id=\\"RR1\\" name=\\"R1_v1\\"><ListOfReactantPatterns><ReactantPattern id=\\"RR1_RP1\\"><ListOfMolecules><Molecule id=\\"RR1_RP1_M1\\" name=\\"A_pop\\"/></ListOfMolecules></ReactantPattern></ListOfReactantPatterns><ListOfProductPatterns><ProductPattern id=\\"RR1_PP1\\"><ListOfMolecules><Molecule id=\\"RR1_PP1_M1\\" name=\\"B\\"/></ListOfMolecules></ProductPattern></ListOfProductPatterns><RateLaw id=\\"RR1_RateLaw\\" type=\\"Ele\\" totalrate=\\"0\\"><ListOfRateConstants><RateConstant value=\\"k\\"/></ListOfRateConstants></RateLaw><ListOfOperations><Add id=\\"RR1_PP1_M1\\"/><Delete id=\\"RR1_RP1\\" DeleteMolecules=\\"0\\"/></ListOfOperations></ReactionRule></ListOfReactionRules><ListOfObservables><Observable id=\\"O1\\" name=\\"A_obs\\" type=\\"Molecules\\"><ListOfPatterns><Pattern id=\\"O1_P1\\"><ListOfMolecules><Molecule id=\\"O1_P1_M1\\" name=\\"A\\"/></ListOfMolecules></Pattern></ListOfPatterns></Observable></ListOfObservables></model></sbml>\\n";
if ($txt =~ /simulate\\(\\{/) {
    open(my $out, '>', 'probe.gdat') or die $!;
    print $out "# time A_obs\\n0.0 1.0\\n1.0 2.0\\n";
    close($out);
}
if ($txt =~ /generate_hybrid_model\\(/) {
    my $target = $txt =~ /prefix=>"cust"/ ? 'cust_hpp.bngl' : ($txt =~ /suffix=>"hyb"/ ? 'probe_hyb.bngl' : 'probe_hpp.bngl');
    if ($txt =~ /overwrite=>0/ && -e $target) {
        die "Refusing overwrite=>0 for $target\\n";
    }
    print "      verbose => 1\\n" if $txt =~ /verbose=>1/;
    open(my $out, '>', $target) or die $!;
    print $out $hybrid_bngl;
    close($out);
    if ($txt =~ /execute=>1/ && $txt =~ /writeXML\\(\\)/) {
        open(my $xout, '>', 'probe_hpp.xml') or die $!;
        print $xout $hybrid_xml;
        close($xout);
    }
}
if ($txt =~ /writeXML\\(/ && $txt !~ /generate_hybrid_model\\(/) {
    open(my $xout, '>', 'probe.xml') or die $!;
    print $xout $hybrid_xml;
    close($xout);
}
if ($txt =~ /generate_network\\(/) {
    open(my $out, '>', 'probe.net') or die $!;
    print $out "# Created by BioNetGen 2.9.3\\nbegin species\\n  1 A() 1\\nend species\\nbegin reactions\\n  1 1 0 1\\nend reactions\\n";
    close($out);
}
exit 0;
""",
        encoding="utf-8",
    )
    return script


def _write_fake_cpp(
    bin_dir: Path, *, corrupt_gdat: bool = False, corrupt_hybrid: bool = False
) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "bng_cpp"
    gdat_line = "1.0 9.0" if corrupt_gdat else "1.0 2.0"
    rate_val = "0.99" if corrupt_hybrid else "0.5"
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
if 'generate_hybrid_model(' in txt:
    target = 'cust_hpp.bngl' if 'prefix=>"cust"' in txt else ('probe_hyb.bngl' if 'suffix=>"hyb"' in txt else 'probe_hpp.bngl')
    if 'overwrite=>0' in txt and Path(target).exists():
        print(f'ABORT: overwrite=>0 refuses {{target}}', file=sys.stderr)
        raise SystemExit(1)
    if 'verbose=>1' in txt:
        print('     verbose => 1', file=sys.stderr)
    Path(target).write_text(
        '# Generated by BioNetGen C++\\nbegin model\\nbegin parameters\\n  k {rate_val}\\n  k_pop 100\\nend parameters\\nbegin molecule types\\n  A\\n  A_pop population\\n  B\\nend molecule types\\nbegin seed species\\n  A_pop() 10\\nend seed species\\nbegin observables\\n  Molecules A_obs A(),A_pop()\\n  Molecules B_obs B()\\nend observables\\nbegin reaction rules\\n  R1_v1: A_pop() -> B() k\\n  _MapRule0: A() -> A_pop() k_pop\\nend reaction rules\\nend model\\n## model actions ##\\nwriteXML()\\n',
        encoding='utf-8',
    )
    if 'execute=>1' in txt and 'writeXML()' in txt:
        Path('probe_hpp.xml').write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\\n<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1"><model id=""><ListOfParameters><Parameter id="k" type="Constant" value="{rate_val}"/><Parameter id="k_pop" type="Constant" value="100"/></ListOfParameters><ListOfMoleculeTypes><MoleculeType id="A"/><MoleculeType id="A_pop" population="1"/><MoleculeType id="B"/></ListOfMoleculeTypes><ListOfSpecies><Species id="S1" concentration="10" name="A_pop()"><ListOfMolecules><Molecule id="S1_M1" name="A_pop"/></ListOfMolecules></Species></ListOfSpecies><ListOfReactionRules><ReactionRule id="RR1" name="R1_v1"><ListOfReactantPatterns><ReactantPattern id="RR1_RP1"><ListOfMolecules><Molecule id="RR1_RP1_M1" name="A_pop"/></ListOfMolecules></ReactantPattern></ListOfReactantPatterns><ListOfProductPatterns><ProductPattern id="RR1_PP1"><ListOfMolecules><Molecule id="RR1_PP1_M1" name="B"/></ListOfMolecules></ProductPattern></ListOfProductPatterns><RateLaw id="RR1_RateLaw" type="Ele" totalrate="0"><ListOfRateConstants><RateConstant value="k"/></ListOfRateConstants></RateLaw><ListOfOperations><Add id="RR1_PP1_M1"/><Delete id="RR1_RP1" DeleteMolecules="0"/></ListOfOperations></ReactionRule></ListOfReactionRules><ListOfObservables><Observable id="O1" name="A_obs" type="Molecules"><ListOfPatterns><Pattern id="O1_P1"><ListOfMolecules><Molecule id="O1_P1_M1" name="A"/></ListOfMolecules></Pattern></ListOfPatterns></Observable></ListOfObservables></model></sbml>\\n',
            encoding='utf-8',
        )
if 'writeXML(' in txt and 'generate_hybrid_model(' not in txt:
    Path('probe.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\\n<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1"><model id=""><ListOfParameters><Parameter id="k" type="Constant" value="{rate_val}"/><Parameter id="k_pop" type="Constant" value="100"/></ListOfParameters><ListOfMoleculeTypes><MoleculeType id="A"/><MoleculeType id="A_pop" population="1"/><MoleculeType id="B"/></ListOfMoleculeTypes><ListOfSpecies><Species id="S1" concentration="10" name="A_pop()"><ListOfMolecules><Molecule id="S1_M1" name="A_pop"/></ListOfMolecules></Species></ListOfSpecies><ListOfReactionRules><ReactionRule id="RR1" name="R1_v1"><ListOfReactantPatterns><ReactantPattern id="RR1_RP1"><ListOfMolecules><Molecule id="RR1_RP1_M1" name="A_pop"/></ListOfMolecules></ReactantPattern></ListOfReactantPatterns><ListOfProductPatterns><ProductPattern id="RR1_PP1"><ListOfMolecules><Molecule id="RR1_PP1_M1" name="B"/></ListOfMolecules></ProductPattern></ListOfProductPatterns><RateLaw id="RR1_RateLaw" type="Ele" totalrate="0"><ListOfRateConstants><RateConstant value="k"/></ListOfRateConstants></RateLaw><ListOfOperations><Add id="RR1_PP1_M1"/><Delete id="RR1_RP1" DeleteMolecules="0"/></ListOfOperations></ReactionRule></ListOfReactionRules><ListOfObservables><Observable id="O1" name="A_obs" type="Molecules"><ListOfPatterns><Pattern id="O1_P1"><ListOfMolecules><Molecule id="O1_P1_M1" name="A"/></ListOfMolecules></Pattern></ListOfPatterns></Observable></ListOfObservables></model></sbml>\\n',
        encoding='utf-8',
    )
if 'generate_network(' in txt:
    Path('probe.net').write_text('# Created by bng_cpp\\nbegin species\\n  1 A() 1\\nend species\\nbegin reactions\\n  1 1 0 1\\nend reactions\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return exe


def test_all_50_probe_rows_exist_and_are_implemented_in_matrix():
    matrix = json.loads((ROOT / "provenance/capability-matrix.yml").read_text())
    by_id = {row["id"]: row for row in matrix["rows"]}
    assert len(probes.PROBE_SPECS) == 50
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
    selected = [
        "builtin.exp",
        "operator.357",
        "operator.364",
        "operator.367",
        "operator.368",
        "bngl.null-reactants-and-products",
        "action.generate_hybrid_model",
        "action.generate_hybrid_model.actions",
        "action.generate_hybrid_model.execute",
        "action.generate_hybrid_model.overwrite",
        "action.generate_hybrid_model.prefix",
        "action.generate_hybrid_model.suffix",
        "action.generate_hybrid_model.verbose",
    ]
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
    assert report["grounded_execution_rows"] == len(selected)

    # Corrupt consumer numeric and hybrid outputs must fail fail-closed.
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

    cpp_bad_hyb = _write_fake_cpp(tmp_path / "bin-bad-hyb", corrupt_hybrid=True)
    with pytest.raises(ValueError, match="hybrid BNGL parity failed"):
        probes.build_bng2_probe_receipts(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            bng_cpp=cpp_bad_hyb,
            receipts_dir=tmp_path / "r-bad-hyb",
            artifacts_dir=tmp_path / "a-bad-hyb",
            rows=["action.generate_hybrid_model"],
        )
    with pytest.raises(ValueError, match="BNG XML parity failed"):
        probes.build_bng2_probe_receipts(
            root=repo,
            revision=rev,
            bng2_root=bng2_root,
            bng_cpp=cpp_bad_hyb,
            receipts_dir=tmp_path / "r-bad-xml",
            artifacts_dir=tmp_path / "a-bad-xml",
            rows=["action.generate_hybrid_model.actions"],
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
