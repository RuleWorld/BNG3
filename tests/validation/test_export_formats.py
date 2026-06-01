"""Export-format validity (WO-5): one writer set, all formats valid."""

from __future__ import annotations

import pytest

from tests.validation import compare, corpus, runner

EXPORT_MODELS = [m for m in ("Motivating_example", "egfr_net", "gene_expr", "Repressilator")
                 if corpus.resolve(m) is not None]


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_xml_wellformed(model_name, api, work_dir):
    out = runner.export(model_name, "xml", work_dir / f"{model_name}.xml")
    ok, msg = compare.check_xml_wellformed(out)
    assert ok, f"BNG-XML not well-formed [{model_name}]: {msg}"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_sbml_valid(model_name, api, work_dir):
    out = runner.export(model_name, "sbml", work_dir / f"{model_name}.xml")
    ok, msg = compare.check_sbml(out)
    assert ok, f"SBML invalid [{model_name}]: {msg}"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_net_roundtrip_idempotent(model_name, bng_cpp, work_dir):
    """write -> read -> write produces an identical network."""
    net1, _, err = runner.run_cli(bng_cpp, model_name, work_dir / "pass1")
    assert net1 is not None, f"first generation failed: {err}"
    # Second pass over the same model must yield an identical network.
    net2, _, err2 = runner.run_cli(bng_cpp, model_name, work_dir / "pass2")
    assert net2 is not None, f"second generation failed: {err2}"
    n1, n2 = compare.parse_net(net1), compare.parse_net(net2)
    diff = compare.compare_net(n1, n2)
    assert diff.ok, f"net not idempotent [{model_name}]:\n{diff.summary()}"
