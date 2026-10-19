"""Mutation controls for source-to-compiled rate/unit traces."""

import pytest

from tests.validation import integrated_traces
from tests.validation import integrated
from tests.validation.integrated_cases import generated_cases, sbml_text


def _dimer_case(volume=3):
    return next(
        case
        for case in generated_cases(full=True)
        if case["family"] == "dimerization" and case["volume"] == volume
    )


def test_rate_trace_detects_missing_and_duplicated_reciprocal_volume():
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    expected = source["reactions"][0]["unit_state_rate"]
    assert expected == 0.4 / 3

    for observed_rate in (0.4, 0.4 / 9):
        result = integrated_traces.compare_rate_trace(
            source,
            {"reaction_rate_coefficients": [observed_rate], "ode_rhs": []},
        )
        assert result["status"] == "FAIL"
        assert result["first_difference"]["source"] == expected
        assert result["first_difference"]["observed"] == observed_rate


def test_rate_trace_passes_source_volume_scaling_and_records_units_and_expression():
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    reaction = source["reactions"][0]
    result = integrated_traces.compare_rate_trace(
        source,
        {"reaction_rate_coefficients": [reaction["unit_state_rate"]], "ode_rhs": []},
    )
    assert result["status"] == "PASS"
    assert reaction["source_expression"]
    assert reaction["parameter_units"]["k"] == "litre_per_item_second"
    assert result["first_difference"] is None


def test_rate_trace_missing_observation_is_not_tested():
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    result = integrated_traces.compare_rate_trace(source, None)
    assert result["status"] == "NOT_TESTED"
    assert result["first_difference"] is None


def test_rate_trace_missing_compiled_rate_is_not_fabricated_as_a_match():
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    result = integrated_traces.compare_rate_trace(
        source, {"reaction_rate_coefficients": [], "ode_rhs": []}
    )
    assert result["status"] == "NOT_TESTED"
    assert "coverage" in result["detail"]


def test_unit_state_evaluator_preserves_source_concentration_and_function_scopes():
    cases = [case for case in generated_cases(full=True) if case.get("transform")]
    for case in cases:
        trace = integrated_traces.source_rate_trace(sbml_text(case))
        assert len(trace["reactions"]) == 1
        assert trace["reactions"][0]["unit_state_rate"] == 0.4


def test_net_parser_export_probe_detects_missing_or_repeated_volume(tmp_path):
    path = tmp_path / "model.net"
    path.write_text(
        "begin parameters\n    k 0.4\nend parameters\n"
        "begin species\n    1 A() 2\n    2 D() 0\nend species\n"
        "begin reactions\n    1 1,1 2 0.166666666667*0.8\nend reactions\n"
    )
    exported = integrated_traces.exported_net_rates(path)
    assert abs(exported["effective_rates"][0] - 0.4 / 3) < 1e-12

    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    assert (
        integrated_traces.compare_rate_values(
            source, exported["effective_rates"], "NET", rtol=5e-11
        )["status"]
        == "PASS"
    )
    for wrong in ([0.4], [0.4 / 9]):
        assert (
            integrated_traces.compare_rate_values(source, wrong, "NET")["status"]
            == "FAIL"
        )


def test_bngxml_probe_records_constants_and_keeps_unresolved_rates_not_tested(
    tmp_path,
):
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    path = tmp_path / "model.xml"
    path.write_text(
        '<Model><ListOfReactionRules><ReactionRule id="R" name="dimer">'
        "<ListOfReactantPatterns><ReactantPattern/><ReactantPattern/></ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="0.8"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></Model>"
    )
    assert integrated_traces.exported_bng_xml(path)["effective_rates"] is None
    observed = integrated_traces.exported_bng_xml(path, source)
    assert observed["effective_rates"] == [0.8]
    assert observed["rules"][0]["rate_constants"] == ["0.8"]

    path.write_text(path.read_text().replace('value="0.8"', 'value="k"'))
    observed = integrated_traces.exported_bng_xml(path, source)
    assert observed["effective_rates"] is None
    assert "unsupported" in observed["detail"]
    assert integrated_traces.boundary_metadata("net-bngxml-rate-coefficient") == {
        "diagnostic_only": True,
        "supported_execution": False,
    }


