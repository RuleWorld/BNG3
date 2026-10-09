"""The parity workflow must actually run the parity modules.

`tests/validation/test_parity_nfsim.py` and
`tests/validation/test_parity_nfsim_seed.py` are selected by path in
`parity.yml`. Their selection is invisible to a Python suite: nothing fails
when a module stops being collected, and the job reports green having tested
less than it did.

This file checks the wiring itself. It exists because the wiring was wrong once
already, and the failure was invisible by construction:

    - name: Run direct/XML NFsim construction checks
    - name: Run NFsim seed-state parity contracts
      shell: bash
      run: |
        ... tests/validation/test_parity_nfsim_seed.py ...
      shell: bash
      run: |
        ... tests/validation/test_parity_nfsim.py -m "nf and not slow" ...

A new step had been inserted between an existing `- name:` and its `shell:`/`run:`,
producing one mapping with two `shell:` keys and two `run:` keys. YAML resolves
duplicate keys by keeping the LAST, so the parsed result silently became:

  * a step named "Run direct/XML NFsim construction checks" with no `run` at all
    (a step GitHub Actions cannot execute), and
  * a step named "Run NFsim seed-state parity contracts" whose body ran the OLD
    module, so the new module was collected by nothing.

`yaml.safe_load` does not raise on duplicate keys. It accepts the file, returns a
plausible structure, and drops the first value of each pair without a word. That
is why this file asserts on the PARSED structure rather than on the text, and why
it also refuses duplicate keys explicitly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PARITY_WORKFLOW = REPO / ".github" / "workflows" / "parity.yml"

# The modules the nfsim-parity job is supposed to execute.
PARITY_MODULES = (
    "tests/validation/test_parity_nfsim.py",
    "tests/validation/test_parity_nfsim_seed.py",
)


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys instead of dropping them.

    PyYAML keeps the last value for a repeated key and reports nothing. That is
    the whole defect: a step can lose its `run:` and the file still parses.
    """


def _reject_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise AssertionError(
                f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}; "
                "PyYAML would silently keep only the last value"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _reject_duplicate_keys
)


def _parse_workflow() -> dict:
    """Parse parity.yml, failing with the duplicate-key cause if there is one.

    Called inside each test rather than from a fixture, so a malformed workflow
    reports as one clean failure per test instead of a fixture ERROR plus a
    cascade. A fixture that calls `pytest.fail` makes every dependent test ERROR
    under pytest, which buries the single message that matters.
    """
    text = PARITY_WORKFLOW.read_text(encoding="utf-8")
    try:
        return yaml.load(text, Loader=_StrictLoader)
    except AssertionError as exc:
        pytest.fail(str(exc), pytrace=False)


def test_parity_workflow_has_no_duplicate_yaml_keys():
    """Duplicate keys are the mechanism that broke this wiring once already.

    Asserted as its own test so the failure names the cause rather than
    surfacing as a confusing downstream symptom about a missing `run:`.
    """
    _parse_workflow()


def test_every_parity_job_step_is_executable():
    """Every step in the parity jobs must carry `run` or `uses`.

    A `- name:` with neither is a step GitHub Actions cannot run. It is accepted
    by the YAML parser, so nothing else in CI would notice.
    """
    parity_workflow = _parse_workflow()

    for job_name, job in parity_workflow["jobs"].items():
        for index, step in enumerate(job.get("steps", [])):
            if "run" not in step and "uses" not in step:
                pytest.fail(
                    f"{PARITY_WORKFLOW.name}: job {job_name!r} step {index} "
                    f"({step.get('name')!r}) has neither 'run' nor 'uses'"
                )


