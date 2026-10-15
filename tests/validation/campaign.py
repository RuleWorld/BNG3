"""Evidence-preserving process and test adapters for the existing harness."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .inventory import sha256

STATUSES = (
    "PASS",
    "FAIL",
    "UNSUPPORTED",
    "NOT_TESTED",
    "INVALID_INPUT",
    "TIMEOUT",
    "HARNESS_ERROR",
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def verify_source(root: Path, source: dict) -> dict:
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise ValueError("reference must be the root of an independent checkout")
    revision = git(root, "rev-parse", "HEAD")
    if revision != source["revision"]:
        raise ValueError(
            f"reference revision {revision} != locked {source['revision']}"
        )
    remote = git(root, "remote", "get-url", "origin")
    if remote.lower().removesuffix(".git") != source["repository"].lower().removesuffix(
        ".git"
    ):
        raise ValueError(f"wrong reference repository: {remote}")
    if git(root, "diff", "HEAD", "--name-only"):
        raise ValueError("reference tracked tree is dirty")
    hidden = [
        line
        for line in git(root, "ls-files", "-v").splitlines()
        if not line.startswith("H ")
    ]
    if hidden:
        raise ValueError("reference has hidden index flags: " + hidden[0])
    untracked = git(root, "ls-files", "--others", "--exclude-standard")
    if untracked:
        raise ValueError("reference has untracked inputs: " + untracked.splitlines()[0])
    return {
        "path": str(root),
        "revision": revision,
        "repository": remote,
        "tree": git(root, "rev-parse", "HEAD^{tree}"),
    }


def verify_digest(path: Path, expected: str) -> None:
    if sha256(path) != expected.removeprefix("sha256:"):
        raise ValueError(f"digest mismatch: {path}")


def reject_shared_engine(
    subject: Path, reference: Path, *, implementation_root: Path | None = None
) -> None:
    if implementation_root and reference.resolve().is_relative_to(
        implementation_root.resolve()
    ):
        raise ValueError("embedded binary is not an independent reference")
    if subject.resolve() == reference.resolve() or sha256(subject) == sha256(reference):
        raise ValueError("reference and subject use the same implementation")


def run_command(
    command: list[str],
    directory: Path,
    timeout: float,
    *,
    required=(),
    env=None,
    cwd=None,
) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {
        "command": command,
        "cwd": str((cwd or directory).resolve()),
        "timeout_seconds": timeout,
    }
    start = time.monotonic()
    with (
        (directory / "stdout.log").open("w") as stdout,
        (directory / "stderr.log").open("w") as stderr,
    ):
        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd or directory,
                stdout=stdout,
                stderr=stderr,
                env=env,
                start_new_session=os.name != "nt",
            )
            try:
                code = proc.wait(timeout=timeout)
                receipt.update(
                    status="PASS" if code == 0 else "FAIL", returncode=code, detail=""
                )
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True,
                    )
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                receipt.update(
                    status="TIMEOUT", returncode=None, detail="process budget exceeded"
                )
        except OSError as exc:
            receipt.update(status="HARNESS_ERROR", returncode=None, detail=str(exc))
    receipt["elapsed_seconds"] = time.monotonic() - start
    if receipt["status"] == "FAIL":
        output = (directory / "stderr.log").read_text(errors="replace") or (
            directory / "stdout.log"
        ).read_text(errors="replace")
        receipt["detail"] = (
            output
            if len(output) <= 4000
            else output[:2000] + "\n...\n" + output[-2000:]
        )
    receipt["artifacts"] = [
        {"path": str(p.resolve()), "sha256": sha256(p)}
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    ]
    if receipt["status"] == "PASS":
        missing = [p for p in required if not (directory / p).is_file()]
        if missing:
            receipt.update(
                status="HARNESS_ERROR", detail="missing output: " + ", ".join(missing)
            )
    (directory / "command.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def read_junit(path: Path, suite: str) -> list[dict]:
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"cannot read JUnit: {exc}") from exc
    rows = []
    for case in tree.iter("testcase"):
        status, detail = "PASS", ""
        for child in case:
            if child.tag in {"error", "failure", "skipped"}:
                status = {
                    "error": "HARNESS_ERROR",
                    "failure": "FAIL",
                    "skipped": "NOT_TESTED",
                }[child.tag]
                detail = child.get("message", "") + (
                    "\n" + child.text if child.text else ""
                )
                break
        rows.append(
            {
                "id": f"{suite}:{case.get('classname', '')}::{case.get('name', '')}",
                "suite": suite,
                "name": case.get("name", ""),
                "stage": "test",
                "status": status,
                "detail": detail,
                "test_file": case.get("file"),
                "elapsed_seconds": float(case.get("time", 0)),
            }
        )
    if not rows:
        raise ValueError("JUnit contains no test cases")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("JUnit contains duplicate test identities")
    return rows


def read_pytest_events(path: Path, suite: str) -> list[dict]:
    cases = {}
    stream_errors = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            stream_errors.append(
                {
                    "id": f"{suite}:event-stream:{number}",
                    "stage": "harness-integrity",
                    "status": "HARNESS_ERROR",
                    "detail": f"incomplete/corrupt event line {number}: {exc}",
                }
            )
            continue
        if event["event"] == "collection":
            for case in event["cases"]:
                cases.setdefault(case["nodeid"], {"file": case["file"], "phases": []})
        else:
            cases.setdefault(event["nodeid"], {"file": event["file"], "phases": []})[
                "phases"
            ].append(event)
    rows = stream_errors
    for nodeid, case in cases.items():
        phases = case["phases"]
        status, detail = "NOT_TESTED", "case not executed before interruption"
        failed = [p for p in phases if p["outcome"] == "failed"]
        skipped = [p for p in phases if p["outcome"] == "skipped" or p.get("xfail")]
        if failed:
            status = (
                "FAIL" if all(p["when"] == "call" for p in failed) else "HARNESS_ERROR"
            )
            detail = "\n".join(p["detail"] for p in failed)
        elif skipped:
            detail = "\n".join(p.get("xfail") or p["detail"] for p in skipped)
        elif any(
            p["when"] == "call" and p["outcome"] == "passed" for p in phases
        ) and any(p["when"] == "teardown" and p["outcome"] == "passed" for p in phases):
            status, detail = "PASS", ""
        elif phases:
            status, detail = "TIMEOUT", "case did not finish; inspect process outcome"
        rows.append(
            {
                "id": suite + ":" + nodeid,
                "name": nodeid,
                "suite": suite,
                "stage": "test",
                "status": status,
                "detail": detail,
                "failure_summary": "\n".join(
                    p.get("summary", p["detail"]) for p in failed
                ),
                "test_file": case["file"],
                "elapsed_seconds": sum(p["duration"] for p in phases),
            }
        )
    if not rows:
        raise ValueError("pytest event log contains no test cases")
    return rows