def test_bngxml_probe_resolves_a_parameter_backed_rate_constant(tmp_path):
    """A constant rate law may name a parameter instead of a literal.

    The exported parameter list states the value the parameter was given, so
    the count-rate coefficient is still a constant.
    """
    path = tmp_path / "model.xml"
    path.write_text(
        "<Model><ListOfParameters>"
        '<Parameter id="k" type="Constant" value="0.8"/>'
        "</ListOfParameters>"
        "<ListOfCompartments>"
        '<Compartment id="cell" spatialDimensions="3" size="3"/>'
        "</ListOfCompartments>"
        '<ListOfReactionRules><ReactionRule id="R" name="dimer" symmetry_factor="0.5">'
        "<ListOfReactantPatterns>"
        '<ReactantPattern compartment="cell"/><ReactantPattern compartment="cell"/>'
        "</ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="k"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></Model>"
    )
    observed = integrated_traces.exported_bng_xml(path)
    assert observed["rules"][0]["rate_constant_value"] == pytest.approx(0.8)
    assert observed["rules"][0]["observed_elementary_coefficient"] == pytest.approx(
        0.8 * 0.5 / 3
    )
    source = integrated_traces.source_rate_trace(sbml_text(_dimer_case()))
    observed = integrated_traces.exported_bng_xml(path, source)
    assert observed["effective_rates"] == [pytest.approx(0.8 * 0.5 / 3)]


def _dimer_xml(compartment='<Compartment id="cell" spatialDimensions="3" size="3"/>'):
    return (
        '<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1">'
        "<model id=''>"
        f"<ListOfCompartments>{compartment}</ListOfCompartments>"
        '<ListOfReactionRules><ReactionRule id="R" name="dimer" symmetry_factor="0.5">'
        "<ListOfReactantPatterns>"
        '<ReactantPattern compartment="cell"/><ReactantPattern compartment="cell"/>'
        "</ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="0.8"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></model></sbml>"
    )


def test_native_count_rate_xml_states_the_count_rate_coefficient(tmp_path):
    """The oracle is handed BNG2's count-rate coefficient, not its own rate.

    The pinned native NFsim applies a compartment size only to zero-order
    synthesis, so a reactant-bearing rule would be sampled at
    ``rate constant x symmetry factor``.  The rewrite folds BNG2's
    compartment unit conversion into the rate constant and drops the
    now-redundant symmetry factor.
    """
    source = tmp_path / "model.xml"
    source.write_text(_dimer_xml())
    target = tmp_path / "native-count-rate.xml"
    result = integrated_traces.native_count_rate_xml(source, target)
    assert result["status"] == "NORMALISED"
    rule = result["rules"][0]
    assert rule["compartment_unit_conversion"] == pytest.approx(1 / 3)
    assert rule["count_rate_coefficient"] == pytest.approx(0.8 * 0.5 / 3)
    text = target.read_text()
    assert 'value="0.13333333333333333"' in text
    assert "symmetry_factor" not in text
    # The document keeps its own default namespace.
    assert "ns0:" not in text
    assert 'xmlns="http://www.sbml.org/sbml/level3"' in text


def test_native_count_rate_xml_refuses_a_model_it_cannot_state(tmp_path):
    """A model without a static conversion states no count-rate coefficient."""
    source = tmp_path / "model.xml"
    source.write_text(
        _dimer_xml('<Compartment id="cell" spatialDimensions="3" sizeParameter="V"/>')
    )
    result = integrated_traces.native_count_rate_xml(
        source, tmp_path / "native-count-rate.xml"
    )
    assert result["status"] == "UNSUPPORTED"
    assert "compartment unit conversion" in result["detail"]

    # The oracle applies the product compartment's size to a zero-order rule
    # itself when the model states the compartment on the molecule, so the
    # coefficient would be counted twice.
    source.write_text(
        _dimer_xml()
        .replace(
            '<Molecule id="M" name="A"/>',
            '<Molecule id="M" name="A" compartment="cell"/>',
        )
        .replace(
            "<ListOfReactantPatterns>"
            '<ReactantPattern compartment="cell"/><ReactantPattern compartment="cell"/>'
            "</ListOfReactantPatterns>",
            "<ListOfReactantPatterns>"
            '<ReactantPattern compartment="cell"/>'
            '<ReactantPattern compartment="cell">'
            '<ListOfMolecules><Molecule id="M" name="A" compartment="cell"/>'
            "</ListOfMolecules></ReactantPattern>"
            "</ListOfReactantPatterns>",
        )
    )
    result = integrated_traces.native_count_rate_xml(
        source, tmp_path / "native-count-rate.xml"
    )
    assert result["status"] == "UNSUPPORTED"
    assert "molecule compartment" in result["detail"]


