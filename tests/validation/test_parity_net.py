"""Network generation parity: engine-under-test .net vs Perl/golden .net.

This is the gate WO-1a must turn green. Known failures are admitted only through
the strict, signature-checked exception ledger.
"""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, exception_ledger, oracle_perl, runner

EXCEPTIONS = exception_ledger.load_ledger()


def _net_parity(model_name: str, bng_cpp, work_dir):
    ref_path, ref_src = oracle_perl.net(model_name, work_dir / "perl")
    if ref_path is None:
        pytest.skip(f"no reference .net for {model_name}: {ref_src}")

    test_net, _, err = runner.run_cli(bng_cpp, model_name, work_dir / "cpp")
    assert test_net is not None, f"engine produced no .net: {err}"

    # parse_net defaults to rate_mode="value": auto-generated rate-parameter
    # NAMES (rateLaw4 vs _rateLaw4 vs __R1_local1) are resolved to their
    # value/expression before comparison, so they don't cause spurious
    # mismatches. A real difference in rate value or expression is still caught,
    # and the over-count (a reaction COUNT difference) is independent of rates.
    # For byte-identical name checking, pass rate_mode="string".
    ref = compare.parse_net(ref_path)
    test = compare.parse_net(test_net)
    assert ref is not None, f"could not parse reference .net ({ref_src})"
    assert test is not None, "could not parse engine .net"

    diff = compare.compare_net(ref, test)
    assert diff.ok, f"net mismatch [{model_name}] (ref={ref_src}):\n{diff.summary()}"


@pytest.mark.smoke
@pytest.mark.parametrize("model_name", corpus.tier_s())
def test_net_parity_smoke(model_name, bng_cpp, work_dir, request):
    entry = EXCEPTIONS.find(request.node.nodeid, model_name, "network_generation")
    with exception_ledger.strict_expected_failure(entry):
        _net_parity(model_name, bng_cpp, work_dir)


@pytest.mark.parity
@pytest.mark.parametrize("model_name", corpus.tier_p())
def test_net_parity_full(model_name, bng_cpp, work_dir, request):
    entry = EXCEPTIONS.find(request.node.nodeid, model_name, "network_generation")
    with exception_ledger.strict_expected_failure(entry):
        _net_parity(model_name, bng_cpp, work_dir)
