"""Independent documentation acceptance checks for issue #472."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(os.environ.get("BNG3_DOCS_ROOT", Path(__file__).resolve().parents[5]))
INLINE_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")
REFERENCE_DEF = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)
REFERENCE_USE = re.compile(r"!?\[([^\]]+)\]\[([^\]]*)\]")
ISSUE_URL = re.compile(r"https://github\.com/RuleWorld/BNG3/issues/(\d+)(?:#[\w-]+)?\Z")
ISSUE_LINK = re.compile(r"\[#(\d+)\]\(([^)]+)\)")
CHECK_ID = re.compile(r"`(release-[a-z0-9-]+)`")


def _assessed_content_sha256(root: Path) -> str:
    paths = [root / "README.md", root / "provenance/capability-matrix.yml"]
    docs = root / "docs"
    if docs.exists():
        paths.extend(docs.rglob("*.md"))
    digest = hashlib.sha256()
    for path in sorted(
        (item for item in paths if item.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _markdown_files(root: Path) -> list[Path]:
    return [
        path
        for path in [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
        if path.is_file()
    ]


def _headings(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        slug = re.sub(r"[^\w -]", "", heading.lower()).strip().replace(" ", "-")
        n = counts.get(slug, 0)
        counts[slug] = n + 1
        slugs.add(slug if n == 0 else f"{slug}-{n}")
    return slugs


def _without_code(text: str) -> str:
    """Remove code examples and inline code before scanning Markdown links."""
    text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$", "", text)
    return re.sub(r"`+[^`]*`+", "", text)


def _markdown_link_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for source in _markdown_files(root):
        if not source.is_file():
            continue
        text = _without_code(source.read_text(encoding="utf-8"))
        definitions = {
            key.casefold(): target for key, target in REFERENCE_DEF.findall(text)
        }
        targets = [
            target.strip().strip("<>") for _, target in INLINE_LINK.findall(text)
        ]
        for label, reference in REFERENCE_USE.findall(text):
            key = (reference or label).casefold()
            if key not in definitions:
                errors.append(
                    f"{source.relative_to(root)}: unresolved reference link [{label}][{reference}]"
                )
            else:
                targets.append(definitions[key])
        for target in targets:
            parsed = urlsplit(target)
            if parsed.scheme in {"http", "https", "mailto", "data"}:
                if parsed.netloc == "github.com" and parsed.path.startswith(
                    "/RuleWorld/BNG3/issues/"
                ):
                    if not ISSUE_URL.fullmatch(target):
                        errors.append(
                            f"{source.relative_to(root)}: malformed issue URL {target}"
                        )
                continue
            # Ignore mathematical notation such as [S](t), which is not a link.
            path_text, _, fragment = target.partition("#")
            if path_text and "/" not in path_text and Path(path_text).suffix == "":
                continue
            dest = (
                (source.parent / path_text).resolve() if path_text else source.resolve()
            )
            if not dest.exists():
                errors.append(f"{source.relative_to(root)}: broken local link {target}")
                continue
            if fragment and dest.is_file() and dest.suffix.lower() == ".md":
                if fragment not in _headings(dest):
                    errors.append(
                        f"{source.relative_to(root)}: missing heading #{fragment} in {dest.relative_to(root)}"
                    )
    return errors


def _split_table_row(line: str) -> list[str]:
    """Split Markdown table cells without treating escaped/code pipes as delimiters."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    cell: list[str] = []
    in_code = False
    escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "`" and not escaped:
            in_code = not in_code
        if char == "|" and not in_code and not escaped:
            cells.append("".join(cell).strip())
            cell = []
            escaped = False
            i += 1
            continue
        if char == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
        cell.append(char)
        i += 1
    cells.append("".join(cell).strip())
    return cells