def test_bng_xml_coefficient_uses_the_same_compartment_convention_as_the_net(
    tmp_path,
):
    """The XML and the NET serializations must state the same rate.

    The NET export folds BNG2's compartment unit conversion into the
    coefficient (`0.166666666667*0.8` for a 2A->D rule in a compartment of
    size 3), while the BNG-XML export keeps the rule rate constant, the
    symmetry factor and the compartment size apart.  Comparing the raw XML
    coefficient with the NET coefficient compares two different conventions,
    so the XML coefficient is converted the same way before it is compared.
    """
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    path = tmp_path / "model.xml"
    path.write_text(
        "<Model><ListOfCompartments>"
        '<Compartment id="cell" spatialDimensions="3" size="3"/>'
        "</ListOfCompartments>"
        '<ListOfReactionRules><ReactionRule id="R" name="dimer" symmetry_factor="0.5">'
        "<ListOfReactantPatterns>"
        '<ReactantPattern compartment="cell"/><ReactantPattern compartment="cell"/>'
        "</ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="0.8"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></Model>"
    )
    observed = integrated_traces.exported_bng_xml(path, source)
    assert observed["rules"][0]["compartment_unit_conversion"] == pytest.approx(1 / 3)
    assert observed["effective_rates"] == [pytest.approx(0.4 / 3)]
    # The NET export states the same rate in its own convention.
    net = tmp_path / "model.net"
    net.write_text(
        "begin parameters\n    k 0.4\nend parameters\n"
        "begin species\n    1 A() 2\n    2 D() 0\nend species\n"
        "begin reactions\n    1 1,1 2 0.166666666667*0.8\nend reactions\n"
    )
    exported = integrated_traces.exported_net_rates(net)
    assert (
        integrated_traces.compare_rate_values(
            exported["effective_rates"],
            observed["effective_rates"],
            "BNG-XML",
            rtol=5e-11,
        )["status"]
        == "PASS"
    )


def test_bng_xml_coefficient_is_not_comparable_without_a_static_compartment_size(
    tmp_path,
):
    """A parameter-backed compartment size cannot be folded in here.

    The BNG-XML export keeps the rule rate constant and lets the consumer
    apply the conversion, so a compartment whose size is a parameter has no
    static conversion and the two serializations cannot be compared.
    """
    case = _dimer_case()
    source = integrated_traces.source_rate_trace(sbml_text(case))
    path = tmp_path / "model.xml"
    path.write_text(
        "<Model><ListOfCompartments>"
        '<Compartment id="cell" spatialDimensions="3" sizeParameter="V"/>'
        "</ListOfCompartments>"
        '<ListOfReactionRules><ReactionRule id="R" name="dimer" symmetry_factor="0.5">'
        "<ListOfReactantPatterns>"
        '<ReactantPattern compartment="cell"/><ReactantPattern compartment="cell"/>'
        "</ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="0.8"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></Model>"
    )
    observed = integrated_traces.exported_bng_xml(path, source)
    assert observed["rules"][0]["compartment_unit_conversion"] is None
    assert observed["effective_rates"] is None


