"""The local Python-floor compatibility check stays effective.

``scripts/ci/check_python_floor.py`` replaces a wait for the ``Python 3.9 ...
3.14`` matrix when a pull request only changes Python code: the matrix can
only catch a construct that the floor interpreter rejects.  This test keeps
the local check honest -- it has to keep detecting the constructs it claims to
detect, it has to keep the repository itself within the floor, and it has to
refuse to pass when it cannot establish compatibility.

The verdict for a construct the floor does not provide is the same on every
host: the file needs an interpreter newer than the floor.  Only the precision
differs, because an interpreter that cannot read the file cannot name the
release that provides the construct.  The tests below therefore assert the
verdict everywhere and the exact release only where the host can name it.
"""

from __future__ import annotations

import ast
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

#: The version of the interpreter running the test.
HOST = sys.version_info[0], sys.version_info[1]

#: A nested f-string.  Python 3.12 relaxed the f-string rules, so an
#: interpreter older than 3.12 cannot even tokenise it.
PEP701_SOURCE = 'def f(data):\n    return f"{data["key"]}"\n'

#: A ``match`` statement, which needs Python 3.10.
MATCH_SOURCE = (
    "def f(x):\n    match x:\n        case 1:\n            return 1\n    return 0\n"
)

#: An exception group handler, which needs Python 3.11.
EXCEPTION_GROUP_SOURCE = (
    "def f():\n"
    "    try:\n"
    "        pass\n"
    "    except* ValueError:\n"
    "        pass\n"
)


def _findings(source, floor=FLOOR):
    """Return the findings of one synthetic file."""
    return analyse_source(Path("sample.py"), source, floor)


def _features(findings):
    return " ".join(finding.feature for finding in findings)


def _host_can_parse(source):
    """Return True when the interpreter running the test can read the source."""
    try:
        ast.parse(source)
    except SyntaxError:
        return False
    return True


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


def test_a_file_the_host_cannot_parse_needs_a_newer_interpreter():
    """A file the interpreter cannot read is not floor-compatible.

    This is the regression test for the classification of a parse failure.
    It does not depend on the host: the parser is replaced by one that
    refuses the file, exactly as an interpreter older than the construct
    does.
    """

    def refusing_parser(source, filename, feature_version=None):
        raise SyntaxError("f-string: unmatched '['")

    findings = analyse_source(
        Path("sample.py"),
        PEP701_SOURCE,
        FLOOR,
        host=(3, 10),
        parser=refusing_parser,
    )
    assert findings, "the parse failure was not reported"
    assert all(finding.requires_newer_interpreter() for finding in findings)
    assert findings[0].rejected_by == (3, 10)
    assert findings[0].rejected_by_role == "host"
    assert "3.10" in findings[0].render()
    assert "newer interpreter" in findings[0].render()


def test_a_file_the_floor_cannot_parse_needs_a_newer_interpreter():
    """A file the floor's grammar refuses is reported against the floor."""

    def floor_refusing_parser(source, filename, feature_version=None):
        if feature_version is None:
            return ast.parse(source, filename=filename)
        raise SyntaxError("invalid syntax")

    findings = analyse_source(
        Path("sample.py"),
        "x = 1\n",
        FLOOR,
        host=(3, 14),
        parser=floor_refusing_parser,
    )
    assert findings, "the parse failure was not reported"
    assert all(finding.requires_newer_interpreter() for finding in findings)
    assert findings[0].rejected_by == FLOOR
    assert findings[0].rejected_by_role == "floor"
    assert format_version(FLOOR) in findings[0].render()


def test_a_match_statement_is_reported():
    """A ``match`` statement needs a newer interpreter, on every host."""
    findings = _findings(MATCH_SOURCE)
    assert findings, "the match statement was not reported"
    assert all(finding.requires_newer_interpreter() for finding in findings)
    if _host_can_parse(MATCH_SOURCE):
        assert all(finding.minimum == (3, 10) for finding in findings)
    else:
        assert all(finding.rejected_by == HOST for finding in findings)


