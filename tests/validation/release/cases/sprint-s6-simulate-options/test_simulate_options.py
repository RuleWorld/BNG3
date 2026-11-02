"""Independent, pinned-BNG2 cases for the selected action.simulate options."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.validation import compare, runner
from tests.validation.oracle_perl import _is_locked_bng2
from tests.validation.strict import require_oracle
from tests.validation.test_export_formats import _locked_bng2_script

CASE_DIR = Path(__file__).parent
MODEL_TEMPLATE = (CASE_DIR / "conversion_model.bngl").read_text(encoding="utf-8")
OPTIONS = (
    "action.simulate.t_start",
    "action.simulate.t_end",
    "action.simulate.n_steps",
    "action.simulate.sample_times",
    "action.simulate.continue",
    "action.simulate.method",
    "action.simulate.atol",
    "action.simulate.rtol",
)
ABSOLUTE_ERROR_BOUND = 1e-6
TIME_ABSOLUTE_ERROR_BOUND = 1e-12


@pytest.fixture(scope="module")
def locked_bng2() -> Path:
    script = _locked_bng2_script()
    require_oracle(
        script is not None and _is_locked_bng2(script),
        "the accepted pinned BNG2 checkout is required; no cached result substitutes",
    )
    require_oracle(
        shutil.which(os.environ.get("PERL", "perl")) is not None,
        "Perl is required to execute the pinned BNG2 oracle",
    )
    assert script is not None
    contract = json.loads((CASE_DIR / "contract.json").read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(
        (script.parent / "Perl2/BNGAction.pm").read_bytes()
    ).hexdigest()
    require_oracle(
        source_hash == contract["source"]["sha256"],
        "pinned BNG2 BNGAction.pm differs from the source used to author this contract",
    )
    return script


def _action(arguments: str) -> str:
    return f"simulate({{{arguments}}})"


def _scenarios(row: str) -> list[dict[str, object]]:
    base = 'method=>"ode",t_start=>0,t_end=>1,n_steps=>4'
    common = {
        "default": base,
        "explicit": base,
        "invalid": base,
        "interaction": base,
    }
    if row.endswith("t_start"):
        common.update(
            default='method=>"ode",t_end=>1,n_steps=>4',
            explicit='method=>"ode",t_start=>0.5,t_end=>1.5,n_steps=>4',
            invalid='method=>"ode",t_start=>2,t_end=>1,n_steps=>4',
            interaction='method=>"ode",t_start=>0.5,t_end=>1.5,n_steps=>4',
        )
    elif row.endswith("t_end"):
        common.update(
            default='method=>"ode",t_start=>0,sample_times=>[0,0.5,1]',
            explicit='method=>"ode",t_start=>0,t_end=>1.5,n_steps=>3',
            invalid='method=>"ode",t_start=>1,t_end=>0,n_steps=>4',
            interaction='method=>"ode",t_start=>0,sample_times=>[0,0.4,0.8],t_end=>1',
        )
    elif row.endswith("n_steps"):
        common.update(
            default='method=>"ode",t_start=>0,t_end=>1',
            explicit='method=>"ode",t_start=>0,t_end=>1,n_steps=>4',
            invalid='method=>"ode",t_start=>0,t_end=>1,n_steps=>0',
            interaction='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,sample_times=>[0,0.25,0.75,1]',
        )
    elif row.endswith("sample_times"):
        common.update(
            default='method=>"ode",t_start=>0,t_end=>1,n_steps=>4',
            explicit='method=>"ode",t_start=>0,sample_times=>[0,0.25,0.75]',
            invalid='method=>"ode",t_start=>0,sample_times=>[0,1]',
            interaction='method=>"ode",t_start=>0,sample_times=>[0,0.4,0.8],t_end=>1',
        )
    elif row.endswith("continue"):
        common.update(
            default='method=>"ode",t_start=>0,t_end=>0.5,n_steps=>2',
            explicit=(
                'simulate({method=>"ode",t_start=>0,t_end=>0.5,n_steps=>2})\n'
                'simulate({method=>"ode",t_start=>0.5,t_end=>1,n_steps=>2,continue=>1})'
            ),
            invalid=(
                'simulate({method=>"ode",t_start=>0,t_end=>0.5,n_steps=>2})\n'
                'simulate({method=>"ode",t_start=>0.75,t_end=>1,n_steps=>1,continue=>1})'
            ),
            interaction=(
                'simulate({method=>"ode",t_start=>0,t_end=>0.5,n_steps=>2})\n'
                'simulate({method=>"ode",t_end=>1,n_steps=>2,continue=>1})'
            ),
        )
    elif row.endswith("method"):
        common.update(
            default="t_start=>0,t_end=>1,n_steps=>4",
            explicit='method=>"ode",t_start=>0,t_end=>1,n_steps=>4',
            invalid='method=>"unknown",t_start=>0,t_end=>1,n_steps=>4',
            interaction='method=>"ssa",t_start=>0,t_end=>1,n_steps=>4,seed=>17,atol=>1e-12,rtol=>1e-10',
        )
    elif row.endswith("atol"):
        common.update(
            default='method=>"ode",t_start=>0,t_end=>1,n_steps=>4',
            explicit='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,atol=>1e-12',
            invalid='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,atol=>-1',
            interaction='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,atol=>1e-12,rtol=>1e-10',
        )
    elif row.endswith("rtol"):
        common.update(
            default='method=>"ode",t_start=>0,t_end=>1,n_steps=>4',
            explicit='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,rtol=>1e-10',
            invalid='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,rtol=>-1',
            interaction='method=>"ode",t_start=>0,t_end=>1,n_steps=>4,atol=>1e-12,rtol=>1e-10',
        )
    else:
        raise AssertionError(row)

    result = []
    for name, arguments in common.items():
        actions = arguments if "\nsimulate(" in arguments else _action(arguments)
        result.append(
            {
                "name": name,
                "actions": actions,
                "expected_rejection": name == "invalid"
                or (row.endswith("method") and name == "default"),
            }
        )
    return result


def _run_bng2(script: Path, source: Path, work_dir: Path) -> dict[str, object]:
    work_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["BNGPATH"] = str(script.parent)
    try:
        process = subprocess.run(
            [
                os.environ.get("PERL", "perl"),
                str(script),
                "--outdir",
                str(work_dir),
                "--no-nfsim",
                str(source),
            ],
            cwd=source.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        transcript = (exc.stdout or b"") + (exc.stderr or b"")
        if isinstance(transcript, bytes):
            transcript = transcript.decode(errors="replace")
        return _outcome(124, None, transcript + "\nTIMEOUT after 60s")
    output = work_dir / f"{source.stem}.gdat"
    if not output.is_file():
        candidates = sorted(work_dir.glob("*.gdat"))
        output = candidates[0] if len(candidates) == 1 else Path()
    return _outcome(process.returncode, output, process.stdout + process.stderr)


def _run_bng3(bng_cpp: Path, source: Path, work_dir: Path) -> dict[str, object]:
    _, output, error = runner.run_cli_path(bng_cpp, source, work_dir, timeout=60)
    if error == "timeout after 60s":
        return _outcome(124, None, error + "\nTIMEOUT after 60s")
    return _outcome(0 if output is not None else 1, output, error or "")


def _outcome(
    return_code: int, output: Path | None, transcript: str
) -> dict[str, object]:
    present = output is not None and output.is_file()
    timed_out = return_code == 124 or "TIMEOUT after 60s" in transcript
    return {
        "return_code": return_code,
        "output": str(output) if present else None,
        "output_sha256": (
            hashlib.sha256(output.read_bytes()).hexdigest() if present else None
        ),
        "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest(),
        "diagnostic_excerpt": transcript[-1000:],
        "transcript": transcript,
        "rejected": not present or return_code != 0,
        "execution_status": (
            "TIMEOUT"
            if timed_out
            else ("PRODUCED" if present and return_code == 0 else "REJECTED")
        ),
        "trajectory": None,
    }


def _read_trajectory(outcome: dict[str, object]) -> tuple[np.ndarray, list[str]] | None:
    path = outcome["output"]
    if not path:
        return None
    data, columns = compare.parse_gdat(Path(path))
    if data is None or columns is None:
        return None
    outcome["trajectory"] = {
        "shape": list(data.shape),
        "columns": columns,
        "values": data.tolist(),
    }
    return data, columns


def _expected_times(row: str, scenario: str) -> np.ndarray | None:
    if scenario == "invalid" or (row.endswith("method") and scenario == "default"):
        return None
    if row.endswith("t_start") and scenario in {"explicit", "interaction"}:
        return np.linspace(0.5, 1.5, 5)
    if row.endswith("t_end") and scenario == "explicit":
        return np.linspace(0, 1.5, 4)
    if row.endswith("t_end") and scenario == "interaction":
        return np.array([0, 0.4, 0.8, 1])
    if row.endswith("t_end") and scenario == "default":
        return np.array([0, 0.5, 1])
    if row.endswith("n_steps") and scenario == "default":
        return np.array([0, 1])
    if row.endswith("sample_times") and scenario == "explicit":
        return np.array([0, 0.25, 0.75])
    if row.endswith("sample_times") and scenario == "interaction":
        return np.array([0, 0.4, 0.8, 1])
    if row.endswith("continue") and scenario in {"explicit", "interaction"}:
        return np.linspace(0, 1, 5)
    if row.endswith("continue") and scenario == "default":
        return np.array([0, 0.25, 0.5])
    if row.endswith("method") and scenario == "interaction":
        return np.linspace(0, 1, 5)
    return np.linspace(0, 1, 5)


def _verify_law(
    data: np.ndarray, columns: list[str], row: str, scenario: str
) -> list[str]:
    failures: list[str] = []
    if columns != ["time", "A_count", "B_count"]:
        failures.append(f"unexpected observable columns: {columns}")
        return failures
    expected_times = _expected_times(row, scenario)
    if expected_times is None:
        failures.append("no independent schedule declared for successful output")
        return failures
    if data.shape[0] != len(expected_times) or not np.allclose(
        data[:, 0], expected_times, rtol=0, atol=TIME_ABSOLUTE_ERROR_BOUND
    ):
        failures.append(
            f"schedule differs: got {data[:, 0].tolist()}, expected {expected_times.tolist()}"
        )
        return failures
    if row.endswith("method") and scenario == "interaction":
        values = data[:, 1:]
        if (
            not np.all(values == np.floor(values))
            or not np.all(values >= 0)
            or not np.allclose(values.sum(axis=1), 10)
        ):
            failures.append(
                "SSA populations must remain nonnegative integers with conserved A+B=10"
            )
        return failures
    relative_start = (
        0.5
        if row.endswith("t_start") and scenario in {"explicit", "interaction"}
        else 0.0
    )
    expected_a = 10.0 * np.exp(-0.4 * (data[:, 0] - relative_start))
    expected_b = 10.0 - expected_a
    if not np.all(np.abs(data[:, 1] - expected_a) <= ABSOLUTE_ERROR_BOUND):
        failures.append(
            "A_count exceeds the fixed independent analytic absolute-error bound"
        )
    if not np.all(np.abs(data[:, 2] - expected_b) <= ABSOLUTE_ERROR_BOUND):
        failures.append(
            "B_count exceeds the fixed independent analytic absolute-error bound"
        )
    return failures


def _receipt(
    row: str, scenarios: list[dict[str, object]], bng_cpp: Path, bng2: Path
) -> dict[str, object]:
    source_root = Path(__file__).resolve().parents[5]
    from scripts.ci.oracle_sources import load_lock, load_oracle_source

    bng2_info = load_oracle_source(load_lock(), "bionetgen")
    receipt: dict[str, object] = {
        "row_id": row,
        "selector": f"tests/validation/release/cases/sprint-s6-simulate-options/test_simulate_options.py::test_simulate_option_contract[{row}]",
        "source": {
            "revision": bng2_info["revision"],
            "path": "bng2/Perl2/BNGAction.pm",
            "sha256": hashlib.sha256(
                (bng2.parent / "Perl2/BNGAction.pm").read_bytes()
            ).hexdigest(),
        },
        "product": {
            "revision": subprocess.run(
                ["git", "-C", str(source_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
            "bng_cpp_sha256": hashlib.sha256(bng_cpp.read_bytes()).hexdigest(),
        },
        "oracle": "pinned BNG2 plus the analytic first-order conversion law; SSA scope is invariant-only",
        "scenarios": [],
        "scope": "default, explicit, invalid, and one row-relevant interaction; only the admitted ODE/SSA pair is attempted",
    }
    failures = []
    for scenario in scenarios:
        name = str(scenario["name"])
        source_path = (
            Path(os.environ.get("S6_CASE_TMP", "/tmp"))
            / f"s6_{row.split('.')[-1]}_{name}.bngl"
        )
        actions = str(scenario["actions"])
        rendered = MODEL_TEMPLATE.replace("{{ACTIONS}}", actions)
        source_path.write_text(rendered, encoding="utf-8")
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        reference = _run_bng2(
            bng2, source_path, source_path.parent / f"{source_path.stem}_bng2"
        )
        product = _run_bng3(
            bng_cpp, source_path, source_path.parent / f"{source_path.stem}_bng3"
        )
        reference_trajectory = _read_trajectory(reference)
        product_trajectory = _read_trajectory(product)
        expected_rejection = bool(scenario["expected_rejection"])
        item_failures: list[str] = []
        nonincreasing_time = row.endswith(("t_start", "t_end")) and name == "invalid"
        timed_out = (
            reference["execution_status"] == "TIMEOUT"
            or product["execution_status"] == "TIMEOUT"
        )
        if timed_out:
            item_failures.append(
                "an engine timed out; this is pending evidence, not a semantic refusal"
            )
        elif nonincreasing_time:
            # BNG2 warns and does not integrate when t_end <= t_start. BNG3
            # may refuse earlier; either way neither consumer may advance the
            # authored state through a reversed/empty interval.
            for engine_name, outcome, trajectory in (
                ("BNG2", reference, reference_trajectory),
                ("BNG3", product, product_trajectory),
            ):
                if trajectory is None:
                    if not outcome["rejected"]:
                        item_failures.append(
                            f"{engine_name} produced no output without a refusal"
                        )
                    continue
                data, columns = trajectory
                if columns != ["time", "A_count", "B_count"] or data.shape[0] > 1:
                    item_failures.append(
                        f"{engine_name} advanced a nonincreasing time interval"
                    )
                elif not np.allclose(data[0, 1:], [10.0, 0.0], rtol=0, atol=1e-12):
                    item_failures.append(
                        f"{engine_name} changed the initial observables without advancing time"
                    )
        elif expected_rejection:
            if not reference["rejected"]:
                item_failures.append(
                    "pinned BNG2 accepted the declared invalid or required-argument case"
                )
            if not product["rejected"]:
                item_failures.append(
                    "BNG3 produced a trajectory for a declared invalid or required-argument case"
                )
        elif reference_trajectory is None:
            item_failures.append(
                "pinned BNG2 did not produce a parseable .gdat for valid input"
            )
        elif product_trajectory is None:
            item_failures.append(
                "BNG3 did not produce a parseable .gdat for valid required input"
            )
        else:
            ref_data, ref_columns = reference_trajectory
            product_data, product_columns = product_trajectory
            if ref_columns != product_columns or ref_data.shape != product_data.shape:
                item_failures.append(
                    "BNG2/BNG3 returned different columns or trajectory shapes"
                )
            else:
                expected_times = _expected_times(row, name)
                if expected_times is not None:
                    for engine_name, data, columns in (
                        ("BNG2", ref_data, ref_columns),
                        ("BNG3", product_data, product_columns),
                    ):
                        item_failures.extend(
                            f"{engine_name}: {failure}"
                            for failure in _verify_law(data, columns, row, name)
                        )
                    if not np.allclose(
                        ref_data[:, 0],
                        product_data[:, 0],
                        rtol=0,
                        atol=TIME_ABSOLUTE_ERROR_BOUND,
                    ):
                        item_failures.append("BNG2 and BNG3 output schedules differ")
        item = {
            "name": name,
            "source_sha256": source_hash,
            "expected_rejection": expected_rejection,
            "bng2": reference,
            "bng3": product,
            "status": (
                "TIMEOUT"
                if timed_out
                else (
                    "PASS"
                    if not item_failures
                    else (
                        "REQUIRED_BUT_UNSUPPORTED"
                        if not product_trajectory and not expected_rejection
                        else "SEMANTIC_FAILURE"
                    )
                )
            ),
            "failures": item_failures,
        }
        receipt["scenarios"].append(item)
        failures.extend(f"{name}: {failure}" for failure in item_failures)

    receipt["status"] = (
        "TIMEOUT"
        if any(scenario["status"] == "TIMEOUT" for scenario in receipt["scenarios"])
        else ("PASS" if not failures else "SEMANTIC_FAILURE")
    )
    receipt["failures"] = failures
    report_dir = Path(
        os.environ.get(
            "S6_RECEIPT_DIR",
            "/tmp/bng3-sprint-20261101-coordination/outbox/S6/local-receipts",
        )
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{row}.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


@pytest.mark.parametrize("row", OPTIONS)
def test_simulate_option_contract(row, bng_cpp, locked_bng2, tmp_path):
    os.environ["S6_CASE_TMP"] = str(tmp_path)
    scenarios = _scenarios(row)
    receipt = _receipt(row, scenarios, bng_cpp, locked_bng2)
    assert receipt["status"] == "PASS", (
        f"{row}: {receipt['status']}; {receipt['failures']}; "
        "see the row receipt under S6_RECEIPT_DIR"
    )


def test_inventory_consumers_preserve_all_rows_and_legacy_metadata():
    root = Path(__file__).resolve().parents[5]
    matrix = json.loads((root / "provenance/capability-matrix.yml").read_text())
    rows = matrix["rows"]
    row_ids = sorted(row["id"] for row in rows)
    assert len(rows) == 994
    assert len(set(row_ids)) == 994
    assert hashlib.sha256(
        json.dumps(row_ids, separators=(",", ":")).encode()
    ).hexdigest() == (
        "acd4ed676970116c4c3055de3fb3bf1dfd3b6b55678040d49023ff3d21828669"
    )

    legacy = matrix["validation_capabilities"]
    assert len(legacy) == 85
    assert (
        hashlib.sha256(
            json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == "8f7b31e5205b96912c41b58a81eac83dd0799d27b6f10d58988915dc6a3ae351"
    )

    selected = set(OPTIONS)
    untouched = [
        row for row in rows if row["id"] not in selected and row.get("issue") != 150
    ]
    assert len(untouched) == 978
    assert (
        hashlib.sha256(
            json.dumps(untouched, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        == "3d5e66473d80873c801caa7531e61b076cc2b11e7a0a877781e1eeed0522d55e"
    )
    selected_rows = {row["id"]: row for row in rows if row["id"] in selected}
    assert set(selected_rows) == selected
    selectors = [row["check"] for row in selected_rows.values()]
    assert len(set(selectors)) == 8
    assert all(
        f"release-capability[{row_id}]" in selected_rows[row_id]["check"]
        for row_id in selected
    )
    assert all(selected_rows[row_id]["status"] == "missing" for row_id in selected)

    markdown_rows = {}
    for line in (root / "docs/CAPABILITY_UNION_INVENTORY.md").read_text().splitlines():
        if (
            not line.startswith("| ")
            or line.startswith("| ID |")
            or line.startswith("| ---")
        ):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells:
            markdown_rows[cells[0]] = cells
    assert set(markdown_rows) == set(row_ids)
    assert len(markdown_rows) == 994
    for row_id in selected:
        assert markdown_rows[row_id][4] == selected_rows[row_id]["check"]
        assert markdown_rows[row_id][6] == "missing"