def test_native_count_rate_xml_states_the_model_the_embedded_engine_executes(
    tmp_path,
):
    """The oracle is handed BNG2's model in BNG2's count-rate convention.

    BNG2's XML states a reactant-bearing rule at the rule rate constant, the
    symmetry factor and the compartment size apart, and the pinned oracle
    applies no compartment conversion to such a rule. The rewrite folds the
    conversion into the rate constant, so the oracle samples the same model the
    embedded engine executes.
    """
    path = tmp_path / "model.xml"
    path.write_text(
        "<Model><ListOfCompartments>"
        '<compartment id="cell" spatialDimensions="3" size="3"/>'
        "</ListOfCompartments>"
        '<ListOfReactionRules><ReactionRule id="RR1" name="dimer" symmetry_factor="0.5">'
        "<ListOfReactantPatterns>"
        '<ReactantPattern compartment="cell"/><ReactantPattern compartment="cell"/>'
        "</ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="0.8"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></Model>"
    )
    target = tmp_path / "count-rate-model.xml"
    observed = integrated_traces.native_count_rate_xml(path, target)
    assert observed["status"] == "NORMALISED"
    rule = observed["rules"][0]
    assert rule["compartment_unit_conversion"] == pytest.approx(1 / 3)
    assert rule["count_rate_coefficient"] == pytest.approx(0.4 / 3)
    text = target.read_text()
    # The count-rate coefficient replaces the rule rate constant, and the
    # symmetry factor it already carries becomes redundant.
    assert 'value="0.13333333333333333"' in text
    assert "symmetry_factor" not in text
    # A molecule compartment inside a rule pattern would make the oracle apply
    # that compartment's size itself.
    path.write_text(
        "<Model><ListOfCompartments>"
        '<compartment id="cell" spatialDimensions="3" size="3"/>'
        "</ListOfCompartments>"
        '<ListOfReactionRules><ReactionRule id="RR1" name="dimer" symmetry_factor="0.5">'
        "<ListOfReactantPatterns>"
        '<ReactantPattern compartment="cell">'
        '<Molecule name="M_A" compartment="cell"/>'
        "</ReactantPattern>"
        '<ReactantPattern compartment="cell"/>'
        "</ListOfReactantPatterns>"
        '<RateLaw type="Ele"><ListOfRateConstants>'
        '<RateConstant value="0.8"/></ListOfRateConstants></RateLaw>'
        "</ReactionRule></ListOfReactionRules></Model>"
    )
    refused = integrated_traces.native_count_rate_xml(path, tmp_path / "refused.xml")
    assert refused["status"] == "UNSUPPORTED"
    assert "molecule compartment" in refused["detail"]


def test_bngxml_report_row_marks_coefficient_evidence_diagnostic_only():
    row = integrated._rate_trace_row(
        "case",
        "net-bngxml-rate-coefficient",
        {"status": "FAIL", "detail": "coefficient differs"},
        evidence={"bng_xml_export": {"status": "OBSERVED"}},
        trace_id="case:rate-units:abc",
        summary={
            "boundary_statuses": [{"name": "net-to-bngxml", "status": "FAIL"}],
            "first_divergence": {"name": "net-to-bngxml"},
            "blocked_at": None,
            "observed_failures": ["net-to-bngxml"],
        },
        receipts=[],
    )
    assert row["diagnostic_only"] is True
    assert row["supported_execution"] is False
    assert row["trace_id"] == "case:rate-units:abc"


def test_first_boundary_summary_preserves_later_failures_after_missing_link():
    trace = integrated_traces.first_differing_boundary(
        [
            dict(name="source-to-compiled", status="NOT_TESTED"),
            dict(
                name="compiled-to-net",
                status="FAIL",
                first_difference={"field": "rate"},
            ),
            dict(
                name="net-to-bngxml",
                status="FAIL",
                first_difference={"field": "volume"},
            ),
        ]
    )
    assert trace["first_divergence"] is None
    assert trace["blocked_at"] == "source-to-compiled"
    assert trace["observed_failures"] == ["compiled-to-net", "net-to-bngxml"]
    assert [row["status"] for row in trace["boundary_statuses"]] == [
        "NOT_TESTED",
        "FAIL",
        "FAIL",
    ]


