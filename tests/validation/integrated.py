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
from .integrated_cases import TIMES, generated_cases, sbml_text, expected_trajectory
from . import integrated_consumers, scientific_contracts, integrated_extensions

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("integrated_worker.py")
# Required evidence is declared independently of execution, so deleting a
# comparator cannot leave a green report containing only successful processes.
PROCESS_STAGES = (
    "atomizer",
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


def expected_contract_ids(cases):
    return [
        f"{c['id']}:{suffix}"
        for c in cases
        for suffix in (
            *PROCESS_STAGES,
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
    ] + integrated_extensions.expected_ids(cases)


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
            row["blocked_by"] = [f"{case}:{stage}:{name}" for name in local]
        rows.append(row)


def _compare(
    case, name, rows, dependencies, reference, subject, *, network=False, exact=False
):
    blocked = [r["id"] for r in dependencies if r["status"] != "PASS"]
    if blocked:
        rows.append(
            dict(
                id=f"{case}:{name}",
                stage=name,
                integration_case=case,
                status="NOT_TESTED",
                detail="comparison prerequisite missing",
                blocked_by=blocked,
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


def run_case(case, args, rows, env):
    key = case["id"]
    work = args.report_dir / "cases" / key
    work.mkdir(parents=True)
    source = work / "source.xml"
    source.write_text(sbml_text(case))
    expected = work / "analytic.gdat"
    data, columns = expected_trajectory(case)
    np.savetxt(expected, data, header=" ".join(columns), fmt="%.17g")

    def worker(operation, source, *, upstream=False):
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
    atomizer = stage(
        "atomizer", worker("atomizer", source), required=("model.bngl", "identity.json")
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
    native = stage(
        "native-nf",
        [
            str(args.nfsim_binary),
            "-xml",
            str(work / "bng2/model.xml"),
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
    identity_stages = [atomizer, api, compat, nf, *consumers, *qualifications]
    identities = [r for r in identity_stages if r["status"] == "PASS"]
    if len(identities) == len(identity_stages):
        observed = [
            json.loads((work / r["stage"] / "identity.json").read_text())
            for r in identities
        ]
        consistent = (
            len({(i["package_file"], i["native_extension_sha256"]) for i in observed})
            == 1
        )
        _checks(
            key,
            "worker-identity",
            [
                dict(
                    check="same-installed-build",
                    status="PASS" if consistent else "HARNESS_ERROR",
                    detail="package location and native extension digest across Atomizer/API/compat/NF workers",
                )
            ],
            rows,
            identities,
        )


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
    parser.add_argument("--ensemble-runs", type=int)
    args = parser.parse_args(argv)
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
    if args.boundaries_only:
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
    rows, references = [], {}
    try:
        references = _preflight(args)
        subject_digest = inventory.sha256(args.bng_cpp)
        integrated_extensions.invoke("boundaries", args, rows, env, run_stage)
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
        missing = set(expected_contract_ids(selected)) - {r["id"] for r in rows}
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
    for row in rows:
        case_id = row.get("integration_case")
        row["command"] = (
            replay_base
            + (
                ["--boundaries-only"]
                if row.get("qualification") == "boundaries"
                else (["--case", case_id] if case_id else [])
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
            row["source_locations"] = [
                "tests/validation/integrated_"
                + {
                    "boundaries": "boundaries",
                    "protocol": "protocol",
                    "nf-marginals": "marginals",
                }[row["stage"]]
                + ".py"
            ]
        stage = row["stage"]
        if not row.get("related_issues"):
            if stage == "boundaries":
                issues = [157, 158, 160, 161, 164]
            elif stage == "protocol":
                issues = [138, 139, 140, 141, 143, 171, 172]
            elif stage == "nf-marginals":
                issues = [143, 146, 151, 167]
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
    import yaml

    matrix = yaml.safe_load((ROOT / "provenance/capability-matrix.yml").read_text())
    capabilities = inventory.discover_capabilities(
        ROOT, matrix["validation_capabilities"]
    )
    reporting.attach_coverage(capabilities, rows)
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
                Path(integrated_extensions.__file__),
                ROOT / "tests/validation/integrated_protocol.py",
                ROOT / "tests/validation/integrated_boundaries.py",
                ROOT / "tests/validation/integrated_marginals.py",
                ROOT / "tests/validation/integrated_cases.py",
                ROOT / "provenance/upstreams.lock.yml",
                ROOT / "provenance/capability-matrix.yml",
                ROOT / "tests/validation/contracts.py",
            )
        },
        references=references,
        results=rows,
        capabilities=capabilities,
        issue_coverage=reporting.issue_coverage(capabilities, rows),
        expected_contract_ids=expected_contract_ids(selected),
        failure_clusters=reporting.cluster_failures(rows),
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
    return int(any(r["status"] != "PASS" for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