def test_parity_jobs_checkout_the_declared_source_commit():
    """PR parity evidence must come from the PR source head, not its merge ref."""
    parity_workflow = _parse_workflow()
    exact_source = "${{ github.event.pull_request.head.sha || github.sha }}"

    for job_name, job in parity_workflow["jobs"].items():
        for index, step in enumerate(job.get("steps", [])):
            if step.get("uses", "").startswith("actions/checkout@"):
                ref = (step.get("with") or {}).get("ref")
                assert ref == exact_source, (
                    f"{PARITY_WORKFLOW.name}: job {job_name!r} checkout step "
                    f"{index} uses {ref!r}; parity must test {exact_source!r}"
                )

    for job_name, step_name in (
        ("bng2-parity", "Verify installed BNG3 package and native identity"),
        ("nfsim-parity", "Report installed BNG3 package and native identities"),
    ):
        job = parity_workflow["jobs"][job_name]
        step = next(item for item in job["steps"] if item.get("name") == step_name)
        assert "--require-source-head" in step["run"]
        assert (step.get("env") or {}).get("BNG3_SOURCE_REVISION") == exact_source


def test_nfsim_parity_job_runs_every_parity_module():
    """Each parity module must appear in some step's command.

    `parity.yml` selects modules by path, so a module that is not named is not
    collected -- and nothing reports that. Asserting the module appears in a
    *parsed* step body is what makes this catch the duplicate-key case, where
    the text contained the module but the executed command did not.
    """
    parity_workflow = _parse_workflow()

    commands = "\n".join(
        str(step.get("run", ""))
        for step in parity_workflow["jobs"]["nfsim-parity"]["steps"]
    )
    for module in PARITY_MODULES:
        assert module in commands, (
            f"{module} is not run by any step of parity.yml:nfsim-parity; a "
            "parity module no job collects is a gate that reports green "
            "without testing anything"
        )


def test_each_parity_module_is_run_by_a_step_named_for_what_it_runs():
    """A step's name must describe the command it actually executes.

    Directly targeted at the observed failure: a step named
    "Run NFsim seed-state parity contracts" was executing the other module's
    command. A mismatch here is how a reader (and a reviewer) ends up believing
    the wrong gate ran.
    """
    parity_workflow = _parse_workflow()

    steps = parity_workflow["jobs"]["nfsim-parity"]["steps"]
    for step in steps:
        run = str(step.get("run", ""))
        if "test_parity_nfsim_seed.py" not in run:
            continue
        name = str(step.get("name", ""))
        assert "seed" in name.lower(), (
            f"the step running test_parity_nfsim_seed.py is named {name!r}, "
            "which does not identify it"
        )


def test_parity_workflow_env_still_pins_the_strict_oracle_flag():
    """`BNG3_CI_STRICT_ORACLES` is what turns a missing oracle into a failure.

    Losing it would silently convert every oracle-gated parity step into a
    skip. Asserted here because the flag is a single line that no behavioural
    test would notice missing, and `test_parity_nfsim_seed.py` depends on the
    strict-mode behaviour being reachable.
    """
    text = PARITY_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r'^\s*BNG3_CI_STRICT_ORACLES:\s*"1"\s*$', text, re.MULTILINE
    ), "parity.yml no longer sets BNG3_CI_STRICT_ORACLES=1; oracle-gated parity steps would skip instead of failing"


def test_orchestrated_steps_keep_their_shell_before_their_run():
    """Guard the shape of the defect: `shell:` must not follow a foreign `- name:`.

    The edit that introduced the bug placed a new `- name:` between an existing
    name and its body. Requiring each step's `shell:` to appear before its
    `run:` keeps the two attached to the same step under a plain text read,
    which is how the mistake is visible without a YAML parse.
    """
    lines = PARITY_WORKFLOW.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^\s+- name:", line):
            continue
        indent = len(line) - len(line.lstrip())
        window = lines[index + 1 : index + 12]
        body = []
        for candidate in window:
            stripped = candidate.strip()
            if not stripped:
                continue
            if len(candidate) - len(candidate.lstrip()) <= indent:
                break
            body.append((len(candidate) - len(candidate.lstrip()), stripped))
        keys = [
            text
            for _, text in body
            if text.split(":")[0] in {"shell", "run", "uses", "env"}
        ]
        if "run" in keys and "shell" in keys:
            assert keys.index("shell") < keys.index("run"), (
                f"step at {PARITY_WORKFLOW.name}:{index + 1} has 'run:' before "
                "'shell:'; a new '- name:' inserted between them would split "
                "the step in two"
            )
