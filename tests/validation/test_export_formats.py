"""Export-format validity (WO-5): one writer set, all formats valid."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.validation import compare, corpus, runner

EXPORT_MODELS = [
    m
    for m in ("Motivating_example", "egfr_net", "gene_expr", "Repressilator")
    if corpus.resolve(m) is not None
]

# The writers that had no coverage anywhere in tests/ before this file. They are
# action-level: the Python `Model` API exposes only write_xml/bngl/net/sbml/
# matlab/latex (python/bionetgen/model.py:573-620), so SSC, MDL and MEX are
# reachable only through the engine's action dispatch
# (cpp/actions/ActionDispatch.cpp:3553, :3666, :3848, :3866).
WRITE_ACTIONS = (
    "writeSSC()",
    "writeSSCcfg()",
    "writeMDL()",
    "writeMfile()",
    "writeMexfile()",
    "writeLatex()",
)


def _model_definition(text: str) -> str:
    """Return the model's block section with its own action list removed.

    Corpus models carry heavy action blocks -- gene_expr alone runs two 5e7 s
    stochastic simulations -- which is pure noise for a writer smoke gate. The
    `begin model`/`end model` form and the bare form both appear in the corpus
    (Repressilator has no `end model`), so cut at the first top-level line that
    is neither a comment nor a `begin`/`end` block delimiter, rather than
    searching for a terminator that may not exist.
    """
    kept: list[str] = []
    depth = 0
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if depth == 0 and stripped and not re.match(r"^(begin|end)\b", stripped):
            break
        kept.append(line)
        if re.match(r"^begin\b", stripped):
            depth += 1
        elif re.match(r"^end\b", stripped):
            depth -= 1
    return "\n".join(kept)


@pytest.fixture(scope="session")
def written_exports(bng_cpp, tmp_path_factory) -> dict[str, Path]:
    """Run the engine once per model with every write action, in isolation.

    One run per model rather than one per format, so that all six artifacts are
    known to come from a single consistent model state -- and so the two SSC
    artifacts are exercised together, which is the case that regressed.
    """
    produced: dict[str, Path] = {}
    for name in EXPORT_MODELS:
        source_dir = tmp_path_factory.mktemp(f"exportsrc_{name}")
        run_dir = tmp_path_factory.mktemp(f"exportrun_{name}")
        source = source_dir / f"{name}.bngl"
        source.write_text(
            _model_definition(corpus.resolve(name).read_text(encoding="utf-8"))
            + "\n\n"
            + "\n".join(WRITE_ACTIONS)
            + "\n",
            encoding="utf-8",
        )
        net, _, err = runner.run_cli_path(bng_cpp, source, run_dir)
        assert net is not None, f"export generation failed [{name}]: {err}"
        produced[name] = run_dir
    return produced


def _artifact(run_dir: Path, model_name: str, suffix: str) -> str:
    """Presence + non-emptiness check; returns the decoded artifact text."""
    path = run_dir / f"{model_name}{suffix}"
    assert path.is_file(), f"writer produced no {suffix} artifact [{model_name}]"
    text = path.read_text(encoding="utf-8", errors="replace")
    assert text.strip(), f"{suffix} artifact is empty [{model_name}]"
    return text


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_xml_wellformed(model_name, api, work_dir):
    out = runner.export(model_name, "xml", work_dir / f"{model_name}.xml")
    ok, msg = compare.check_xml_wellformed(out)
    assert ok, f"BNG-XML not well-formed [{model_name}]: {msg}"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_sbml_valid(model_name, api, work_dir):
    out = runner.export(model_name, "sbml", work_dir / f"{model_name}.xml")
    ok, msg = compare.check_sbml(out)
    assert ok, f"SBML invalid [{model_name}]: {msg}"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_net_roundtrip_idempotent(model_name, bng_cpp, work_dir):
    """write -> read -> write produces an identical network."""
    net1, _, err = runner.run_cli(bng_cpp, model_name, work_dir / "pass1")
    assert net1 is not None, f"first generation failed: {err}"

    # Follow BNG2's michment/michment_cont contract: the second pass must read
    # the first pass's .net file, not regenerate the BNGL model.
    roundtrip_source = work_dir / f"{model_name}_roundtrip.bngl"
    roundtrip_source.write_text(
        f'readFile({{file=>"{net1.as_posix()}"}})\nwriteNetwork({{overwrite=>1}})\n',
        encoding="utf-8",
    )
    net2, _, err2 = runner.run_cli_path(bng_cpp, roundtrip_source, work_dir / "pass2")
    assert net2 is not None, f"second generation failed: {err2}"
    n1, n2 = compare.parse_net(net1), compare.parse_net(net2)
    diff = compare.compare_net(n1, n2)
    assert diff.ok, f"net not idempotent [{model_name}]:\n{diff.summary()}"


# --------------------------------------------------------------------------- #
# SSC: two actions, two different artifacts.
#
# BNG2 writes a full reaction program to .rxn (BNGOutput.pm:1288-1369) and a
# parameter-only block to .cfg (:1371-1397). A build in which both actions emit
# the full program is a user-facing bug that a "a file appeared" check cannot
# see, so the assertions below are on content, not presence.
# --------------------------------------------------------------------------- #


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_ssc_rxn_is_a_full_program(model_name, written_exports):
    rxn = _artifact(written_exports[model_name], model_name, ".rxn")
    for section in ("// Parameters", "// Species", "// Reactions"):
        assert section in rxn, f"SSC .rxn missing {section} section [{model_name}]"
    # A species declaration and a reaction rule, not just the three headings.
    assert re.search(
        r"^new \w+\(", rxn, re.M
    ), f"SSC .rxn declares no species [{model_name}]"
    assert re.search(
        r"^[^/\s]\S*\s*->.*;\s*$", rxn, re.M
    ), f"SSC .rxn declares no reaction rule [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_ssc_cfg_is_parameters_only(model_name, written_exports):
    cfg = _artifact(written_exports[model_name], model_name, ".cfg")
    assert "const " in cfg, f"SSC .cfg has no parameter block [{model_name}]"
    for forbidden in ("// Species", "// Reactions"):
        assert forbidden not in cfg, (
            f"SSC .cfg carries the {forbidden} section of a full program "
            f"[{model_name}] -- writeSSCcfg must not re-emit writeSSC's output"
        )
    assert not re.search(
        r"^new \w+\(", cfg, re.M
    ), f"SSC .cfg declares species [{model_name}]"
    assert "->" not in cfg, f"SSC .cfg declares reaction rules [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_ssc_cfg_and_rxn_are_different_artifacts(model_name, written_exports):
    """The regression: .cfg is the .rxn parameter block and nothing else."""
    run_dir = written_exports[model_name]
    rxn = _artifact(run_dir, model_name, ".rxn")
    cfg = _artifact(run_dir, model_name, ".cfg")
    assert cfg != rxn, f"SSC .cfg and .rxn are the same artifact [{model_name}]"

    rxn_params = {ln for ln in rxn.splitlines() if ln.startswith("const ")}
    cfg_params = {ln for ln in cfg.splitlines() if ln.startswith("const ")}
    assert cfg_params, f"SSC .cfg has no parameter block [{model_name}]"
    assert (
        cfg_params <= rxn_params
    ), f"SSC .cfg parameters are not the .rxn parameter block [{model_name}]"
    # The two blocks are *meant* to agree on parameters; what must not survive
    # into .cfg is everything after them, which the section assertions in
    # test_ssc_cfg_is_parameters_only cover.
    assert len(cfg.splitlines()) < len(
        rxn.splitlines()
    ), f"SSC .cfg is at least as large as the full program [{model_name}]"


# --------------------------------------------------------------------------- #
# MDL / MATLAB / MEX / LaTeX.
#
# These are smoke gates, not goldens: each asserts the file exists, is
# non-empty, and carries the section markers that make it that format rather
# than a differently-named copy of something else. They do NOT check numeric
# values, so a writer that emitted structurally valid but wrong numbers would
# still pass.
# --------------------------------------------------------------------------- #


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_mdl_written(model_name, written_exports):
    mdl = _artifact(written_exports[model_name], model_name, ".mdl")
    for marker in ("ITERATIONS", "DEFINE_MOLECULES", "DEFINE_REACTIONS"):
        assert marker in mdl, f"MDL missing {marker} [{model_name}]"
    assert re.search(
        r"^\s*\w+ \{ DIFFUSION_CONSTANT_3D", mdl, re.M
    ), f"MDL declares no molecule with a diffusion coefficient [{model_name}]"
    assert "INSTANTIATE" in mdl, f"MDL never instantiates the world [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_matlab_mfile_written(model_name, written_exports):
    m = _artifact(written_exports[model_name], model_name, ".m")
    assert (
        "function [err, timepoints" in m
    ), f"MATLAB .m is not the documented 4-output entry point [{model_name}]"
    for helper in ("getDefaultParameters", "getInitialSpecies"):
        assert helper in m, f"MATLAB .m missing {helper}() [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_mex_c_written(model_name, written_exports):
    # MexWriter appends a "_mex" tag to the output stem (ActionDispatch.cpp:3686).
    mex = _artifact(written_exports[model_name], model_name, "_mex.c")
    assert '#include "mex.h"' in mex, f"MEX file does not include mex.h [{model_name}]"
    assert "mexFunction" in mex, f"MEX file defines no mexFunction [{model_name}]"


@pytest.mark.export
@pytest.mark.parametrize("model_name", EXPORT_MODELS)
def test_latex_written(model_name, written_exports):
    tex = _artifact(written_exports[model_name], model_name, ".tex")
    assert "\\documentclass" in tex, f"LaTeX has no documentclass [{model_name}]"
    assert "\\begin{document}" in tex, f"LaTeX never begins the document [{model_name}]"
    assert "\\end{document}" in tex, f"LaTeX document is unterminated [{model_name}]"
    for section in ("\\section{Parameters}", "\\section{Reactions}"):
        assert section in tex, f"LaTeX missing {section} [{model_name}]"
