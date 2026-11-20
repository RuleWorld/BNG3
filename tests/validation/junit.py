"""Read required pytest node outcomes from retained JUnit reports."""

from pathlib import Path
import xml.etree.ElementTree as ET


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
