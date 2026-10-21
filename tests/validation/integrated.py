"""Generated cross-component contracts using the existing evidence/triage helpers.

A bounded SBML amount model crosses Atomizer, native CLI, Python API, BNG2,
upstream PyBioNetGen and native NFsim. Each handoff is retained and attributed.
This is an integration detector, not qualification of the entire upstream union.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from . import campaign, contracts, inventory, reporting
from .simulation_contract import net_reload_context
from .integrated_cases import (
    TIMES,
    generated_cases,
    sbml_text,
    expected_trajectory,
)
from . import (
    integrated_consumers,
    integrated_source,
    scientific_contracts,
    integrated_extensions,
    integrated_traces,
)

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("integrated_worker.py")
# Required evidence is declared independently of execution, so deleting a
# comparator cannot leave a green report containing only successful processes.
PROCESS_STAGES = (
    "source-validation",
    "source-sbml-oracle",
    "atomizer",
    "rate-trace",
    "bng2",
    "cli",
    "api",
    "pybng",
    "compat",
    "nf",
    "native-nf",
    "net-reload",
    *integrated_consumers.OPERATIONS,
)
TRAJECTORY_GROUPS = (
    tuple(
        name + "-source-dynamics"
        for name in ("bng2", "cli", "api", "pybng", "compat", "net-reload")
    )
    + ("pybng-returned-data", "python-public-compatibility")
    + tuple(name + "-source-dynamics" for name in integrated_consumers.OPERATIONS)
)
NETWORK_CHECKS = (
    "artifact-validity",
    "species-count",
    "species-identity",
    "initial-amounts",
    "reaction-count",
    "reaction-stoichiometry",
    "reaction-multiplicity",
    "reaction-rates",
    "observable-names",
    "observable-weights",
)


def annotate_acceptance_evidence(rows):
    """Label registered semantic consumer checks, never process receipts."""
    consumers = set(
        integrated_consumers.expected_check_ids(
            [case["id"] for case in generated_cases(full=True)]
        )
    )
    for case in generated_cases(full=True):
        consumers.update(
            {
                f"{case['id']}:nf-marginals:native.source-cdf",
                f"{case['id']}:nf-marginals:native.marginal-means",
                f"{case['id']}:rate-trace:source-compiled-rate-multiset",
                f"{case['id']}:rate-trace:compiled-net-rate-multiset",
            }
        )
    consumers.update(integrated_extensions.check_ids("quantity-laws", full=True))
    consumers.update(integrated_extensions.check_ids("api-surface"))
    consumers.update(integrated_extensions.check_ids("stochastic-parity"))
    consumers.update(integrated_extensions.check_ids("graph-identity-contract"))
    consumers.update(integrated_extensions.check_ids("sbml-support-boundary"))
    consumers.update(integrated_extensions.check_ids("atomizer-symbol-resolution"))
    consumers.update(integrated_extensions.check_ids("bngsim-boundary"))
    for case in generated_cases(full=True):
        consumers.update(integrated_extensions.check_ids("protocol", case))
    for row in rows:
        if (
            row["id"] in consumers
            and row.get("supported_execution") is not False
            and row.get("status") in {"PASS", "FAIL"}
        ):
            row.setdefault("evidence_kind", "supported-execution")
            row.setdefault("supported_execution", True)


def expected_contract_ids(
    cases,
    *,
    include_boundaries=True,
    include_graph_identity=True,
    include_bngir_adversarial=True,
    include_quantity_laws=True,
    include_export_format_tier=True,
    include_netrule_execution=True,
    include_bngsim_boundary=True,
    include_jax_backend_measurement=True,
    include_rate_law_contract=True,
    include_nfnext_slices=True,
    include_api_surface=True,
    include_stochastic_parity=True,
    include_graph_identity_contract=True,
    include_sbml_support_boundary=True,
    include_atomizer_symbol_resolution=True,
    include_atomizer_reconstruction=True,
    include_energy_qualification=True,
    include_workload_profile=True,
    include_semantic_identity=True,
    include_graph_differential=True,
    include_capability_inventory=True,
    include_real_model_fixtures=True,
    include_corpus_selection=True,
    include_biomodels_hold=True,
    full=False,
):
    return [
        f"{c['id']}:{suffix}"
        for c in cases
        for suffix in (
            *PROCESS_STAGES,
            "rate-trace:source-compiled-rate-multiset",
            "rate-trace:compiled-net-rate-multiset",
            "rate-trace:net-bngxml-rate-coefficient",
            *(
                f"{group}:gdat.{check}"
                for group in TRAJECTORY_GROUPS
                + (("nf-independent",) if c["exact_nf"] else ())
                for check in ("artifact-validity", "time-grid", "columns", "values")
            ),
            *(
                f"{route}-network:{check}"
                for route in ("cli", "api", "bngir-v01", "bngl-reload")
                for check in NETWORK_CHECKS
            ),
            *(
                suffix.split(c["id"] + ":", 1)[1]
                for suffix in integrated_consumers.expected_check_ids([c["id"]])
            ),
            *(
                f"{route}-invariants:{check}"
                for route in ("nf", "native-nf")
                for check in (
                    "gdat.artifact-validity",
                    "gdat.time-grid",
                    "gdat.columns",
                    "initial-amounts",
                    "nonnegative-integer-counts",
                    "observable-aliases",
                    "invariant.conserved-total",
                )
            ),
            "worker-identity:same-installed-build",
        )
    ] + integrated_extensions.expected_ids(
        cases,
        include_boundaries=include_boundaries,
        include_graph_identity=include_graph_identity,
        include_bngir_adversarial=include_bngir_adversarial,
        include_quantity_laws=include_quantity_laws,
        include_export_format_tier=include_export_format_tier,
        include_netrule_execution=include_netrule_execution,
        include_bngsim_boundary=include_bngsim_boundary,
        include_jax_backend_measurement=include_jax_backend_measurement,
        include_rate_law_contract=include_rate_law_contract,
        include_nfnext_slices=include_nfnext_slices,
        include_api_surface=include_api_surface,
        include_stochastic_parity=include_stochastic_parity,
        include_graph_identity_contract=include_graph_identity_contract,
        include_sbml_support_boundary=include_sbml_support_boundary,
        include_atomizer_symbol_resolution=include_atomizer_symbol_resolution,
        include_atomizer_reconstruction=include_atomizer_reconstruction,
        include_energy_qualification=include_energy_qualification,
        include_workload_profile=include_workload_profile,
        include_semantic_identity=include_semantic_identity,
        include_graph_differential=include_graph_differential,
        include_capability_inventory=include_capability_inventory,
        include_real_model_fixtures=include_real_model_fixtures,
        include_corpus_selection=include_corpus_selection,
        include_biomodels_hold=include_biomodels_hold,
        full=full,
    )


def _rate_trace_row(case_id, name, result, *, evidence, trace_id, summary, receipts):
    row = dict(
        id=f"{case_id}:rate-trace:{name}",
        check=name,
        stage="rate-trace",
        integration_case=case_id,
        status=result["status"],
        detail=result["detail"],
        first_difference=result.get("first_difference"),
        **evidence,
        trace_id=trace_id,
        trace_boundary_statuses=summary["boundary_statuses"],
        trace_first_divergence=summary["first_divergence"],
        trace_blocked_at=summary["blocked_at"],
        trace_observed_failures=summary["observed_failures"],
        evidence=[summary],
        receipts=receipts,
        related_issues=[151],
    )
    row.update(integrated_traces.boundary_metadata(name))
    return row


def run_stage(
    case,
    stage,
    command,
    directory,
    rows,
    *,
    dependencies=(),
    required=(),
    env=None,
    timeout=60,
):
    blocked = [r["id"] for r in dependencies if r["status"] != "PASS"]
    row = dict(
        id=f"{case}:{stage}",
        stage=stage,
        integration_case=case,
        status="NOT_TESTED",
        detail="",
        command=command,
    )
    if blocked:
        row.update(blocked_by=blocked, detail="prerequisite handoff did not pass")
    else:
        receipt = campaign.run_command(
            command, directory, timeout, required=required, env=env
        )
        status = receipt["status"]
        worker_status = directory / "worker-status.json"
        if status == "FAIL" and worker_status.is_file():
            declared = json.loads(worker_status.read_text()).get("status")
            status = (
                declared
                if declared in ("FAIL", "HARNESS_ERROR", "UNSUPPORTED", "NOT_TESTED")
                else "HARNESS_ERROR"
            )
        row.update(
            status=status,
            detail=receipt["detail"],
            receipt=str((directory / "command.json").resolve()),
        )
    rows.append(row)
    return row


def _checks(case, stage, checks, rows, dependencies):
    receipts = [r["receipt"] for r in dependencies if r.get("receipt")]
    for check in checks:
        # Inner artifact contracts use local names for prerequisite links.
        blocked = check.pop("blocked_by", None)
        row = dict(
            check,
            id=f"{case}:{stage}:{check['check']}",
            stage=stage,
            integration_case=case,
            receipts=receipts,
        )
        if blocked:
            local = [blocked] if isinstance(blocked, str) else blocked
            row["blocked_by"] = [
                name if name.startswith(f"{case}:") else f"{case}:{stage}:{name}"
                for name in local
            ]
        rows.append(row)


def _compare(
    case, name, rows, dependencies, reference, subject, *, network=False, exact=False
):
    blocked = [r["id"] for r in dependencies if r["status"] != "PASS"]
    if blocked:
        # Emit the inner check ids the unblocked branch would produce so that
        # declared evidence is always present, each blocked by the failed handoff.
        checks = (
            NETWORK_CHECKS
            if network
            else tuple(
                "gdat." + check
                for check in ("artifact-validity", "time-grid", "columns", "values")
            )
        )
        receipts = [r["receipt"] for r in dependencies if r.get("receipt")]
        for check in checks:
            rows.append(
                dict(
                    check=check,
                    id=f"{case}:{name}:{check}",
                    stage=name,
                    integration_case=case,
                    status="NOT_TESTED",
                    detail="comparison prerequisite missing",
                    blocked_by=blocked,
                    receipts=receipts,
                )
            )
        return
    checks = (
        # BNG2 NET embeds conversion prefactors with eight significant digits
        # (e.g. 1/6 -> 0.16666667). Keep structural checks exact.
        contracts.network_contracts(reference, subject, numeric_rate_rtol=5e-8)
        if network
        else contracts.trajectory_contracts(
            reference,
            subject,
            kind="gdat",
            expected_times=TIMES,
            rtol=0 if exact else 1e-6,
            atol=0 if exact else 1e-9,
        )
    )
    _checks(case, name, checks, rows, dependencies)


def _nf_invariants(case, route, path, rows, dependency):
    """Source invariants supplement seeded parity; they never imply a distribution match."""
    stage = route + "-invariants"
    if dependency["status"] != "PASS":
        rows.append(
            dict(
                id=f"{case['id']}:{stage}",
                stage=stage,
                integration_case=case["id"],
                status="NOT_TESTED",
                detail="stochastic output prerequisite missing",
                blocked_by=[dependency["id"]],
            )
        )
        return
    try:
        data, columns = contracts._trajectory(path)
    except (ValueError, OSError) as exc:
        _checks(
            case["id"],
            stage,
            [
                dict(
                    check="gdat.artifact-validity",
                    status="HARNESS_ERROR",
                    detail=str(exc),
                )
            ],
            rows,
            [dependency],
        )
        return
    expected, names = expected_trajectory(case)
    same_names = set(names) == set(columns)
    checks = [
        dict(
            check="gdat.artifact-validity",
            status="PASS",
            detail="finite uniquely named trajectory",
        ),
        dict(
            check="gdat.time-grid",
            status=(
                "PASS"
                if len(data) == len(TIMES)
                and np.allclose(data[:, 0], TIMES, rtol=0, atol=1e-9)
                else "FAIL"
            ),
            detail="complete requested stochastic grid",
        ),
        dict(
            check="gdat.columns",
            status="PASS" if same_names else "FAIL",
            detail=f"source={names}, observed={columns}",
        ),
    ]
    if same_names:
        aligned = data[:, [columns.index(name) for name in names[1:]]]
        checks += [
            dict(
                check="initial-amounts",
                status=(
                    "PASS" if np.array_equal(aligned[0], expected[0, 1:]) else "FAIL"
                ),
                detail=f"initial={aligned[0].tolist()}, source={expected[0, 1:].tolist()}",
            ),
            dict(
                check="nonnegative-integer-counts",
                status=(
                    "PASS"
                    if np.all(aligned >= 0)
                    and np.array_equal(aligned, np.rint(aligned))
                    else "FAIL"
                ),
                detail="item observables must be nonnegative integer counts",
            ),
        ]
        aliases_ok = all(
            np.array_equal(
                data[:, columns.index(name)], data[:, columns.index(name + "_amt")]
            )
            for name in names[1:]
            if not name.endswith("_amt")
        )
        checks.append(
            dict(
                check="observable-aliases",
                status="PASS" if aliases_ok else "FAIL",
                detail="source amount aliases must equal their corresponding species counts",
            )
        )
        second = "D" if case["family"] == "dimerization" else "B"
        checks.append(
            scientific_contracts.conserved_total(
                data[:, 0],
                data[:, [columns.index("A"), columns.index(second)]],
                [1, 2 if second == "D" else 1],
                case["initial"],
            )
        )
    _checks(case["id"], stage, checks, rows, [dependency])


def _candidate_issue_ids(case, stage):
    """Map only transformed candidate-side evidence to directly tested issues."""
    transform = case.get("transform")
    trajectory = stage.endswith("-source-dynamics")
    nf_route = stage in {
        "nf",
        "native-nf",
        "nf-independent",
        "nf-invariants",
        "nf-marginals",
    }
    if transform == "function-shadowing" and (
        stage == "atomizer" or trajectory or nf_route
    ):
        return [143]
    if transform == "concentration-coordinate":
        if stage == "atomizer" or trajectory:
            return [161]
        if nf_route:
            return [151]
    return None


def run_case(case, args, rows, env):
    first_row = len(rows)
    key = case["id"]
    work = args.report_dir / "cases" / key
    work.mkdir(parents=True)
    source = work / "source.xml"
    source_xml = sbml_text(case)
    source.write_text(source_xml)
    try:
        source_status, source_detail = integrated_source.validate_sbml_source(
            source_xml
        )
    except Exception as exc:
        source_status = "HARNESS_ERROR"
        source_detail = (
            f"libSBML source validation unavailable: {type(exc).__name__}: {exc}"
        )
    source_validation = dict(
        id=f"{key}:source-validation",
        stage="source-validation",
        integration_case=key,
        status=source_status,
        detail=source_detail,
        command="libsbml.readSBMLFromString + checkConsistency",
        receipt=str(source.resolve()),
        related_issues=[],
    )
    rows.append(source_validation)
    source_oracle = integrated_source.source_sbml_oracle(
        case, source, work, source_validation
    )
    rows.append(source_oracle)
    expected = work / "analytic.gdat"
    data, columns = expected_trajectory(case)
    np.savetxt(expected, data, header=" ".join(columns), fmt="%.17g")

    def worker(operation, source, *, upstream=False, xml_out=None):
        command = [
            str(args.pybionetgen_python) if upstream else sys.executable,
            "-I",
            "-B",
            str(WORKER),
            operation,
            "--input",
            str(source),
            "--case-id",
            key,
        ]
        if upstream:
            command += ["--upstream", str(args.pybionetgen_root)]
        if operation == "atomizer" and case["atomize"]:
            command += ["--atomize"]
        if xml_out is not None:
            command += ["--xml-out", str(xml_out)]
        return command

    def stage(name, command, *, deps=(), required=()):
        return run_stage(
            key,
            name,
            command,
            work / name,
            rows,
            dependencies=deps,
            required=required,
            env=env,
        )

    translated = work / "atomizer/model.bngl"
    bng3_xml = work / "bng3/model.xml"
    atomizer = stage(
        "atomizer",
        worker("atomizer", source, xml_out=bng3_xml),
        deps=[source_validation],
        required=("model.bngl", "identity.json"),
    )
    if atomizer["status"] == "PASS" and not bng3_xml.is_file():
        atomizer.update(status="HARNESS_ERROR", detail="missing BNG3 NFsim XML export")
    rate_trace = stage(
        "rate-trace",
        worker("rate-trace", translated),
        deps=[source_validation, atomizer],
        required=("rate-trace.json", "identity.json"),
    )
    observation = None
    net_export = integrated_traces.exported_net_rates(work / "rate-trace/model.net")
    xml_export = None
    try:
        source_trace = integrated_traces.source_rate_trace(source_xml)
        xml_export = integrated_traces.exported_bng_xml(
            work / "rate-trace/model.xml", source_trace
        )
        observation_path = work / "rate-trace/rate-trace.json"
        observation = (
            json.loads(observation_path.read_text())
            if rate_trace["status"] == "PASS" and observation_path.is_file()
            else None
        )
        trace_result = integrated_traces.compare_rate_trace(source_trace, observation)
        net_result = integrated_traces.compare_rate_values(
            observation.get("reaction_rate_coefficients") if observation else None,
            net_export.get("effective_rates"),
            "BNG3 NET export vs compiled API",
            # BNG NET values are serialized with twelve significant digits.
            rtol=5e-11,
        )
        xml_result = integrated_traces.compare_rate_values(
            net_export.get("effective_rates"),
            xml_export.get("effective_rates"),
            "BNG-XML compartment-converted coefficients vs NET",
            rtol=5e-11,
        )
    except Exception as exc:
        source_trace = None
        trace_result = net_result = xml_result = dict(
            status="HARNESS_ERROR",
            detail=f"could not construct source-to-compiled rate trace: {type(exc).__name__}: {exc}",
            first_difference=None,
        )
    trace_receipts = [rate_trace.get("receipt")] if rate_trace.get("receipt") else []
    trace_boundary_rows = [
        ("source-to-compiled", trace_result),
        ("compiled-to-net", net_result),
        ("net-to-bngxml", xml_result),
    ]
    trace_summary = integrated_traces.first_differing_boundary(
        [
            dict(
                name=name,
                status=result["status"],
                first_difference=result.get("first_difference"),
            )
            for name, result in trace_boundary_rows
        ]
    )
    trace_id = (
        integrated_traces.trace_identity(key, source_trace)
        if source_trace is not None
        else f"{key}:rate-units:source-unavailable"
    )
    for name, result, evidence in (
        (
            "source-compiled-rate-multiset",
            trace_result,
            {"source_trace": source_trace, "observation": observation},
        ),
        (
            "compiled-net-rate-multiset",
            net_result,
            {
                "compiled_trace_id": f"{key}:rate-trace:source-compiled-rate-multiset",
                "observation": observation,
                "net_export": net_export,
            },
        ),
        (
            "net-bngxml-rate-coefficient",
            xml_result,
            {
                "net_trace_id": f"{key}:rate-trace:compiled-net-rate-multiset",
                "net_export": net_export,
                "bng_xml_export": xml_export,
            },
        ),
    ):
        rows.append(
            _rate_trace_row(
                key,
                name,
                result,
                evidence=evidence,
                trace_id=trace_id,
                summary=trace_summary,
                receipts=trace_receipts,
            )
        )
    # Identical translated source, copied before adding the same action protocol.
    actions = (
        "\nbegin actions\ngenerate_network({overwrite=>1})\n"
        "writeXML()\nsimulate_ode({t_end=>2,n_steps=>10,rtol=>1e-10,atol=>1e-12})\nend actions\n"
    )
    if atomizer["status"] == "PASS":
        text = translated.read_text()
        for route in ("bng2", "cli", "pybng", "compat"):
            directory = work / route
            directory.mkdir()
            (directory / "model.bngl").write_text(text + actions)

    bng2 = stage(
        "bng2",
        ["perl", str(args.bng2_root / "bng2/BNG2.pl"), str(work / "bng2/model.bngl")],
        deps=[atomizer],
        required=("model.net", "model.gdat", "model.xml"),
    )
    cli = stage(
        "cli",
        [str(args.bng_cpp), str(work / "cli/model.bngl")],
        deps=[atomizer],
        required=("model.net", "model.gdat"),
    )
    api = stage(
        "api",
        worker("api", translated),
        deps=[atomizer],
        required=("model.net", "api.gdat", "identity.json"),
    )
    pybng = stage(
        "pybng",
        worker("pybng", work / "pybng/model.bngl", upstream=True),
        deps=[atomizer],
        required=("api.gdat", "model.gdat", "identity.json"),
    )
    compat = stage(
        "compat",
        worker("compat", work / "compat/model.bngl"),
        deps=[atomizer],
        required=("api.gdat", "model.gdat", "identity.json"),
    )
    nf = stage(
        "nf",
        worker("nf", translated),
        deps=[atomizer],
        required=("nf.gdat", "identity.json"),
    )
    # The pinned oracle applies a compartment size only to zero-order
    # synthesis, so BNG2's XML states a reactant-bearing rule at a rate the
    # oracle reads without the compartment unit conversion. The XML is
    # normalised into BNG2's count-rate convention first, so the oracle
    # samples the model the embedded engine executes. When the rewrite cannot
    # state the convention, the oracle runs on BNG2's XML and the stage records
    # why, rather than the whole run stopping.
    native_xml = work / "bng2/model.xml"
    normalised = integrated_traces.native_count_rate_xml(
        native_xml, work / "native-nf/count-rate-model.xml"
    )
    oracle_xml = (
        work / "native-nf/count-rate-model.xml"
        if normalised["status"] == "NORMALISED"
        else native_xml
    )
    native = stage(
        "native-nf",
        [
            str(args.nfsim_binary),
            "-xml",
            str(oracle_xml),
            "-o",
            str(work / "native-nf/nf.gdat"),
            "-sim",
            "2",
            "-oSteps",
            "10",
            "-seed",
            "7",
        ],
        deps=[bng2],
        required=("nf.gdat",),
    )
    if normalised["status"] != "NORMALISED":
        # The oracle could not be handed the model in BNG2's count-rate
        # convention, so the stage ran on BNG2's XML and the reason is kept
        # with the stage's record.
        native["detail"] = (
            "the native NFsim oracle ran on BNG2's XML, not on the model in "
            "BNG2's count-rate convention: " + normalised["detail"]
        )

    consumers = []
    for operation in integrated_consumers.OPERATIONS:
        required = (
            "api.gdat",
            "identity.json",
            "checks.json",
            "native-network.json" if operation == "bngir-v02" else "model.net",
        )
        consumer = stage(
            operation, worker(operation, translated), deps=[atomizer], required=required
        )
        consumers.append(consumer)
        checks_path = work / operation / "checks.json"
        validated_checks = []
        if checks_path.is_file():
            checks = json.loads(checks_path.read_text())
            errors = integrated_consumers.validate_checks(key, operation, checks)
            if errors:
                consumer.update(status="HARNESS_ERROR", detail="; ".join(errors))
            else:
                validated_checks = checks
                integrated_consumers.mark_process_summary(consumer, checks)
                for check in checks:
                    check = dict(
                        check,
                        check=check["name"],
                        related_issues=check["issue_ids"],
                        stage=operation,
                        integration_case=key,
                        receipts=(
                            [consumer["receipt"]] if consumer.get("receipt") else []
                        ),
                    )
                    rows.append(check)
        _compare(
            key,
            operation + "-source-dynamics",
            rows,
            [
                integrated_consumers.handoff_dependency(
                    consumer,
                    validated_checks,
                    (
                        "original"
                        if operation == "reuse"
                        else (
                            "trajectory" if operation == "sbml-reload" else "simulation"
                        )
                    ),
                )
            ],
            expected,
            work / operation / "api.gdat",
        )
        if operation in ("bngir-v01", "bngl-reload"):
            _compare(
                key,
                operation + "-network",
                rows,
                [
                    bng2,
                    integrated_consumers.handoff_dependency(
                        consumer, validated_checks, "network"
                    ),
                ],
                work / "bng2/model.net",
                work / operation / "model.net",
                network=True,
            )

    # Reload BNG3's own serialization through its CLI, then compare to the
    # independently specified source dynamics. No generated golden becomes an oracle.
    if api["status"] == "PASS":
        directory = work / "net-reload"
        directory.mkdir()
        shutil.copyfile(work / "api/model.net", directory / "model.net")
        (directory / "reload.bngl").write_text(
            net_reload_context(translated)
            + '\nbegin actions\nreadFile({file=>"model.net"})\n'
            'simulate_ode({t_end=>2,n_steps=>10,rtol=>1e-10,atol=>1e-12,prefix=>"reload"})\nend actions\n'
        )
    reload = stage(
        "net-reload",
        [str(args.bng_cpp), str(work / "net-reload/reload.bngl")],
        deps=[api],
        required=("reload.gdat",),
    )
    for name, dep, path in (
        ("bng2", bng2, work / "bng2/model.gdat"),
        ("cli", cli, work / "cli/model.gdat"),
        ("api", api, work / "api/api.gdat"),
        ("compat", compat, work / "compat/api.gdat"),
        ("pybng", pybng, work / "pybng/api.gdat"),
        ("net-reload", reload, work / "net-reload/reload.gdat"),
    ):
        _compare(key, name + "-source-dynamics", rows, [dep], expected, path)
    for name, dep in (("cli", cli), ("api", api)):
        _compare(
            key,
            name + "-network",
            rows,
            [bng2, dep],
            work / "bng2/model.net",
            work / name / "model.net",
            network=True,
        )
    _compare(
        key,
        "pybng-returned-data",
        rows,
        [pybng],
        work / "pybng/model.gdat",
        work / "pybng/api.gdat",
        exact=True,
    )
    _compare(
        key,
        "python-public-compatibility",
        rows,
        [pybng, compat],
        work / "pybng/api.gdat",
        work / "compat/api.gdat",
    )
    if case["exact_nf"]:
        _compare(
            key,
            "nf-independent",
            rows,
            [native, nf],
            work / "native-nf/nf.gdat",
            work / "nf/nf.gdat",
            exact=True,
        )
    for route, dep in (("nf", nf), ("native-nf", native)):
        _nf_invariants(case, route, work / route / "nf.gdat", rows, dep)
    qualifications = [
        integrated_extensions.invoke(
            "protocol", args, rows, env, run_stage, case=case, dependencies=[atomizer]
        )
    ]
    if case["family"] in ("decay", "reversible", "dimerization"):
        qualifications.append(
            integrated_extensions.invoke(
                "nf-marginals",
                args,
                rows,
                env,
                run_stage,
                case=case,
                dependencies=[atomizer, bng2],
            )
        )
    # Confirm repeated installed workers did not silently select another build.
    identity_stages = [
        atomizer,
        rate_trace,
        api,
        compat,
        nf,
        *consumers,
        *qualifications,
    ]
    blocked = [
        r["id"]
        for r in identity_stages
        if not (work / r["stage"] / "identity.json").is_file()
    ]
    if blocked:
        check = dict(
            check="same-installed-build",
            status="NOT_TESTED",
            detail="process identity prerequisite missing",
            blocked_by=blocked,
        )
    else:
        observed = [
            json.loads((work / r["stage"] / "identity.json").read_text())
            for r in identity_stages
        ]
        consistent = (
            len({(i["package_file"], i["native_extension_sha256"]) for i in observed})
            == 1
        )
        check = dict(
            check="same-installed-build",
            status="PASS" if consistent else "HARNESS_ERROR",
            detail="package location and native extension digest across Atomizer/API/compat/NF workers",
        )
    _checks(key, "worker-identity", [check], rows, identity_stages)
    for row in rows[first_row:]:
        row["base_case_id"] = case.get("base_case_id", case["id"])
        row["transform"] = case.get("transform", "identity")
        row["quantity_basis"] = case.get("quantity_basis", "initialAmount; item amount")
        issue_ids = _candidate_issue_ids(case, row["stage"])
        if issue_ids is not None:
            row["related_issues"] = issue_ids


def _preflight(args):
    lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
    references = {}
    for name, path in (
        ("bionetgen", args.bng2_root),
        ("nfsim", args.nfsim_root),
        ("pybionetgen", args.pybionetgen_root),
    ):
        if path.resolve().is_relative_to(ROOT):
            raise ValueError("embedded source cannot qualify independent compatibility")
        references[name] = campaign.verify_source(path, lock["sources"][name])
    binary = args.bng2_root / "bng2/bin/run_network"
    campaign.verify_digest(binary, args.bng2_network_sha256)
    campaign.verify_digest(args.nfsim_binary, args.nfsim_sha256)
    for oracle in (binary, args.nfsim_binary):
        campaign.reject_shared_engine(args.bng_cpp, oracle, implementation_root=ROOT)
    references["bionetgen"].update(
        script=str(args.bng2_root / "bng2/BNG2.pl"),
        network_binary=str(binary),
        network_binary_sha256=inventory.sha256(binary),
        interpreter="perl",
        script_sha256=inventory.sha256(args.bng2_root / "bng2/BNG2.pl"),
    )
    references["nfsim"].update(
        binary=str(args.nfsim_binary), sha256=inventory.sha256(args.nfsim_binary)
    )
    if not args.pybionetgen_python.is_file():
        raise ValueError("isolated upstream Python interpreter is missing")
    references["pybionetgen"]["python_executable"] = str(args.pybionetgen_python)
    return references


# The focused-campaign flag of every qualification: the qualification's name
# and the argument that selects it.  A focused flag selects exactly its own
# qualification and excludes the others, and the selection is derived from
# this table, so a new qualification cannot silently exclude itself.
FOCUS_FLAGS = {
    "boundaries": "boundaries_only",
    "graph_identity": "graph_identity_only",
    "bngir_adversarial": "bngir_adversarial_only",
    "quantity_laws": "quantity_laws_only",
    "export_format_tier": "export_format_tier_only",
    "netrule_execution": "netrule_execution_only",
    "bngsim_boundary": "bngsim_boundary_only",
    "jax_backend_measurement": "jax_backend_measurement_only",
    "rate_law_contract": "rate_law_contract_only",
    "nfnext_slices": "nfnext_slices_only",
    "api_surface": "api_surface_only",
    "stochastic_parity": "stochastic_parity_only",
    "graph_identity_contract": "graph_identity_contract_only",
    "sbml_support_boundary": "sbml_support_boundary_only",
    "atomizer_symbol_resolution": "atomizer_symbol_resolution_only",
    "atomizer_reconstruction": "atomizer_reconstruction_only",
    "energy_qualification": "energy_qualification_only",
    "workload_profile": "workload_profile_only",
    "semantic_identity": "semantic_identity_only",
    "graph_differential": "graph_differential_only",
    "capability_inventory": "capability_inventory_only",
    "real_model_fixtures": "real_model_fixtures_only",
    "corpus_selection": "corpus_selection_only",
    "biomodels_hold": "biomodels_hold_only",
}


def select_qualifications(focused_flags):
    """Return the qualification selection for the focused campaign flags.

    Every focused campaign flag selects exactly its own qualification and
    excludes the others. The selection is derived from the flag table so a
    new qualification cannot silently exclude itself.
    """
    if not isinstance(focused_flags, dict) or not focused_flags:
        raise ValueError("the focused flag table must be a non-empty mapping")

    def _other_focused(name):
        return any(value for key, value in focused_flags.items() if key != name)

    return {f"include_{name}": not _other_focused(name) for name in FOCUS_FLAGS}


def focus_selection(args):
    """Return the family selection of one campaign run.

    Without a focused flag every qualification runs.  With one, that
    qualification runs and the others do not.
    """
    return select_qualifications(
        {name: bool(getattr(args, dest, False)) for name, dest in FOCUS_FLAGS.items()}
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "bng-cpp",
        "bng2-root",
        "nfsim-root",
        "nfsim-binary",
        "pybionetgen-root",
        "pybionetgen-python",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("bng2-network-sha256", "nfsim-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--boundaries-only", action="store_true")
    parser.add_argument("--graph-identity-only", action="store_true")
    parser.add_argument("--bngir-adversarial-only", action="store_true")
    parser.add_argument("--quantity-laws-only", action="store_true")
    parser.add_argument("--export-format-tier-only", action="store_true")
    parser.add_argument("--netrule-execution-only", action="store_true")
    parser.add_argument("--bngsim-boundary-only", action="store_true")
    parser.add_argument("--jax-backend-measurement-only", action="store_true")
    parser.add_argument("--rate-law-contract-only", action="store_true")
    parser.add_argument("--api-surface-only", action="store_true")
    parser.add_argument("--stochastic-parity-only", action="store_true")
    parser.add_argument("--graph-identity-contract-only", action="store_true")
    parser.add_argument("--sbml-support-boundary-only", action="store_true")
    parser.add_argument("--atomizer-symbol-resolution-only", action="store_true")
    parser.add_argument("--atomizer-reconstruction-only", action="store_true")
    parser.add_argument("--energy-qualification-only", action="store_true")
    parser.add_argument("--workload-profile-only", action="store_true")
    parser.add_argument("--semantic-identity-only", action="store_true")
    parser.add_argument("--graph-differential-only", action="store_true")
    parser.add_argument("--capability-inventory-only", action="store_true")
    parser.add_argument("--real-model-fixtures-only", action="store_true")
    parser.add_argument("--corpus-selection-only", action="store_true")
    parser.add_argument("--biomodels-hold-only", action="store_true")
    parser.add_argument("--nfnext-slices-only", action="store_true")
    parser.add_argument("--ensemble-runs", type=int)
    args = parser.parse_args(argv)
    if (
        sum(
            (
                args.boundaries_only,
                args.graph_identity_only,
                args.bngir_adversarial_only,
                args.quantity_laws_only,
                args.export_format_tier_only,
                args.netrule_execution_only,
                args.bngsim_boundary_only,
                args.jax_backend_measurement_only,
                args.rate_law_contract_only,
                args.nfnext_slices_only,
            )
        )
        > 1
    ):
        parser.error("select at most one focused qualification")
    args.ensemble_runs = (
        args.ensemble_runs
        if args.ensemble_runs is not None
        else (128 if args.full else 32)
    )
    if not 8 <= args.ensemble_runs <= 256:
        parser.error("ensemble run budget must be 8..256")
    all_cases = generated_cases(full=True)
    if set(args.case) - {c["id"] for c in all_cases}:
        parser.error("unknown integration case")
    selected = (
        [c for c in all_cases if c["id"] in args.case]
        if args.case
        else generated_cases(args.full)
    )
    if (
        args.boundaries_only
        or args.graph_identity_only
        or args.bngir_adversarial_only
        or args.quantity_laws_only
        or args.export_format_tier_only
        or args.netrule_execution_only
        or args.bngsim_boundary_only
        or args.jax_backend_measurement_only
        or args.rate_law_contract_only
        or args.nfnext_slices_only
    ):
        selected = []
    for name in (
        "bng_cpp",
        "bng2_root",
        "nfsim_root",
        "nfsim_binary",
        "pybionetgen_root",
        "pybionetgen_python",
        "report_dir",
    ):
        # Preserve the venv executable path: resolving its symlink selects the
        # base interpreter and loses isolation.
        setattr(args, name, Path(os.path.abspath(getattr(args, name))))
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        parser.error("report directory must be empty")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        BNGPATH=str(args.bng2_root / "bng2"),
        PYTHONDONTWRITEBYTECODE="1",
        MPLBACKEND="Agg",
        SYMPY_USE_GMPY="0",
    )
    env.pop("PYTHONPATH", None)
    env["BIONETGEN_USE_PERL"] = "0"
    # Every focused campaign flag selects exactly its own qualification and
    # excludes the others. The selection is derived from the flag table so a
    # new qualification cannot silently exclude itself.
    qualification_selection = focus_selection(args)
    required_ids = expected_contract_ids(
        selected, full=args.full, **qualification_selection
    )
    rows, references = [], {}
    try:
        references = _preflight(args)
        subject_digest = inventory.sha256(args.bng_cpp)
        if qualification_selection["include_boundaries"]:
            integrated_extensions.invoke("boundaries", args, rows, env, run_stage)
        if qualification_selection["include_graph_identity"]:
            integrated_extensions.invoke("graph-identity", args, rows, env, run_stage)
        if qualification_selection["include_bngir_adversarial"]:
            integrated_extensions.invoke(
                "bngir-adversarial", args, rows, env, run_stage
            )
        if qualification_selection["include_quantity_laws"]:
            integrated_extensions.invoke("quantity-laws", args, rows, env, run_stage)
        if qualification_selection["include_export_format_tier"]:
            integrated_extensions.invoke(
                "export-format-tier", args, rows, env, run_stage
            )
        if qualification_selection["include_netrule_execution"]:
            integrated_extensions.invoke(
                "netrule-execution", args, rows, env, run_stage
            )
        if qualification_selection["include_bngsim_boundary"]:
            integrated_extensions.invoke("bngsim-boundary", args, rows, env, run_stage)
        if qualification_selection["include_jax_backend_measurement"]:
            integrated_extensions.invoke(
                "jax-backend-measurement", args, rows, env, run_stage
            )
        if qualification_selection["include_api_surface"]:
            integrated_extensions.invoke("api-surface", args, rows, env, run_stage)
        if qualification_selection["include_stochastic_parity"]:
            integrated_extensions.invoke(
                "stochastic-parity", args, rows, env, run_stage
            )
        if qualification_selection["include_graph_identity_contract"]:
            integrated_extensions.invoke(
                "graph-identity-contract", args, rows, env, run_stage
            )
        if qualification_selection["include_sbml_support_boundary"]:
            integrated_extensions.invoke(
                "sbml-support-boundary", args, rows, env, run_stage
            )
        if qualification_selection["include_atomizer_symbol_resolution"]:
            integrated_extensions.invoke(
                "atomizer-symbol-resolution", args, rows, env, run_stage
            )
        if qualification_selection["include_energy_qualification"]:
            integrated_extensions.invoke(
                "energy-qualification", args, rows, env, run_stage
            )
        if qualification_selection["include_semantic_identity"]:
            integrated_extensions.invoke(
                "semantic-identity", args, rows, env, run_stage
            )
        if qualification_selection["include_capability_inventory"]:
            integrated_extensions.invoke(
                "capability-inventory", args, rows, env, run_stage
            )
        if qualification_selection["include_real_model_fixtures"]:
            integrated_extensions.invoke(
                "real-model-fixtures", args, rows, env, run_stage
            )
        if qualification_selection["include_corpus_selection"]:
            integrated_extensions.invoke("corpus-selection", args, rows, env, run_stage)
        if qualification_selection["include_biomodels_hold"]:
            integrated_extensions.invoke("biomodels-hold", args, rows, env, run_stage)
        if qualification_selection["include_graph_differential"]:
            integrated_extensions.invoke(
                "graph-differential", args, rows, env, run_stage
            )
        if qualification_selection["include_workload_profile"]:
            integrated_extensions.invoke("workload-profile", args, rows, env, run_stage)
        if qualification_selection["include_atomizer_reconstruction"]:
            integrated_extensions.invoke(
                "atomizer-reconstruction", args, rows, env, run_stage
            )
        if qualification_selection["include_rate_law_contract"]:
            integrated_extensions.invoke(
                "rate-law-contract", args, rows, env, run_stage
            )
        if qualification_selection["include_nfnext_slices"]:
            integrated_extensions.invoke("nfnext-slices", args, rows, env, run_stage)
        for case in selected:
            run_case(case, args, rows, env)
        # Inputs/oracles must still have their preflight identities after execution.
        if (
            _preflight(args) != references
            or inventory.sha256(args.bng_cpp) != subject_digest
        ):
            raise ValueError(
                "runtime or reference identity changed during integration run"
            )
        missing = set(required_ids) - {r["id"] for r in rows}
        if missing and all(r["status"] == "PASS" for r in rows):
            raise ValueError(
                "missing semantic integration evidence: " + ", ".join(sorted(missing))
            )
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        rows.append(
            dict(
                id="integrated:infrastructure",
                stage="integration-preflight",
                status="HARNESS_ERROR",
                detail=str(exc),
            )
        )
    replay_base = [sys.executable, "-m", "tests.validation.integrated"]
    for name in (
        "bng_cpp",
        "bng2_root",
        "bng2_network_sha256",
        "nfsim_root",
        "nfsim_binary",
        "nfsim_sha256",
        "pybionetgen_root",
        "pybionetgen_python",
    ):
        replay_base += ["--" + name.replace("_", "-"), str(getattr(args, name))]
    replay_base += ["--ensemble-runs", str(args.ensemble_runs)]
    focused_qualifications = {
        "quantity-laws": ["--quantity-laws-only"],
        "api-surface": ["--api-surface-only"],
        "stochastic-parity": ["--stochastic-parity-only"],
        "graph-identity-contract": ["--graph-identity-contract-only"],
        "sbml-support-boundary": ["--sbml-support-boundary-only"],
        "atomizer-symbol-resolution": ["--atomizer-symbol-resolution-only"],
        "atomizer-reconstruction": ["--atomizer-reconstruction-only"],
        "energy-qualification": ["--energy-qualification-only"],
        "workload-profile": ["--workload-profile-only"],
        "semantic-identity": ["--semantic-identity-only"],
        "graph-differential": ["--graph-differential-only"],
        "capability-inventory": ["--capability-inventory-only"],
        "real-model-fixtures": ["--real-model-fixtures-only"],
        "corpus-selection": ["--corpus-selection-only"],
        "biomodels-hold": ["--biomodels-hold-only"],
        "boundaries": ["--boundaries-only"],
        "bngir-adversarial": ["--bngir-adversarial-only"],
        "graph-identity": ["--graph-identity-only"],
        "export-format-tier": ["--export-format-tier-only"],
        "netrule-execution": ["--netrule-execution-only"],
        "jax-backend-measurement": ["--jax-backend-measurement-only"],
        "rate-law-contract": ["--rate-law-contract-only"],
        "nfnext-slices": ["--nfnext-slices-only"],
    }
    for row in rows:
        case_id = row.get("integration_case")
        selection = focused_qualifications.get(row.get("qualification"))
        if selection is None:
            selection = ["--case", case_id] if case_id else []
        row["command"] = (
            replay_base
            + (["--full"] if args.full else [])
            + selection
            + (
                ["--quantity-laws-only"]
                if row.get("qualification") == "quantity-laws"
                else (
                    ["--bngsim-boundary-only"]
                    if row.get("qualification") == "bngsim-boundary"
                    else []
                )
            )
            + (
                ["--boundaries-only"]
                if row.get("qualification") == "boundaries"
                else (
                    ["--bngir-adversarial-only"]
                    if row.get("qualification") == "bngir-adversarial"
                    else (
                        ["--graph-identity-only"]
                        if row.get("qualification") == "graph-identity"
                        else (["--case", case_id] if case_id else [])
                    )
                )
            )
            + [
                "--report-dir",
                str(args.report_dir.parent / ("replay-" + (case_id or "preflight"))),
            ]
        )
        row["source_locations"] = {
            "atomizer": [
                "python/bionetgen/sbml.py",
                "python/bionetgen/atomizer/modern/writer.py",
            ],
            "api": ["python/bionetgen/model.py"],
            "compat": ["python/bionetgen/compat/runner.py"],
            "pybng": ["tests/validation/integrated_worker.py"],
            "nf": ["cpp/nfsim/NFinput/NFinput_fromAst.cpp"],
            "native-nf": [
                "tests/validation/integrated.py",
                "tests/validation/integrated_worker.py",
            ],
        }.get(
            row["stage"],
            ["tests/validation/integrated.py", "tests/validation/contracts.py"],
        )
        if row["stage"] in integrated_consumers.OPERATIONS:
            row["source_locations"] = [
                "tests/validation/integrated_worker.py",
                (
                    "python/bionetgen/bngir.py"
                    if row["stage"].startswith("bngir")
                    else "python/bionetgen/model.py"
                ),
            ]
        row.setdefault("question", "generated-cross-component-handoff")
        if row["stage"] in integrated_extensions.OPERATIONS:
            source_locations = {
                "boundaries": "tests/validation/integrated_boundaries.py",
                "protocol": "tests/validation/integrated_protocol.py",
                "nf-marginals": "tests/validation/integrated_marginals.py",
                "quantity-laws": "tests/validation/integrated_marginals.py",
                "bngir-adversarial": [
                    "tests/validation/bngir_adversarial.py",
                    "tests/validation/bngir_format_contracts.py",
                    "tests/validation/bngir_reconstruction_contracts.py",
                ],
                "graph-identity": "tests/validation/graph_identity.py",
                "export-format-tier": "tests/validation/export_format_tier.py",
                "api-surface": "tests/validation/api_surface.py",
                "stochastic-parity": "tests/validation/stochastic_parity.py",
                "graph-identity-contract": (
                    "tests/validation/graph_identity_contract.py"
                ),
                "sbml-support-boundary": ("tests/validation/sbml_support_boundary.py"),
                "atomizer-symbol-resolution": (
                    "tests/validation/atomizer_symbol_resolution.py"
                ),
                "atomizer-reconstruction": (
                    "tests/validation/atomizer_reconstruction.py"
                ),
                "energy-qualification": "tests/validation/energy_qualification.py",
                "workload-profile": "tests/validation/workload_profile.py",
                "semantic-identity": "tests/validation/semantic_identity.py",
                "graph-differential": "tests/validation/graph_differential.py",
                "capability-inventory": "tests/validation/capability_inventory.py",
                "real-model-fixtures": "tests/validation/real_model_fixtures.py",
                "corpus-selection": "tests/validation/corpus_selection.py",
                "biomodels-hold": "tests/validation/biomodels_hold.py",
                "netrule-execution": [
                    "tests/validation/netrule_execution.py",
                    "cpp/engine/NetworkRulePlan.cpp",
                    "cpp/engine/LegacyNetworkRuleKernel.cpp",
                ],
                "bngsim-boundary": [
                    "tests/validation/bngsim_boundary.py",
                    "cpp/engine/FiniteBackend.cpp",
                ],
                "jax-backend-measurement": [
                    "tests/validation/jax_backend_measurement.py",
                    "python/bionetgen/jax_ode.py",
                    "python/bionetgen/jax_ssa.py",
                ],
            }[row["stage"]]
            row["source_locations"] = (
                source_locations
                if isinstance(source_locations, list)
                else [source_locations]
            )
            if row["stage"] == "graph-identity":
                row["question"] = "native-network-graph-identity-vs-independent-oracle"
            if row["stage"] == "netrule-execution":
                row["question"] = (
                    "compile-owned-network-rule-contract-vs-legacy-path-and-oracle"
                )
            if row["stage"] == "jax-backend-measurement":
                row["question"] = (
                    "jax-backend-stage-profile-vs-independent-closed-form-law"
                )
        if row["stage"] == "rate-trace":
            row["source_locations"] = [
                "tests/validation/integrated_traces.py",
                "tests/validation/integrated_worker.py",
                "cpp/bindings/bind_engine.cpp",
            ]
            row["question"] = "source-sbml-rate-and-unit-scaling-vs-bng3-compiled-rhs"
        stage = row["stage"]
        if "related_issues" not in row:
            if stage == "bngir-adversarial":
                issues = [153, 154, 155, 156]
            elif stage == "boundaries":
                issues = [157, 158, 160, 161, 164]
            elif stage == "protocol":
                issues = [138, 139, 140, 141, 143, 171, 172]
            elif stage in {"nf-marginals", "quantity-laws"}:
                issues = [143, 146, 151, 167]
            elif stage == "graph-identity":
                issues = [142]
            elif stage == "export-format-tier":
                issues = [163]
            elif stage == "netrule-execution":
                issues = [139]
            elif stage == "bngsim-boundary":
                issues = [144]
            elif stage == "api-surface":
                issues = [171]
            elif stage == "stochastic-parity":
                issues = [167]
            elif stage == "graph-identity-contract":
                issues = [142]
            elif stage == "sbml-support-boundary":
                issues = [160]
            elif stage == "atomizer-symbol-resolution":
                issues = [164]
            elif stage == "atomizer-reconstruction":
                issues = [161]
            elif stage == "energy-qualification":
                issues = [177]
            elif stage == "workload-profile":
                issues = [176]
            elif stage == "semantic-identity":
                issues = [166]
            elif stage == "graph-differential":
                issues = [168]
            elif stage == "capability-inventory":
                issues = [137]
            elif stage == "real-model-fixtures":
                issues = [152]
            elif stage == "corpus-selection":
                issues = [181]
            elif stage == "biomodels-hold":
                issues = [162]
            elif stage == "jax-backend-measurement":
                issues = [174]
            elif stage in integrated_consumers.ISSUES:
                issues = list(integrated_consumers.ISSUES[stage])
            elif stage.startswith(("bngir-", "bngl-reload")):
                issues = [153, 154, 155, 156, 163]
            elif stage.startswith(("nf", "native-nf")):
                issues = [142, 146, 151]
            elif stage in (
                "compat",
                "pybng",
                "python-public-compatibility",
                "pybng-returned-data",
            ):
                issues = [140, 171, 172]
            elif stage == "atomizer":
                issues = [143, 161, 164]
            elif stage == "integration-preflight":
                issues = [179, 180]
            else:
                issues = [138, 140, 143, 163]
            row["related_issues"] = issues
        row["capabilities"] = ["integration.cross-component"]
        if row["stage"] == "netrule-execution":
            # The compile-owned network-rule contract qualification is the
            # independent evidence for the network expansion capability.
            row["capabilities"].append("network.expansion")
    import yaml

    matrix = yaml.safe_load((ROOT / "provenance/capability-matrix.yml").read_text())
    capabilities = inventory.discover_capabilities(
        ROOT, matrix["validation_capabilities"]
    )
    reporting.attach_coverage(capabilities, rows)
    annotate_acceptance_evidence(rows)
    report = dict(
        schema_version=1,
        generated_by="tests.validation.integrated",
        source=dict(
            revision=campaign.git(ROOT, "rev-parse", "HEAD"),
            dirty=bool(campaign.git(ROOT, "status", "--porcelain")),
        ),
        subject=dict(
            binary=str(args.bng_cpp),
            sha256=inventory.sha256(args.bng_cpp) if args.bng_cpp.is_file() else None,
        ),
        configuration=dict(
            cases=selected,
            environment={
                k: env[k]
                for k in (
                    "BNGPATH",
                    "PYTHONDONTWRITEBYTECODE",
                    "MPLBACKEND",
                    "SYMPY_USE_GMPY",
                    "BIONETGEN_USE_PERL",
                )
            },
            t_end=2,
            n_steps=10,
            seed=7,
            ensemble_runs=args.ensemble_runs,
            ensemble_alpha_global=1e-6,
            ensemble_case_budget=len(all_cases),
            rtol=1e-6,
            atol=1e-9,
        ),
        inputs={
            str(p.relative_to(ROOT)): inventory.sha256(p)
            for p in (
                Path(__file__),
                WORKER,
                Path(integrated_consumers.__file__),
                Path(integrated_source.__file__),
                Path(integrated_extensions.__file__),
                Path(integrated_traces.__file__),
                ROOT / "tests/validation/integrated_protocol.py",
                ROOT / "tests/validation/bngir_adversarial.py",
                ROOT / "tests/validation/integrated_boundaries.py",
                ROOT / "tests/validation/integrated_marginals.py",
                ROOT / "tests/validation/integrated_cases.py",
                ROOT / "tests/validation/export_format_tier.py",
                ROOT / "tests/validation/netrule_execution.py",
                ROOT / "tests/validation/bngsim_boundary.py",
                ROOT / "tests/validation/compare.py",
                ROOT / "provenance/upstreams.lock.yml",
                ROOT / "provenance/capability-matrix.yml",
                ROOT / "tests/validation/contracts.py",
            )
        },
        references=references,
        results=rows,
        capabilities=capabilities,
        issue_coverage=reporting.issue_coverage(capabilities, rows),
        expected_contract_ids=required_ids,
        failure_clusters=reporting.cluster_failures(rows),
    )
    obligation_catalog = json.loads(
        (ROOT / "provenance/issue-obligations.json").read_text()
    )
    report["required_obligation_checks"] = sorted(
        {
            check["id"]
            for issue in obligation_catalog["issues"]
            for obligation in issue["obligations"]
            for check in obligation["required_checks"]
        }
    )
    report["obligation_catalog_sha256"] = inventory.sha256(
        ROOT / "provenance/issue-obligations.json"
    )
    report["investigation_tasks"] = reporting.investigation_tasks(
        report, args.report_dir
    )
    for task in report["investigation_tasks"]:
        task["replay_status"] = "PREPARED_NOT_EXECUTED"
        task["replay_requirements"] = [
            "Restore the recorded source revision, installed BNG3 package and independent oracle identities.",
            "Use the recorded separate upstream interpreter; choose an empty report directory.",
        ]
    for name, content in (
        ("report.json", report),
        ("investigation-tasks.json", report["investigation_tasks"]),
    ):
        (args.report_dir / name).write_text(json.dumps(content, indent=2) + "\n")
    artifacts = [
        dict(path=str(p.relative_to(args.report_dir)), sha256=inventory.sha256(p))
        for p in sorted(args.report_dir.rglob("*"))
        if p.is_file()
    ]
    (args.report_dir / "artifacts.json").write_text(
        json.dumps(artifacts, indent=2) + "\n"
    )
    return int(bool(reporting.gate_failures(rows)))


if __name__ == "__main__":
    raise SystemExit(main())
