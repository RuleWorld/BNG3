"""Spawned API workers must keep the package selected by test mode."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import multiprocessing
from pathlib import Path

from tests.validation import runner


def _native_identity() -> tuple[str, str, str, str]:
    runner._ensure_source_python_path()
    import bionetgen
    import bionetgen.model as model
    import bionetgen._bionetgen_cpp as package_native

    model_native = model._cpp
    assert model_native is not None
    package_path = Path(bionetgen.__file__).resolve()
    package_native_path = Path(package_native.__file__).resolve()
    model_native_path = Path(model_native.__file__).resolve()
    return (
        str(package_path),
        str(package_native_path),
        hashlib.sha256(package_native_path.read_bytes()).hexdigest(),
        str(model_native_path),
    )


def test_spawned_api_worker_uses_the_selected_package_and_native_extension():
    parent = _native_identity()
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
        child = pool.submit(_native_identity).result()

    assert child == parent
    assert parent[1] == parent[3]
