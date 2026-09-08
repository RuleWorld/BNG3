"""Explicit PyBioNetGen-compatible file runner backed by BNG3."""

from __future__ import annotations

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from bionetgen.core.exc import BNGError
from bionetgen.core.tools.result import BNGResult


def _run_in_directory(
    inp: Path,
    output: Path,
    *,
    suppress: bool,
    method: str | None,
    timeout: int | None,
) -> BNGResult:
    if inp.suffix.lower() != ".bngl":
        raise NotImplementedError(
            "The BNG3 compatibility runner currently accepts BNGL input only"
        )
    if method is not None:
        raise NotImplementedError(
            "method overrides are not supported by the compatibility runner; "
            "edit the model actions or use load(...).simulate(...)"
        )
    if timeout is not None:
        raise NotImplementedError(
            "timeout is not supported by the in-process BNG3 compatibility runner"
        )

    output.mkdir(parents=True, exist_ok=True)
    copied = output / inp.name
    if copied.resolve() != inp.resolve():
        shutil.copy2(inp, copied)

    try:
        from bionetgen import _bionetgen_cpp as cpp
    except ImportError as exc:
        raise BNGError(
            "The BNG3 C++ backend is required for bionetgen.run(input, out)"
        ) from exc

    try:
        model = cpp.parse_file(str(copied))
        cpp.execute(model, str(copied), verbose=not suppress)
    except Exception as exc:
        raise BNGError(f"BNG3 failed while running {inp}: {exc}") from exc

    result = BNGResult(path=str(output))
    result.process_return = 0
    result.output = ["Ran successfully via BNG3"]
    return result


def run(
    inp,
    out=None,
    suppress=False,
    timeout=None,
    simulator="auto",
    format=None,
    method=None,
    t_span=None,
    n_points=None,
    t_end=100.0,
    n_steps=100,
    **kwargs,
):
    """Run a BNGL file into a PyBioNetGen-style result directory.

    This first compatibility slice intentionally preserves the input model's
    declared actions. Unsupported legacy options fail explicitly rather than
    silently selecting a different simulator or output contract.
    """
    if kwargs:
        names = ", ".join(sorted(kwargs))
        raise TypeError(f"unsupported compatibility runner option(s): {names}")
    if simulator != "auto":
        raise NotImplementedError(
            "only simulator='auto' is supported by the BNG3 compatibility runner"
        )
    if format not in (None, "bngl"):
        raise NotImplementedError(
            "only BNGL input is supported by the BNG3 compatibility runner"
        )
    if t_span is not None or n_points is not None:
        raise NotImplementedError(
            "t_span/n_points overrides are not supported while preserving actions"
        )
    if t_end != 100.0 or n_steps != 100:
        raise NotImplementedError(
            "t_end/n_steps overrides are not supported while preserving actions"
        )

    inp_path = Path(inp).expanduser().resolve()
    if not inp_path.is_file():
        raise FileNotFoundError(inp_path)

    if out is None:
        with TemporaryDirectory(prefix="bionetgen-run-") as temp:
            return _run_in_directory(
                inp_path,
                Path(temp),
                suppress=suppress,
                method=method,
                timeout=timeout,
            )

    output = Path(out).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(output)
    return _run_in_directory(
        inp_path,
        output,
        suppress=suppress,
        method=method,
        timeout=timeout,
    )
