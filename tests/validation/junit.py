"""Read required pytest node outcomes from retained JUnit reports."""

from pathlib import Path
import xml.etree.ElementTree as ET


def executed_test_names(path: Path) -> set[str]:
    """Return base names of tests that actually ran and passed in a JUnit report.

    A check may only claim PASS when its named test is in this set.  Callers
    must never synthesize the set from an expected-name list or from a pytest
    exit code: a skipped, deselected or missing test leaves no passing case in
    the report.
    """
    if not path.is_file():
        raise ValueError(f"missing JUnit report {path}")
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    names: set[str] = set()
    for suite in suites:
        for case in suite.findall("testcase"):
            problem = any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            )
            if not problem:
                names.add(case.get("name", "").split("[", 1)[0])
    return names


def require_passing_junit(path: Path, required: list[str]) -> None:
    if not path.is_file():
        raise ValueError(f"missing JUnit report {path}")
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    cases = {}
    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "").split("[", 1)[0]
            node = f"{classname}::{name}"
            problem = any(
                case.find(tag) is not None for tag in ("failure", "error", "skipped")
            )
            cases.setdefault(node, []).append(not problem)
    for node in required:
        # JUnit node ids use dotted module paths and parametrized suffixes;
        # match by the base function name so parametrized tests still count.
        fn = node.split("::")[-1]
        hits = [
            v
            for k, values in cases.items()
            for v in values
            if k.rsplit("::", 1)[-1] == fn
        ]
        if not hits:
            raise ValueError(f"required test did not execute: {node}")
        if not all(hits):
            raise ValueError(f"required test was skipped or failed: {node}")