def _inventory_errors(root: Path) -> list[str]:
    inventory_path = root / "docs/CAPABILITY_UNION_INVENTORY.md"
    matrix_path = root / "provenance/capability-matrix.yml"
    errors: list[str] = []
    if not inventory_path.is_file() or not matrix_path.is_file():
        return ["capability inventory or matrix is absent"]
    table_rows: dict[str, list[str]] = {}
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = _split_table_row(line)
        if not cells or cells[0] == "ID" or set(cells[0]) <= {"-", ":"}:
            continue
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", cells[0]):
            if cells[0] in table_rows:
                errors.append(f"inventory contains duplicate row ID {cells[0]}")
            table_rows[cells[0]] = cells
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"capability matrix cannot be parsed: {exc}"]
    rows = matrix.get("rows", [])
    row_ids = [row.get("id") for row in rows]
    if len(row_ids) != len(set(row_ids)):
        errors.append("matrix contains duplicate row IDs")
    if set(table_rows) != set(row_ids):
        errors.append(
            f"inventory/matrix row IDs differ: inventory-only={sorted(set(table_rows)-set(row_ids))[:5]}, "
            f"matrix-only={sorted(set(row_ids)-set(table_rows))[:5]}"
        )
    if len(table_rows) != len(rows):
        errors.append(
            f"inventory has {len(table_rows)} rows but matrix has {len(rows)}"
        )
    plan_path = root / "docs/PLAN.md"
    if not plan_path.is_file():
        errors.append("docs/PLAN.md is missing issue mappings")
        known_issues: set[int] = set()
    else:
        known_issues = {
            int(n)
            for n in re.findall(r"#(\d+)\b", plan_path.read_text(encoding="utf-8"))
        }
    for row in rows:
        row_id = row.get("id", "<missing-id>")
        for field in (
            "behavior",
            "upstream",
            "bng3",
            "check",
            "oracle",
            "status",
            "issue",
        ):
            if row.get(field) in (None, ""):
                errors.append(f"matrix row {row_id} lacks {field}")
        cells = table_rows.get(row_id)
        if cells:
            if len(cells) < 8 or any(not cells[index] for index in range(8)):
                errors.append(
                    f"inventory row {row_id} has an incomplete required field"
                )
            elif cells[4] != row.get("check"):
                errors.append(f"inventory row {row_id} check does not match the matrix")
            else:
                issue_match = re.search(r"#(\d+)\b", cells[7])
                if not issue_match or int(issue_match.group(1)) != row.get("issue"):
                    errors.append(
                        f"inventory row {row_id} issue does not match the matrix"
                    )
        issue = row.get("issue")
        if isinstance(issue, int) and issue not in known_issues:
            errors.append(f"matrix row {row_id} issue #{issue} has no PLAN mapping")
        for check_path in re.findall(
            r"(?<![\w])((?:tests|scripts)/[\w./-]+)", row.get("check", "")
        ):
            if not (root / check_path.rstrip(".,;")).exists():
                errors.append(
                    f"matrix row {row_id} check path does not resolve: {check_path}"
                )
    return errors


def _link_acceptance_errors(root: Path) -> list[str]:
    errors = _markdown_link_errors(root) + _inventory_errors(root)
    readme_path = root / "README.md"
    if not readme_path.is_file():
        errors.append("README.md is missing")
        readme = ""
    else:
        readme = readme_path.read_text(encoding="utf-8")
    checklist_path = root / "docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md"
    index_path = root / "docs/index.md"
    progress_path = root / "docs/CURRENT_PROGRESS.md"
    for path in (checklist_path, index_path):
        if not path.is_file():
            errors.append(
                f"required navigation document missing: {path.relative_to(root)}"
            )
    checklist = (
        checklist_path.read_text(encoding="utf-8") if checklist_path.exists() else ""
    )
    index = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    for name, text in (
        ("README.md", readme),
        ("docs/BNG3_CONVERGENCE_DONE_CHECKLIST.md", checklist),
        ("docs/index.md", index),
    ):
        for required in ("CAPABILITY_UNION_INVENTORY.md", "DECISIONS.md"):
            if required not in text:
                errors.append(f"{name} does not link {required}")
    if "CURRENT_PROGRESS.md" not in readme:
        errors.append("README.md does not link current issue status")
    plan_path = root / "docs/PLAN.md"
    if progress_path.exists() and plan_path.exists():
        progress = progress_path.read_text(encoding="utf-8")
        plan = plan_path.read_text(encoding="utf-8")
        known_issues = {int(n) for n in re.findall(r"#(\d+)\b", plan)}
        for issue, url in ISSUE_LINK.findall(progress):
            if not ISSUE_URL.fullmatch(url):
                errors.append(
                    f"CURRENT_PROGRESS.md: issue #{issue} does not use the canonical issue URL"
                )
            if int(issue) not in known_issues:
                errors.append(
                    f"CURRENT_PROGRESS.md: issue #{issue} has no PLAN mapping"
                )
        known_checks = set(CHECK_ID.findall(plan))
        for check in set(CHECK_ID.findall(progress)) - known_checks:
            errors.append(f"CURRENT_PROGRESS.md: check {check} has no PLAN declaration")
    return errors


