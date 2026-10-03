"""Parsing helpers for `.github/workflows/*.yml`, shared by the CI contracts.

A workflow is configuration, not prose. Every property a contract wants to
assert about one -- the concurrency group, the steps a job runs, the labels a
matrix requests -- is available by *parsing* it. Reading the file as text and
searching for a substring cannot tell the difference between a key that is
present and a key that is **executed**, and that difference is not academic:
PyYAML resolves duplicate mapping keys last-wins without a word, so a text
search reports the intended wiring as present while the run executes the other
copy. That is a defect this repository has already shipped once.

So: parse, and never fall back to `yaml.safe_load` where a duplicate key is
the thing being ruled out.
"""

from __future__ import annotations

import glob
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO / ".github" / "workflows"


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of dropping them."""


def _reject_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _reject_duplicate_keys
)


def workflow_files() -> list[Path]:
    return [Path(p) for p in sorted(glob.glob(str(WORKFLOW_DIR / "*.yml")))]


def parse_workflow(path: Path) -> dict:
    """Parse a workflow, raising on a duplicate key rather than dropping it."""
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=StrictLoader)


def parse_workflow_or_none(path: Path) -> dict | None:
    """Parse a workflow, or return None if it will not parse at all.

    Lets an inventory helper keep going so the duplicate key is reported once,
    by name, instead of as a collection error that hides which check fired.
    """
    try:
        return parse_workflow(path)
    except yaml.YAMLError:
        return None


def concurrency_of(path: Path) -> dict:
    """The workflow's `concurrency:` block, parsed."""
    doc = parse_workflow_or_none(path)
    if not isinstance(doc, dict):
        return {}
    value = doc.get("concurrency")
    return value if isinstance(value, dict) else {}


def job_matrix_values(path: Path, job_name: str, key: str) -> list:
    """The values `key` takes across a job's `strategy.matrix.include` entries.

    Asserting on these by value rather than by source text matters: the YAML
    `macos_deployment_target: "10.13"` and `macos_deployment_target: 10.13` are
    the same deployment target, and a test that only accepts the quoted form is
    asserting the author's punctuation.
    """
    doc = parse_workflow_or_none(path)
    job = ((doc or {}).get("jobs") or {}).get(job_name) or {}
    include = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
    return [entry[key] for entry in include if isinstance(entry, dict) and key in entry]


def job_subtree_text(path: Path, job_name: str) -> str:
    """A job's parsed subtree, rendered as text for substring assertions.

    Substring assertions are still the right shape for "does this step invoke
    X", but the haystack is now the *parsed* job rather than a regex slice of
    the file. A duplicate key inside the job is still resolved last-wins here,
    which is why `tests/test_workflow_contract.py` rejects duplicates outright
    rather than trusting this rendering.
    """
    doc = parse_workflow_or_none(path)
    jobs = (doc or {}).get("jobs") or {}
    if job_name not in jobs:
        raise AssertionError(f"{path.name} must define a {job_name} job")
    return render_scalars(jobs[job_name])


def render_scalars(node) -> str:
    """Render a parsed subtree as its scalar content, formatting-agnostically.

    `yaml.safe_dump` is the obvious way to get text out of parsed YAML and the
    wrong one: it re-folds and re-quotes long shell commands, so a substring
    written against the source file stops matching. That would force callers
    to assert on formatting, which is the opposite of the point.

    So emit the *values* the subtree contains, plus the `key: value` and
    `key: [a, b]` renderings of its scalar and list leaves. Callers can still
    write `assert "x" in job`, and the haystack still comes from the parsed
    structure rather than the file text.
    """
    out: list[str] = []

    def walk(item, key=None):
        if isinstance(item, dict):
            for k, v in item.items():
                walk(v, k)
        elif isinstance(item, list):
            scalars = [str(x) for x in item if not isinstance(x, (dict, list))]
            if key is not None and scalars:
                out.append(f"{key}: [{', '.join(scalars)}]")
            for x in item:
                walk(x, key)
        elif item is not None:
            out.append(str(item))
            if key is not None:
                out.append(f"{key}: {str(item)}")

    walk(node)
    return "\n".join(out)
