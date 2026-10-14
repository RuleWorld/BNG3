"""Integrated campaign over existing validation infrastructure (reporting only)."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

from . import campaign, inventory, reporting

ROOT = Path(__file__).resolve().parents[2]
TIERS = ("smoke", "integration", "full", "performance", "platform")


def _result(identity, stage, status, detail="", **kwargs):
    return dict(id=identity, stage=stage, status=status, detail=detail, **kwargs)


def _json(path, value):
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def evidence_inputs(root):
    paths = campaign.git(
        root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "tests",
        "scripts",
        "models",
        "provenance",
        "formal",
        "benchmarks",
        ".github",
    ).splitlines()
    return {
        p: inventory.sha256(root / p)
        for p in paths
        if (root / p).is_file() and "evidence" not in Path(p).parts
    }


def mapped_suite(suite, capabilities):
    if suite.get("selection") != "capability-mapped":
        return suite
    tests = sorted(
        {
            t
            for c in capabilities
            for t in c.get("tests", [])
            if t.startswith("tests/python/")
        }
    )
    if not tests:
        raise ValueError("capability-mapped suite has no tests")
    return {**suite, "tests": tests}


def _reference(root, name, lock, subject):
    if root is None:
        raise ValueError(f"missing independent {name} checkout")
    if root.resolve().is_relative_to(ROOT):
        raise ValueError("embedded reference cannot qualify independent compatibility")
    identity = campaign.verify_source(root, lock["sources"][name])
    if name == "bionetgen":
        script = root / "bng2/BNG2.pl"
        campaign.reject_shared_engine(subject, script)
        identity.update(
            script=str(script.resolve()), script_sha256=inventory.sha256(script)
        )
        interpreter = shutil.which(os.environ.get("PERL", "perl"))
        if not interpreter:
            raise ValueError("independent BNG2 requires a Perl interpreter")
        identity.update(
            interpreter=str(Path(interpreter).resolve()),
            interpreter_sha256=inventory.sha256(Path(interpreter)),
        )
    return identity


def _suite_command(suite, args, junit):
    if suite["kind"] == "pytest":
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.validation.pytest_evidence",
        ]
        validation_suite = any(
            t.startswith("tests/validation/") for t in suite["tests"]
        )
        if validation_suite:
            command += ["-c", str(ROOT / "tests/validation/pytest.ini")]
        command += [
            *[str(ROOT / t) for t in suite["tests"]],
            "-q",
            "-o",
            "junit_family=legacy",
            f"--junitxml={junit}",
            f"--basetemp={junit.parent / 'pytest-temp'}",
        ]
        if args.bng_cpp and validation_suite:
            command += ["--bng-cpp", str(args.bng_cpp)]
    else:
        command = [
            "ctest",
            "--test-dir",
            str(args.build_dir),
            "--output-on-failure",
            "--timeout",
            str(args.case_timeout),
            "--output-junit",
            str(junit),
        ]
    return command


def _suite(suite, args, directory, references, env):
    name = suite["id"]
    reference = suite.get("reference")
    if name != "harness" and not args.bng_cpp.is_file():
        return [
            _result(
                name,
                "subject-preflight",
                "HARNESS_ERROR",
                "requested subject binary is missing; fallback prohibited",
            )
        ]
    if reference and reference not in references:
        return [
            _result(
                name,
                "reference-preflight",
                "HARNESS_ERROR",
                f"missing verified {reference} oracle",
                reference=reference,
            )
        ]
    if (
        reference == "bionetgen"
        and name != "harness"
        and not references[reference].get("network_binary_sha256")
    ):
        return [
            _result(
                name,
                "reference-preflight",
                "HARNESS_ERROR",
                "finite BNG2 suites require --bng2-network-sha256 for the independently built run_network binary",
            )
        ]
    work = directory / "suites" / name
    junit = work / "junit.xml"
    suite_env = {**env, "BNG3_TEST_EVENT_LOG": str(work / "pytest-events.jsonl")}
    native_commands = {}
    if suite["kind"] == "ctest":
        cache = args.build_dir / "CMakeCache.txt"
        if (
            not cache.is_file()
            or f"CMAKE_HOME_DIRECTORY:INTERNAL={ROOT}" not in cache.read_text()
        ):
            return [
                _result(
                    name,
                    "source-preflight",
                    "HARNESS_ERROR",
                    "native build does not identify this source tree",
                )
            ]
        preflight = campaign.run_command(
            ["ctest", "--test-dir", str(args.build_dir), "--show-only=json-v1"],
            work / "discovery",
            30,
            env=env,
        )
        if preflight["status"] != "PASS":
            return [
                _result(name, "test-discovery", "HARNESS_ERROR", preflight["detail"])
            ]
        registered = json.loads((work / "discovery/stdout.log").read_text())
        native_commands = {
            case["name"]: case.get("command", []) for case in registered["tests"]
        }
        binaries = {command[0] for command in native_commands.values() if command}
        _json(
            work / "native-identities.json",
            {
                "cmake_cache_sha256": inventory.sha256(cache),
                "binaries": {
                    p: inventory.sha256(Path(p))
                    for p in sorted(binaries)
                    if Path(p).is_file()
                },
            },
        )
    receipt = campaign.run_command(
        _suite_command(suite, args, junit),
        work,
        suite["timeout"],
        required=["junit.xml"],
        env=suite_env,
        cwd=ROOT,
    )
    try:
        events = work / "pytest-events.jsonl"
        results = (
            campaign.read_pytest_events(events, name)
            if events.exists()
            else campaign.read_junit(junit, name)
        )
    except ValueError as exc:
        results = []
        if receipt["status"] == "PASS":
            receipt.update(status="HARNESS_ERROR", detail=str(exc))
    if receipt["status"] != "PASS":
        results.append(
            _result(
                name + ":process",
                "test-execution",
                receipt["status"],
                receipt["detail"]
                or "test process failed; inspect stdout.log and stderr.log",
            )
        )
    if reference and any(r["status"] == "NOT_TESTED" for r in results):
        results.append(
            _result(
                name + ":incomplete",
                "test-execution",
                "HARNESS_ERROR",
                "selected compatibility cases were skipped or xfailed; see individual reasons",
            )
        )
    # Skips, xfails, collection errors and incomplete reports cannot qualify a suite.
    for result in results:
        if result.get("name") in native_commands:
            command = native_commands[result["name"]]
            result["command"] = command
            if command:
                sources = list((ROOT / "tests").rglob(Path(command[0]).stem + ".cpp"))
                if len(sources) == 1:
                    result["test_file"] = sources[0].relative_to(ROOT).as_posix()
        test_file = result.get("test_file")
        if test_file:
            for base in (ROOT, ROOT / "tests/validation"):
                candidate = (base / test_file).resolve()
                if candidate.is_file() and candidate.is_relative_to(ROOT):
                    result["test_file"] = candidate.relative_to(ROOT).as_posix()
                    break
        result.update(
            reference=reference,
            question=suite["question"],
            receipt=str((work / "command.json").resolve()),
        )
    return results


def _models(args, selection):
    from . import corpus

    names = (
        args.models
        or selection["tiers"][args.corpus_tier or ("p" if "full" in args.tier else "s")]
    )
    records = {r["id"]: r for r in selection["records"]}
    selected = []
    for name in names:
        if name not in records:
            raise ValueError(f"model {name!r} is outside the locked selection")
        record = records[name]
        source = ROOT / record["path"]
        campaign.verify_digest(source, record["sha256"])
        resolved = corpus.resolve(name)
        if resolved is None or resolved.resolve() != source.resolve():
            raise ValueError(f"ambiguous locked model path: {name}")
        if (
            int(hashlib.sha256(name.encode()).hexdigest(), 16) % args.shard_count
            == args.shard_index
        ):
            selected.append((name, source))
    return selected


def _model(name, source, args, directory, reference, env):
    from scripts.cross_validate import _stage_model
    from .compare import compare_net, parse_net

    work = directory / "models" / name
    source_root = source.parent
    staged = _stage_model(source, source_root, work / "input")
    text = staged.read_text().replace(
        "generate_network({overwrite=>1})",
        f"generate_network({{overwrite=>1,max_iter=>{args.network_iterations},max_agg=>{args.max_aggregate}}})",
    )
    staged.write_text(text)
    original_dir = work / "original"
    shutil.copytree(staged.parent, original_dir)
    original = original_dir / source.name
    shutil.copy2(source, original)
    check = campaign.run_command(
        [str(args.bng_cpp), "--check", str(original)],
        work / "parse",
        args.case_timeout,
        env=env,
    )
    rows = [
        _result(
            name + ":parse",
            "parse",
            check["status"],
            check["detail"],
            model=name,
            capabilities=["parser.grammar"],
            receipt=str(work / "parse/command.json"),
        )
    ]
    if check["status"] != "PASS":
        return rows
    if reference is None:
        rows.append(
            _result(
                name + ":network",
                "bounded-network",
                "NOT_TESTED",
                "no verified BNG2 reference requested",
                model=name,
                reference="bionetgen",
            )
        )
        return rows
    common = dict(
        model=name,
        reference="bionetgen",
        question="legacy-agreement",
        capabilities=[
            "network.expansion",
            "network.rule-multiplicity",
            "network.observables",
        ],
    )
    for label in ("reference", "subject"):
        target = work / label
        target.mkdir(parents=True)
        for item in staged.parent.iterdir():
            if item.is_dir():
                shutil.copytree(item, target / item.name)
            else:
                shutil.copy2(item, target / item.name)
        model = target / staged.name
        if label == "reference":
            command = [
                env.get("PERL", "perl"),
                reference["script"],
                "--outdir",
                str(target.resolve()),
                str(model.resolve()),
            ]
        else:
            command = [str(args.bng_cpp), str(model.resolve())]
        receipt = campaign.run_command(
            command, target, args.case_timeout, required=[source.stem + ".net"], env=env
        )
        if receipt["status"] != "PASS":
            rows.append(
                _result(
                    name + ":network",
                    "reference-network" if label == "reference" else "bounded-network",
                    (
                        "HARNESS_ERROR"
                        if label == "reference" and receipt["status"] == "FAIL"
                        else receipt["status"]
                    ),
                    receipt["detail"] or f"{label} execution failed; inspect logs",
                    receipt=str(target / "command.json"),
                    **common,
                )
            )
            return rows
    ref = parse_net(work / "reference" / (source.stem + ".net"))
    test = parse_net(work / "subject" / (source.stem + ".net"))
    if ref is None or test is None:
        rows.append(
            _result(
                name + ":network",
                "bounded-network",
                "HARNESS_ERROR",
                "malformed .net output",
                **common,
            )
        )
    else:
        diff = compare_net(ref, test, compare_initial_amounts=True)
        if diff.initial_amounts_changed:
            common["capabilities"] += ["interface.cli-actions", "export.net"]
            common["first_observed_divergence"] = "network.initial_amounts"
            common["diagnosis"] = {
                "confidence": "observed-field",
                "confirmed_root_cause": None,
                "hypotheses": [
                    "action state update",
                    "network writer state serialization",
                ],
            }
        common["network_counts"] = {
            "reference": [ref.n_species, ref.n_reactions],
            "subject": [test.n_species, test.n_reactions],
        }
        common["initial_amounts_changed"] = sorted(diff.initial_amounts_changed)
        rows.append(
            _result(
                name + ":network",
                "bounded-network",
                "PASS" if diff.ok else "FAIL",
                diff.summary(),
                **common,
            )
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", action="append", choices=TIERS, default=[])
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--plan", type=Path, default=ROOT / "provenance/validation-plan.json"
    )
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--bng-cpp",
        type=Path,
        default=ROOT
        / ("build/cpp/bng_cpp.exe" if os.name == "nt" else "build/cpp/bng_cpp"),
    )
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--bng2-root", type=Path)
    parser.add_argument("--bng2-network-sha256")
    parser.add_argument("--nfsim-root", type=Path)
    parser.add_argument("--nfsim-binary", type=Path)
    parser.add_argument("--nfsim-sha256")
    parser.add_argument("--sbml-suite", type=Path)
    parser.add_argument("--pybionetgen-root", type=Path)
    parser.add_argument("--rulehub-root", type=Path)
    parser.add_argument(
        "--package-mode",
        choices=("source", "installed"),
        default=os.environ.get("BNG3_PYTHON_TEST_MODE", "source"),
    )
    parser.add_argument("--corpus-tier", choices=("s", "p", "nf", "expr", "x", "b"))
    parser.add_argument("--suite", action="append", default=[])
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--case-timeout", type=float, default=30)
    parser.add_argument("--network-iterations", type=int, default=4)
    parser.add_argument("--max-aggregate", type=int, default=8)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="preserve unsuccessful results but return zero (new CI coverage only)",
    )
    args = parser.parse_args(argv)
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("invalid shard index/count")
    if (
        args.case_timeout <= 0
        or args.network_iterations <= 0
        or args.max_aggregate <= 0
    ):
        parser.error("budgets must be positive")
    directory = args.report_dir.resolve()
    if directory.exists() and any(directory.iterdir()):
        parser.error("report directory must be empty; stale outputs cannot be evidence")
    directory.mkdir(parents=True, exist_ok=True)
    args.bng_cpp = args.bng_cpp.resolve()
    args.plan = args.plan.resolve()
    args.build_dir = args.build_dir.resolve()
    plan = json.loads(args.plan.read_text())
    matrix_path = ROOT / plan.get(
        "capability_inventory", "provenance/capability-matrix.yml"
    )
    matrix = yaml.safe_load(matrix_path.read_text())
    plan["capabilities"] = matrix["validation_capabilities"]
    errors = inventory.validate_plan(ROOT, plan)
    if errors:
        parser.error("invalid capability plan: " + "; ".join(errors))
    capabilities = inventory.discover_capabilities(ROOT, plan["capabilities"])
    selection = json.loads((ROOT / "provenance/corpus/selection.json").read_text())
    lock = json.loads((ROOT / "provenance/upstreams.lock.yml").read_text())
    env = os.environ.copy()
    env["BNG3_CI_STRICT_ORACLES"] = "1"
    env.pop("BIONETGEN_USE_PERL", None)
    env.setdefault("MPLBACKEND", "Agg")
    env["MPLCONFIGDIR"] = str(directory / "cache/matplotlib")
    source_snapshot = {
        "revision": campaign.git(ROOT, "rev-parse", "HEAD"),
        "dirty": bool(campaign.git(ROOT, "status", "--porcelain")),
        "diff_sha256": hashlib.sha256(
            campaign.git(ROOT, "diff", "HEAD").encode()
        ).hexdigest(),
    }
    evidence_snapshot = evidence_inputs(ROOT)
    subject_digest = inventory.sha256(args.bng_cpp) if args.bng_cpp.is_file() else None
    references, results = {}, []
    if not args.inventory_only:
        args.tier = args.tier or ["smoke"]
        performance_only = set(args.tier) == {"performance"} and not args.suite
        if not args.bng_cpp.is_file() and not performance_only:
            results.append(
                _result(
                    "subject",
                    "subject-preflight",
                    "HARNESS_ERROR",
                    "requested subject binary is missing; fallback prohibited",
                )
            )
        for name, root in (
            ("bionetgen", args.bng2_root),
            ("nfsim", args.nfsim_root),
            ("pybionetgen", args.pybionetgen_root),
            ("rulehub", args.rulehub_root),
        ):
            if root is None:
                continue
            try:
                identity = _reference(root, name, lock, args.bng_cpp)
                if name == "nfsim":
                    if not args.nfsim_binary or not args.nfsim_sha256:
                        raise ValueError(
                            "NFsim requires an independently built binary and expected SHA-256"
                        )
                    campaign.reject_shared_engine(
                        args.bng_cpp, args.nfsim_binary, implementation_root=ROOT
                    )
                    campaign.verify_digest(args.nfsim_binary, args.nfsim_sha256)
                    identity.update(
                        binary=str(args.nfsim_binary.resolve()),
                        binary_sha256=inventory.sha256(args.nfsim_binary),
                    )
                    env["NFSIM_BIN"] = identity["binary"]
                elif name == "bionetgen":
                    env.update(
                        BNG2_PERL=identity["script"],
                        BNGPATH=str(Path(identity["script"]).parent),
                        PERL=identity["interpreter"],
                    )
                    if args.bng2_network_sha256:
                        binary = Path(identity["script"]).parent / "bin/run_network"
                        campaign.reject_shared_engine(args.bng_cpp, binary)
                        campaign.verify_digest(binary, args.bng2_network_sha256)
                        identity.update(
                            network_binary=str(binary),
                            network_binary_sha256=inventory.sha256(binary),
                        )
                references[name] = identity
                results.append(
                    _result(
                        name + ":identity",
                        "reference-preflight",
                        "PASS",
                        "locked source identity verified",
                        reference=name,
                    )
                )
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
                results.append(
                    _result(
                        name + ":identity",
                        "reference-preflight",
                        "HARNESS_ERROR",
                        str(exc),
                        reference=name,
                    )
                )
        if set(args.suite) - {s["id"] for s in plan["suites"]}:
            parser.error("unknown suite requested")
        selected_suites = [
            s
            for s in plan["suites"]
            if (args.suite and s["id"] in args.suite)
            or (not args.suite and set(args.tier) & set(s["tiers"]))
        ]
        selected_suites = [
            mapped_suite(s, plan["capabilities"]) for s in selected_suites
        ]
        needs_api = (
            any(s["kind"] == "pytest" and s["id"] != "harness" for s in selected_suites)
            or "performance" in args.tier
            or "full" in args.tier
        )
        api_identity = None
        if needs_api and (args.bng_cpp.is_file() or performance_only):
            env["BNG3_PYTHON_TEST_MODE"] = args.package_mode
            # Existing benchmark/SBML scripts import normally; select the same
            # source paths whose identity the probe verifies.
            if args.package_mode == "source":
                env["PYTHONPATH"] = os.pathsep.join(
                    [str(ROOT), str(ROOT / "python"), str(args.build_dir / "cpp")]
                )
            probe = directory / "python-identity"
            receipt = campaign.run_command(
                [
                    sys.executable,
                    "-m",
                    "tests.validation.identity_probe",
                    str(probe / "identity.json"),
                ],
                probe,
                30,
                required=["identity.json"],
                env=env,
                cwd=ROOT,
            )
            if receipt["status"] == "PASS":
                api_identity = json.loads((probe / "identity.json").read_text())
            else:
                results.append(
                    _result(
                        "python-identity",
                        "package-preflight",
                        "HARNESS_ERROR",
                        receipt["detail"],
                    )
                )
        for suite in selected_suites:
            if (args.suite and suite["id"] in args.suite) or (
                not args.suite and set(args.tier) & set(suite["tiers"])
            ):
                print("Running suite:", suite["id"], flush=True)
                if (
                    suite["kind"] == "pytest"
                    and suite["id"] != "harness"
                    and api_identity is None
                    and (not suite.get("reference") or suite["reference"] in references)
                ):
                    results.append(
                        _result(
                            suite["id"],
                            "package-preflight",
                            "HARNESS_ERROR",
                            "no verified native Python package",
                        )
                    )
                    continue
                results.extend(_suite(suite, args, directory, references, env))
        if "performance" in args.tier or ("full" in args.tier and not args.suite):
            from .external_lanes import run_existing_lane

            for lane in (["performance"] if "performance" in args.tier else []) + (
                ["sbml"] if "full" in args.tier and not args.suite else []
            ):
                if api_identity is None:
                    results.append(
                        _result(
                            lane,
                            "package-preflight",
                            "HARNESS_ERROR",
                            "no verified native Python package",
                        )
                    )
                else:
                    results.extend(
                        run_existing_lane(
                            lane, ROOT, directory, env, sbml_suite=args.sbml_suite
                        )
                    )
        if "performance" not in args.tier or len(args.tier) > 1:
            try:
                for name, source in _models(args, selection):
                    print("Checking model:", name, flush=True)
                    results.extend(
                        _model(
                            name,
                            source,
                            args,
                            directory,
                            references.get("bionetgen"),
                            env,
                        )
                    )
            except (ValueError, OSError, KeyError) as exc:
                results.append(
                    _result("corpus", "selection", "HARNESS_ERROR", str(exc))
                )
    reporting.attach_coverage(capabilities, results)
    source = source_snapshot
    if subject_digest:
        try:
            campaign.verify_digest(args.bng_cpp, subject_digest)
        except (ValueError, OSError) as exc:
            results.append(
                _result(
                    "subject-mutated", "harness-integrity", "HARNESS_ERROR", str(exc)
                )
            )
    evidence_after = evidence_inputs(ROOT)
    input_changes = sorted(
        p
        for p in evidence_snapshot.keys() | evidence_after.keys()
        if evidence_snapshot.get(p) != evidence_after.get(p)
    )
    if input_changes:
        results.append(
            _result(
                "input-mutation",
                "harness-integrity",
                "HARNESS_ERROR",
                "recorded validation inputs changed during execution: "
                + ", ".join(input_changes),
            )
        )
    inputs = {
        str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): inventory.sha256(p)
        for p in [
            args.plan,
            ROOT / "provenance/upstreams.lock.yml",
            ROOT / "provenance/corpus/selection.json",
            ROOT / "provenance/capability-matrix.yml",
        ]
    }
    config = {
        "environment": {
            key: env.get(key)
            for key in (
                "BNG3_PYTHON_TEST_MODE",
                "BIONETGEN_FINITE_BACKEND",
                "DYLD_LIBRARY_PATH",
                "LD_LIBRARY_PATH",
                "BNG_ENSEMBLE_WORKERS",
                "OMP_NUM_THREADS",
                "MPLBACKEND",
            )
        },
        "tiers": args.tier,
        "models": args.models,
        "suites": args.suite,
        "package_mode": args.package_mode,
        "corpus_tier": args.corpus_tier,
        "case_timeout": args.case_timeout,
        "network_iterations": args.network_iterations,
        "max_aggregate": args.max_aggregate,
        "shard": [args.shard_index, args.shard_count],
    }
    environment = {
        "system": platform.platform(),
        "python": sys.version,
        "executable": sys.executable,
        "dependencies": {
            d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
        },
    }
    evidence = evidence_snapshot
    comparison_key = hashlib.sha256(
        json.dumps(
            {
                "inputs": inputs,
                "evidence": evidence,
                "config": config,
                "references": references,
                "environment": environment,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "input_changes_during_run": input_changes,
        "execution_policy": {
            "report_only": args.report_only,
            "qualification": "unqualified; test evidence does not approve support policy or release gates",
        },
        "platform": environment,
        "evidence_inputs": evidence,
        "configuration": config,
        "inputs": inputs,
        "comparison_key": comparison_key,
        "references": references,
        "subject": {
            "binary": str(args.bng_cpp),
            "sha256": subject_digest,
        },
        "capabilities": capabilities,
        "corpus": inventory.discover_models(ROOT),
        "results": results,
        "source_policy_rows": matrix["rows"],
        "reconciliation": {
            p.stem: json.loads(p.read_text())
            for p in sorted((ROOT / "provenance/reconciliation").glob("*.yml"))
        },
        "external_corpus": {
            name: {
                "reference": identity,
                "models": inventory.discover_models(
                    Path(identity["path"]),
                    roots=(
                        "models",
                        "tests",
                        "examples",
                        "bng2/Models2",
                        "bng2/Validate",
                    ),
                ),
            }
            for name, identity in references.items()
        },
        "existing_lanes": plan["existing_lanes"],
        "failure_clusters": reporting.cluster_failures(results),
    }
    if not args.inventory_only:
        report["python_identity"] = api_identity
    previous = json.loads(args.baseline.read_text()) if args.baseline else None
    report["history"] = reporting.history(report, previous)
    _json(directory / "report.json", report)
    _json(
        directory / "inventory.json",
        {"schema_version": 1, "source": source, "capabilities": capabilities},
    )
    (directory / "report.md").write_text(reporting.markdown(report))
    _json(
        directory / "artifacts.json",
        [
            {"path": str(p.relative_to(directory)), "sha256": inventory.sha256(p)}
            for p in sorted(directory.rglob("*"))
            if p.is_file()
        ],
    )
    print(
        "Outcomes:",
        ", ".join(
            f"{status}={sum(r['status'] == status for r in results)}"
            for status in campaign.STATUSES
        ),
        flush=True,
    )
    print("Report:", directory / "report.md", flush=True)
    return int(
        any(r["status"] in reporting.BAD for r in results) and not args.report_only
    )


if __name__ == "__main__":
    raise SystemExit(main())