def _decision_acceptance_errors(root: Path) -> list[str]:
    errors: list[str] = []
    decision_path = root / "docs/DECISIONS.md"
    if not decision_path.is_file():
        return ["docs/DECISIONS.md is missing"]
    decisions = decision_path.read_text(encoding="utf-8")
    required = (
        "every user-facing capability",
        "All inventory rows are release requirements",
        "Native BNG3 solvers are the default",
        "BNGsim is a supported optional backend",
        "NFnext is the single next-generation engine",
        "Equality means process equality",
    )
    for phrase in required:
        if phrase.casefold() not in decisions.casefold():
            errors.append(f"DECISIONS.md omits final decision: {phrase}")
    banned = (
        r"all decisions remain pending",
        r"release boundary proposed for approval",
        r"BNGIR v0\.1 (?:is )?(?:the )?(?:public )?default",
        r"the capability inventory is not the release scope",
        r"release scope (?:is|remains) (?:pending|proposed for approval)",
        r"BNGsim(?: backend)? (?:is|becomes) (?:the )?(?:default|primary)",
        r"(?:default|primary) (?:is|becomes) BNGsim(?: backend)?",
        r"NFcore is not (?:the )?(?:production )?default",
        r"NFnext (?:is|becomes) (?:the )?(?:production )?default",
        r"(?:approval|approval receipt) is required to (?:finalize|close) (?:a )?decision",
    )
    for path in _markdown_files(root):
        if "archive" in path.relative_to(root).parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in banned:
            if re.search(pattern, text, re.IGNORECASE):
                errors.append(
                    f"{path.relative_to(root)} conflicts with final decisions: {pattern}"
                )
    archive = root / "docs/archive"
    if archive.exists():
        for path in archive.rglob("*.md"):
            first_lines = "\n".join(
                path.read_text(encoding="utf-8").splitlines()[:4]
            ).casefold()
            if not any(
                term in first_lines for term in ("historical", "archived", "archive")
            ):
                errors.append(
                    f"{path.relative_to(root)} is archived without a history label"
                )
    return errors


if __name__ == "__main__":
    import argparse
    import subprocess
    import sys

    parser = argparse.ArgumentParser(
        description="Evaluate issue #472 documentation acceptance checks"
    )
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=REPO,
        help="checkout containing documentation to assess",
    )
    parser.add_argument(
        "--report", type=Path, help="write machine-readable JSON assessment"
    )
    args = parser.parse_args()
    root = args.docs_root.resolve()

    def git_identity(checkout: Path) -> tuple[str | None, bool | None]:
        try:
            revision = subprocess.check_output(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            status = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                text=True,
            )
            return revision, bool(status.strip())
        except (OSError, subprocess.CalledProcessError):
            return None, None

    assessed_revision, assessed_dirty = git_identity(root)
    checker_revision, checker_dirty = git_identity(REPO)
    checker_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assessed_sha256 = _assessed_content_sha256(root)
    results = []
    for check_id, fn in (
        ("release-docs-links", _link_acceptance_errors),
        ("release-docs-decisions", _decision_acceptance_errors),
    ):
        findings = fn(root)
        results.append(
            {
                "check_id": check_id,
                "status": "FAIL" if findings else "PASS",
                "findings": findings,
            }
        )
    report = {
        "issue": 472,
        "evaluated_checkout": str(root),
        "assessed_revision": assessed_revision,
        "assessed_working_tree_dirty": assessed_dirty,
        "assessed_content_sha256": assessed_sha256,
        "checker_revision": checker_revision,
        "checker_working_tree_dirty": checker_dirty,
        "checker_source_sha256": checker_sha256,
        "checks": results,
        "status": (
            "FAIL" if any(item["status"] == "FAIL" for item in results) else "PASS"
        ),
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    sys.exit(1 if report["status"] == "FAIL" else 0)
