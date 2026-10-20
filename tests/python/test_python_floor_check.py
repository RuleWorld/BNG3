"""The local Python-floor compatibility check stays effective.

``scripts/ci/check_python_floor.py`` replaces a wait for the ``Python 3.9 ...
3.14`` matrix when a pull request only changes Python code: the matrix can
only catch a construct that the floor interpreter rejects.  This test keeps
the local check honest -- it has to keep detecting the constructs it claims to
detect, it has to keep the repository itself within the floor, and it has to
refuse to pass when it cannot establish compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.ci.check_python_floor import (
    CannotEstablish,
    analyse_source,
    check_files,
    floor_from_pyproject,
    format_version,
    matrix_versions_from_workflow,
    resolve_floor,
    scope_python_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FLOOR = (3, 9)


def _findings(source, floor=FLOOR):
    """Return the findings of one synthetic file."""
    return analyse_source(Path("sample.py"), source, floor)


def _features(findings):
    return " ".join(finding.feature for finding in findings)


def test_the_declared_floor_is_the_oldest_interpreter_of_the_ci_matrix():
    """``requires-python`` and the CI matrix have to agree on the floor."""
    floor = floor_from_pyproject(REPO_ROOT)
    assert floor == FLOOR, format_version(floor)

    matrix = matrix_versions_from_workflow(REPO_ROOT)
    assert matrix is not None, "the CI workflow no longer declares a matrix"
    assert min(matrix) == floor
    assert floor in matrix

    assert resolve_floor(REPO_ROOT, None) == floor


def test_the_repository_uses_no_construct_newer_than_the_floor():
    """The whole repository has to stay inside the floor it declares."""
    files = scope_python_files(REPO_ROOT)
    assert files, "the lint scope is empty"
    findings = check_files(files, FLOOR, root=REPO_ROOT)
    assert findings == [], [finding.render() for finding in findings]


def test_the_checker_and_its_own_test_stay_inside_the_floor():
    """The check has to be usable on the floor it checks against."""
    for path in (
        REPO_ROOT / "scripts" / "ci" / "check_python_floor.py",
        Path(__file__).resolve(),
    ):
        findings = analyse_source(path, path.read_text(encoding="utf-8"), FLOOR)
        assert findings == [], [finding.render() for finding in findings]


def test_a_match_statement_is_reported():
    source = (
        "def f(x):\n    match x:\n        case 1:\n            return 1\n    return 0\n"
    )
    try:
        findings = _findings(source)
    except CannotEstablish:
        # An interpreter that cannot parse the construct at all cannot
        # establish compatibility either, and must say so instead of passing.
        assert sys.version_info < (3, 10)
        return
    assert findings, "the match statement was not reported"
    assert all(finding.minimum >= (3, 10) for finding in findings)


def test_an_exception_group_handler_is_reported():
    source = (
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except* ValueError:\n"
        "        pass\n"
    )
    try:
        findings = _findings(source)
    except CannotEstablish:
        # Python 3.9 has no ``except*`` at all, so the checker refuses to
        # establish compatibility rather than reporting success.
        assert sys.version_info < (3, 11)
        return
    assert findings, "the exception group handler was not reported"
    assert all(finding.minimum >= (3, 11) for finding in findings)


def test_a_runtime_pep604_union_is_reported():
    findings = _findings("def f():\n    return int | str\n")
    assert "PEP 604" in _features(findings)
    assert all(finding.minimum >= (3, 10) for finding in findings)


def test_a_pep604_annotation_is_reported_when_it_is_evaluated():
    findings = _findings("def f(x: int | None):\n    return x\n")
    assert "PEP 604" in _features(findings)


def test_a_deferred_pep604_annotation_is_not_reported():
    findings = _findings(
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "def f(x: int | None):\n"
        "    return x\n"
    )
    assert findings == [], [finding.render() for finding in findings]


def test_a_pep585_builtin_generic_is_reported_below_its_release():
    findings = _findings("def f():\n    return list[int]\n", floor=(3, 8))
    assert "PEP 585" in _features(findings)

    findings = _findings("def f():\n    return list[int]\n", floor=FLOOR)
    assert findings == [], [finding.render() for finding in findings]


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "import itertools\n\n\ndef f():\n    return itertools.pairwise([1])\n",
            "itertools.pairwise",
        ),
        (
            "from typing import Self\n\n\ndef f() -> Self:\n    return None\n",
            "typing.Self",
        ),
        (
            "import typing\n\n\ndef f() -> typing.Self:\n    return None\n",
            "typing.Self",
        ),
        ("from datetime import UTC\n\n\ndef f():\n    return UTC\n", "datetime.UTC"),
        ("import tomllib\n\n\ndef f():\n    return tomllib.loads('{}')\n", "tomllib"),
        ("def f():\n    raise ExceptionGroup('x', [])\n", "ExceptionGroup"),
    ],
)
def test_the_constructs_the_floor_lacks_are_reported(source, expected):
    findings = _findings(source)
    assert expected in _features(findings), [finding.render() for finding in findings]


@pytest.mark.parametrize("method", ["removeprefix", "removesuffix"])
def test_the_str_methods_of_python39_are_reported_below_their_release(method):
    source = f"def f():\n    return 'x'.{method}('x')\n"
    assert _findings(source, floor=FLOOR) == []
    assert method in _features(_findings(source, floor=(3, 8)))


def test_zoneinfo_is_available_on_the_floor_but_not_below_it():
    source = "import zoneinfo\n\n\ndef f():\n    return zoneinfo.ZoneInfo('UTC')\n"
    assert _findings(source, floor=FLOOR) == []
    assert "zoneinfo" in _features(_findings(source, floor=(3, 8)))


def test_a_file_that_cannot_be_parsed_is_not_reported_as_compatible():
    with pytest.raises(CannotEstablish):
        _findings("def f(:\n")


def test_an_unreadable_file_is_not_reported_as_compatible(tmp_path):
    missing = tmp_path / "missing.py"
    with pytest.raises(CannotEstablish):
        check_files([missing], FLOOR, root=tmp_path)
