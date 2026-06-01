"""Network generation parity: engine-under-test .net vs Perl/golden .net.

This is the gate WO-1 must turn green. The two known over-count models are
xfail-marked with a reason and a tracking note; WO-1 removes them from this map
once canonical labeling is unified.
"""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, oracle_perl, runner

# Models where the C++ engine currently emits MORE reactions than Perl, because
# symmetry-equivalent reactions fail to merge in RxnList::add (their product
# species strings differ due to incomplete canonical labeling in HNauty).
# Removed by WO-1. The +N is the observed reaction surplus vs the Perl oracle.
KNOWN_OVERCOUNT = {
    "blbr": "WO-1: +26 reactions; symmetric complexes not canonicalized to a single label",
    "Motivating_example_cBNGL": "WO-1: +2 reactions; compartmental symmetry merge gap",
}


def _net_parity(model_name: str, bng_cpp, work_dir):
    ref_path, ref_src = oracle_perl.net(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference .net for {model_name}: {ref_src}")

    test_net, _, err = runner.run_cli(bng_cpp, model_name, work_dir / "cpp")
    assert test_net is not None, f"engine produced no .net: {err}"

    ref = compare.parse_net(ref_path)
    test = compare.parse_net(test_net)
    assert ref is not None, f"could not parse reference .net ({ref_src})"
    assert test is not None, "could not parse engine .net"

    diff = compare.compare_net(ref, test)
    assert diff.ok, f"net mismatch [{model_name}] (ref={ref_src}):\n{diff.summary()}"


@pytest.mark.smoke
@pytest.mark.parametrize("model_name", corpus.tier_s())
def test_net_parity_smoke(model_name, bng_cpp, work_dir, request):
    if model_name in KNOWN_OVERCOUNT:
        request.node.add_marker(pytest.mark.xfail(reason=KNOWN_OVERCOUNT[model_name], strict=True))
    _net_parity(model_name, bng_cpp, work_dir)


@pytest.mark.parity
@pytest.mark.parametrize("model_name", corpus.tier_p())
def test_net_parity_full(model_name, bng_cpp, work_dir, request):
    if model_name in KNOWN_OVERCOUNT:
        request.node.add_marker(pytest.mark.xfail(reason=KNOWN_OVERCOUNT[model_name], strict=True))
    _net_parity(model_name, bng_cpp, work_dir)
