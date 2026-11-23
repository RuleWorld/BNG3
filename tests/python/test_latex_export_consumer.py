"""The LaTeX export must be consumed by a real LaTeX engine.

Regression: the writer emitted ``\\varnothing`` while omitting the
``amssymb`` package, so ``pdflatex`` failed on every generated document. The
preamble assertion runs everywhere; actual compilation runs when a TeX engine
is available.
"""

from __future__ import annotations

import shutil

import pytest
from _extdep import require_extension

require_extension()
import bionetgen

MODEL = """begin model
begin parameters
  k 0.1
end parameters
begin molecule types
  A()
end molecule types
begin seed species
  A() 10
end seed species
begin observables
  Molecules A_obs A()
end observables
begin reaction rules
  decay: A() -> 0 k
end reaction rules
end model
"""


def test_exported_latex_compiles(tmp_path):
    source = tmp_path / "m.bngl"
    source.write_text(MODEL)
    model = bionetgen.load(str(source))
    model.generate_network()
    tex = tmp_path / "m.tex"
    model.write_latex(str(tex))

    preamble = tex.read_text().splitlines()[:12]
    assert any(r"\usepackage{amsmath}" in line for line in preamble)
    # \varnothing is an amssymb symbol; without the package pdflatex fails.
    assert any(r"\usepackage{amssymb}" in line for line in preamble)

    engine = shutil.which("pdflatex")
    if engine is None:
        pytest.skip("pdflatex is not installed")
    import subprocess

    result = subprocess.run(
        [engine, "-interaction=nonstopmode", "-halt-on-error", "m.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "m.pdf").is_file()
