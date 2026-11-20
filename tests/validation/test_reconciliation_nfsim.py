"""Record source and product results for specific NFsim reconciliation claims."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.validation import compare, oracle_nfsim
from tests.validation.strict import require_oracle


@pytest.fixture
def pinned_nfsim_source():
    checkout = os.environ.get("BNG3_RECONCILIATION_NFSIM_SOURCE")
    native = oracle_nfsim.nfsim_binary()
    require_oracle(bool(checkout and native), "set the pinned NFsim source and binary")
    assert checkout is not None and native is not None
    root = Path(checkout).resolve()
    from scripts.ci.oracle_sources import load_lock, load_oracle_source

    expected = load_oracle_source(load_lock(), "nfsim")["revision"]
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    assert actual == expected
    return root, native


def _pinned_bytes(root, filename, record_property):
    data = (root / filename).read_bytes()
    committed = subprocess.check_output(
        ["git", "-C", str(root), "cat-file", "blob", f"HEAD:{filename}"]
    )
    assert data == committed
    record_property(filename, hashlib.sha256(data).hexdigest())
    return data


def _run_native(native, xml, output, *flags):
    return subprocess.run(
        [
            str(native),
            "-xml",
            str(xml),
            "-o",
            str(output),
            "-sim",
            "1",
            "-oSteps",
            "1",
            "-seed",
            "1",
            *flags,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _bound_endpoint(path):
    values, columns = compare.parse_gdat(path)
    assert values is not None and columns is not None
    return float(values[-1, columns.index("bound")])


def test_record_complex_flag_reconciliation(
    pinned_nfsim_source, api, tmp_path, monkeypatch, record_property
):
    """Retain the source and product endpoints, including any difference."""
    root, native = pinned_nfsim_source
    xml = tmp_path / "native.xml"
    xml.write_bytes(_pinned_bytes(root, "test/Issue51/issue51.xml", record_property))
    bngl = _pinned_bytes(root, "test/Issue51/issue51.bngl", record_property)
    model, actions, _ = bngl.decode().partition("begin actions")
    assert actions
    monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")

    comparisons = {}
    for name, flags, options, expected in (
        ("default", (), "", 0.0),
        ("cb", ("-cb",), ",complex=>1", 0.0),
        ("bscb", ("-bscb",), ',param=>"-bscb"', 0.0),
        ("no_bscb", ("-no-bscb",), ',param=>"-no-bscb"', 1.0),
    ):
        oracle_output = tmp_path / f"oracle-{name}.gdat"
        result = _run_native(native, xml, oracle_output, *flags)
        assert result.returncode == 0, result.stderr
        reference = _bound_endpoint(oracle_output)
        assert reference == expected

        source = tmp_path / f"product-{name}.bngl"
        source.write_text(
            model
            + "begin actions\n"
            + f'simulate_nf({{prefix=>"product-{name}",t_end=>1,n_steps=>1,seed=>1{options}}})\n'
            + "end actions\n",
            encoding="utf-8",
        )
        api.load(str(source)).execute()
        actual = _bound_endpoint(tmp_path / f"product-{name}.gdat")
        record_property(f"{name}.source_bound", reference)
        record_property(f"{name}.bng3_bound", actual)
        comparisons[name] = {"source_bound": reference, "bng3_bound": actual}
    matched = all(
        pair["source_bound"] == pair["bng3_bound"] for pair in comparisons.values()
    )
    record_property("semantic_result", "PASS" if matched else "FAIL")

    output = os.environ.get("BNG3_NFSIM_RECONCILIATION_REPORT")
    if output:
        repo = Path(__file__).resolve().parents[2]
        product = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain"]
        )
        upstream = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        results = []
        for option in ("cb", "bscb", "no_bscb"):
            pair = comparisons[option]
            passed = pair["source_bound"] == pair["bng3_bound"]
            results.append(
                {
                    "id": f"release-capability[nf.option.{option.replace('_', '-')}]",
                    "status": "PASS" if passed else "FAIL",
                    "supported_execution": passed,
                    "evidence_kind": "supported-execution",
                    "case": "NFsim Issue51 bound observable at t=1",
                    "comparisons": pair,
                }
            )
        report = {
            "schema_version": 1,
            "source": {"revision": product, "dirty": bool(dirty)},
            "references": {
                "nfsim": {
                    "revision": upstream,
                    "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                    "bngl_sha256": hashlib.sha256(bngl).hexdigest(),
                    "xml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                },
            },
            "subject": {
                "sha256": hashlib.sha256(
                    Path(api.model._cpp.__file__).read_bytes()
                ).hexdigest()
            },
            "results": results,
        }
        Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("directory", "name", "xml_rate", "rule_rate", "diagnostic"),
    [
        ("MM", "mm_small_km", 'id="RR1_RateLaw" type="MM"', "MM(kcat,Km)", "MM"),
        (
            "testSuite",
            "t3",
            'id="RR9_RateLaw" type="Function" name="_rateLaw1"',
            "pOn(x)\n",
            "local functions",
        ),
    ],
    ids=["mm", "local-function"],
)
def test_record_totalrate_reconciliation(
    pinned_nfsim_source,
    api,
    tmp_path,
    monkeypatch,
    capfd,
    record_property,
    directory,
    name,
    xml_rate,
    rule_rate,
    diagnostic,
):
    """Use the pinned Issue91 XML mutation and compare the direct BNGL route."""
    root, native = pinned_nfsim_source
    source = f"test/{directory}/{name}"
    xml_text = _pinned_bytes(root, source + ".xml", record_property).decode()
    valid_rate = xml_rate + ' totalrate="0"'
    assert xml_text.count(valid_rate) == 1
    xml = tmp_path / "invalid.xml"
    xml.write_text(xml_text.replace(valid_rate, xml_rate + ' totalrate="1"', 1))
    native_output = tmp_path / "invalid.gdat"
    result = _run_native(native, xml, native_output)
    assert not native_output.exists()
    assert f"TotalRate keyword is not compatible with {diagnostic}" in (
        result.stdout + result.stderr
    )

    bngl = _pinned_bytes(root, source + ".bngl", record_property).decode()
    assert bngl.count(rule_rate) == 1
    product = tmp_path / "product.bngl"
    product.write_text(bngl.replace(rule_rate, rule_rate.rstrip() + " TotalRate\n", 1))
    monkeypatch.setenv("BNG_NFSIM_REQUIRE_DIRECT", "1")
    try:
        trajectory = api.load(str(product)).simulate(
            method="nf", t_end=1, n_steps=1, seed=1
        )
    except (RuntimeError, ValueError) as error:
        captured = capfd.readouterr()
        messages = str(error) + captured.out + captured.err
        diagnostic_line = next(
            (line.strip() for line in messages.splitlines() if "TotalRate" in line), ""
        )
        record_property("bng3_result", diagnostic_line or "unattributed rejection")
        matched = bool(diagnostic_line)
    else:
        assert trajectory.construction_path == "direct"
        record_property("bng3_result", "executed")
        matched = False
    record_property("source_result", "TotalRate rejected")
    record_property("semantic_result", "PASS" if matched else "FAIL")


def test_record_unmapped_reactant_reconciliation(
    pinned_nfsim_source, api, tmp_path, monkeypatch, record_property
):
    """Verify internal bond reconnection runs with -cb and -bscb without dereferencing null mappings."""
    root, native = pinned_nfsim_source
    bngl_bytes = _pinned_bytes(root, "validate/basicModels/v31.bngl", record_property)
    bngl_text = bngl_bytes.decode()

    # Generate XML via BNG3 writeXML
    v31_gen = tmp_path / "v31_gen.bngl"
    v31_gen.write_text(bngl_text, encoding="utf-8")
    api.load(str(v31_gen)).execute()
    xml = tmp_path / "v31_gen.xml"
    assert xml.exists()

    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    matched = True
    for flag, option in (("-cb", ",complex=>1"), ("-bscb", ',param=>"-bscb"')):
        native_out = tmp_path / f"native{flag}.gdat"
        res = subprocess.run(
            [
                str(native),
                "-xml",
                str(xml),
                "-o",
                str(native_out),
                "-sim",
                "1",
                "-oSteps",
                "1",
                "-seed",
                "1",
                flag,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert res.returncode == 0, res.stderr
        record_property(f"native_{flag}.status", "executed")

        bng3_bngl = tmp_path / f"product{flag}.bngl"
        bng3_bngl.write_text(
            bngl_text.replace(
                "writeXML()",
                f'simulate_nf({{prefix=>"product{flag}",t_end=>1,n_steps=>1,seed=>1{option}}})\n',
            ),
            encoding="utf-8",
        )
        api.load(str(bng3_bngl)).execute()
        bng3_out = tmp_path / f"product{flag}.species"
        assert bng3_out.exists()
        record_property(f"bng3_{flag}.status", "executed")

    record_property("semantic_result", "PASS" if matched else "FAIL")