def test_an_exception_group_handler_is_reported():
    """An exception group needs a newer interpreter, on every host."""
    findings = _findings(EXCEPTION_GROUP_SOURCE)
    assert findings, "the exception group handler was not reported"
    assert all(finding.requires_newer_interpreter() for finding in findings)
    if _host_can_parse(EXCEPTION_GROUP_SOURCE):
        assert all(finding.minimum == (3, 11) for finding in findings)
    else:
        assert all(finding.rejected_by == HOST for finding in findings)


def test_a_runtime_pep604_union_is_reported():
    findings = _findings("def f():\n    return int | str\n")
    assert "PEP 604" in _features(findings)
    assert all(finding.minimum >= (3, 10) for finding in findings)


def test_a_pep604_annotation_is_reported_when_it_is_evaluated():
    findings = _findings("def f(x: int | None):\n    return x\n")
    assert "PEP 604" in _features(findings)


def test_a_bitwise_or_of_shouted_constants_is_not_a_union():
    # 'os.O_WRONLY | os.O_CREAT' is a bitwise OR of two flags, not a union of
    # two types, and every supported interpreter evaluates it.  The check read
    # the shouted attribute name as a class name and reported the whole file
    # as needing a newer interpreter.
    findings = _findings(
        "import os\n" "\n" "\n" "def f():\n" "    return os.O_WRONLY | os.O_CREAT\n"
    )
    assert findings == [], [finding.render() for finding in findings]


def test_a_bitwise_or_of_two_classes_is_still_reported():
    findings = _findings(
        "class A:\n    pass\n\n\nclass B:\n    pass\n\n\ndef f():\n    return A | B\n"
    )
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


def test_a_pep701_nested_fstring_is_reported():
    """A nested f-string needs a newer interpreter, on every host.

    Python 3.12 relaxed the f-string rules.  An interpreter older than 3.12
    cannot tokenise the file at all, so the report names that interpreter
    instead of the release; the verdict is the same either way.
    """
    findings = _findings(PEP701_SOURCE)
    assert findings, "the nested f-string was not reported"
    assert all(finding.requires_newer_interpreter() for finding in findings)
    if _host_can_parse(PEP701_SOURCE):
        assert all(finding.minimum == (3, 12) for finding in findings)
    else:
        assert all(finding.rejected_by == HOST for finding in findings)


def test_an_ordinary_fstring_is_not_reported():
    findings = _findings(
        "def f(data):\n    return f\"{data['key']} and {len(data)}\"\n"
    )
    assert findings == [], [finding.render() for finding in findings]


def test_an_escaped_quote_in_an_fstring_literal_is_not_reported():
    """The literal part of an f-string is not a replacement field.

    An escaped quote in the literal part of an f-string is valid on every
    supported interpreter.  Only Python 3.12 and later report the positions
    inside an f-string exactly, so the textual rule must not be used on the
    interpreters that do not.
    """
    source = "def f(path):\n" '    return f"""readFile({{file=>\\"{path}\\"}})"""\n'
    findings = _findings(source)
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


def test_a_file_with_a_syntax_error_is_not_reported_as_compatible():
    """A file the interpreter cannot read is not floor-compatible."""
    findings = _findings("def f(:\n")
    assert findings, "the syntax error was not reported"
    assert all(finding.requires_newer_interpreter() for finding in findings)


def test_a_host_older_than_the_floor_cannot_establish_compatibility():
    """An interpreter older than the floor cannot judge the floor."""
    with pytest.raises(CannotEstablish):
        analyse_source(Path("sample.py"), "x = 1\n", FLOOR, host=(3, 8))


def test_an_unreadable_file_is_not_reported_as_compatible(tmp_path):
    missing = tmp_path / "missing.py"
    with pytest.raises(CannotEstablish):
        check_files([missing], FLOOR, root=tmp_path)