def test_first_boundary_summary_selects_earliest_failure_after_passed_links():
    trace = integrated_traces.first_differing_boundary(
        [
            dict(name="source-to-compiled", status="PASS"),
            dict(
                name="compiled-to-net",
                status="FAIL",
                first_difference={"field": "rate"},
            ),
            dict(
                name="net-to-bngxml",
                status="FAIL",
                first_difference={"field": "volume"},
            ),
        ]
    )
    assert trace["first_divergence"] == dict(
        name="compiled-to-net", first_difference={"field": "rate"}
    )
    assert trace["observed_failures"] == ["compiled-to-net", "net-to-bngxml"]


def test_trace_failure_keeps_boundary_evidence_in_cluster_and_repair_packet(tmp_path):
    from tests.validation import reporting

    boundary = integrated_traces.first_differing_boundary(
        [
            dict(name="source-to-compiled", status="PASS"),
            dict(
                name="compiled-to-net",
                status="FAIL",
                first_difference={"sorted_index": 0},
            ),
            dict(
                name="net-to-bngxml",
                status="FAIL",
                first_difference={"sorted_index": 0},
            ),
        ]
    )
    row = dict(
        id="case:rate-trace:compiled-net-rate-multiset",
        stage="rate-trace",
        check="compiled-net-rate-multiset",
        status="FAIL",
        detail="rate values differ from BNG3 NET export vs compiled API",
        first_difference={"sorted_index": 0},
        trace_id="case:rate-units:abc",
        evidence=[boundary],
        command=["python", "integrated.py", "--case", "case"],
        receipts=[],
        related_issues=[151],
    )
    report = dict(
        results=[row],
        source={"revision": "abc"},
        subject={"binary": "build/cpp/bng_cpp"},
        configuration={"environment": {}},
        references={},
    )
    cluster = reporting.cluster_failures([row])[0]
    packet = reporting.investigation_tasks(report, tmp_path)[0]
    assert cluster["cases"] == [row["id"]]
    assert packet["observation"] == {"sorted_index": 0}
    assert packet["evidence"] == [boundary]
    assert packet["evidence"][0]["observed_failures"] == [
        "compiled-to-net",
        "net-to-bngxml",
    ]


def test_worker_cli_atomizes_then_emits_native_net_xml_and_rhs_trace(tmp_path):
    import subprocess
    import sys

    import pytest

    try:
        import bionetgen  # noqa: F401
        from bionetgen import _bionetgen_cpp  # noqa: F401
    except ImportError:
        pytest.skip("installed BNG3 package/native binding is unavailable")
    case = _dimer_case()
    source = tmp_path / "source.xml"
    source.write_text(sbml_text(case))
    worker = integrated_traces.__file__.replace(
        "integrated_traces.py", "integrated_worker.py"
    )
    for operation, input_path in (
        ("atomizer", source),
        ("rate-trace", tmp_path / "model.bngl"),
    ):
        completed = subprocess.run(
            [
                sys.executable,
                worker,
                operation,
                "--input",
                str(input_path),
                "--case-id",
                case["id"],
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
    observation = __import__("json").loads((tmp_path / "rate-trace.json").read_text())
    assert len(observation["reaction_rate_coefficients"]) == 1
    assert len(observation["ode_rhs"]) == len(observation["species"]) == 2
    assert (tmp_path / "model.net").is_file()
    assert (tmp_path / "model.xml").is_file()
    source_trace = integrated_traces.source_rate_trace(sbml_text(case))
    assert integrated_traces.compare_rate_trace(source_trace, observation)[
        "status"
    ] in {"PASS", "FAIL"}
    net_export = integrated_traces.exported_net_rates(tmp_path / "model.net")
    assert net_export["status"] == "OBSERVED"
    assert integrated_traces.compare_rate_values(
        source_trace, net_export["effective_rates"], "NET", rtol=5e-11
    )["status"] in {"PASS", "FAIL"}
    xml_export = integrated_traces.exported_bng_xml(
        tmp_path / "model.xml", source_trace
    )
    assert xml_export["status"] == "OBSERVED"
    assert integrated_traces.compare_rate_values(
        net_export["effective_rates"],
        xml_export["effective_rates"],
        "BNG-XML",
        rtol=5e-11,
    )["status"] in {"PASS", "FAIL"}
