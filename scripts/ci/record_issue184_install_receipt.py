"""Install actual BNG3 wheel/sdist artifacts in an isolated venv and emit #184 receipts."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CPU_EXTRAS = ("legacy", "plotting", "jax", "notebook", "full")
EXTRA_IMPORTS: dict[str, tuple[str, ...]] = {
    "legacy": ("cement", "colorlog", "pyparsing", "pylru"),
    "plotting": ("pandas", "matplotlib"),
    "jax": ("jax", "jaxlib"),
    "notebook": ("ipykernel", "matplotlib"),
    "full": (
        "cement",
        "colorlog",
        "pyparsing",
        "pylru",
        "pandas",
        "matplotlib",
        "seaborn",
        "xmltodict",
        "yaml",
        "lxml",
        "networkx",
        "libsbml",
        "sympy",
    ),
}


def detect_platform() -> str:
    """Return normalized declared #184 platform family for current host."""
    raw = sys.platform.lower()
    if raw.startswith("linux"):
        return "linux"
    if raw == "darwin":
        return "macos"
    if raw.startswith(("win", "cygwin")):
        return "windows"
    return raw


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_wheel_record(zf: zipfile.ZipFile, names: list[str]) -> list[str]:
    """Verify every hashed entry in dist-info/RECORD matches its zip content."""
    errors: list[str] = []
    record_names = [n for n in names if n.endswith(".dist-info/RECORD")]
    if len(record_names) != 1:
        return [f"expected 1 RECORD file, found {len(record_names)}"]
    record_name = record_names[0]
    rows = list(
        csv.reader(io.StringIO(zf.read(record_name).decode("utf-8", "replace")))
    )
    if not rows:
        return ["empty RECORD file"]
    present = set(names)
    for row in rows:
        if not row or not row[0]:
            continue
        member = row[0]
        if member not in present:
            errors.append(f"RECORD references missing member: {member}")
            continue
        hash_spec = row[1] if len(row) > 1 else ""
        size_spec = row[2] if len(row) > 2 else ""
        if member == record_name:
            continue
        if not hash_spec.startswith("sha256="):
            errors.append(f"RECORD member missing sha256 digest: {member}")
            continue
        raw = zf.read(member)
        expected_b64 = hash_spec.split("=", 1)[1]
        actual_b64 = (
            base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
            .decode("ascii")
            .rstrip("=")
        )
        if actual_b64 != expected_b64:
            errors.append(f"RECORD sha256 mismatch for {member}")
        if size_spec and int(size_spec) != len(raw):
            errors.append(f"RECORD size mismatch for {member}")
    return errors


def inspect_wheel_archive(path: Path) -> dict[str, Any]:
    """Inspect a built wheel archive for metadata, LICENSE, NOTICE, and RECORD."""
    resolved = path.resolve()
    with zipfile.ZipFile(resolved) as zf:
        names = zf.namelist()
        meta_names = [n for n in names if n.endswith(".dist-info/METADATA")]
        meta_text = (
            zf.read(meta_names[0]).decode("utf-8", "replace") if meta_names else ""
        )
        dist_name = ""
        dist_version = ""
        provides_extras: list[str] = []
        license_header = ""
        for line in meta_text.splitlines():
            if line.startswith("Name:") and not dist_name:
                dist_name = line.split(":", 1)[1].strip()
            elif line.startswith("Version:") and not dist_version:
                dist_version = line.split(":", 1)[1].strip()
            elif line.startswith("Provides-Extra:"):
                provides_extras.append(line.split(":", 1)[1].strip())
            elif (
                line.startswith(("License:", "License-Expression:"))
                and not license_header
            ):
                license_header = line.split(":", 1)[1].strip()
        license_entries = sorted(
            n
            for n in names
            if n.endswith("/licenses/LICENSE") or n.endswith(".dist-info/LICENSE")
        )
        notice_entries = sorted(n for n in names if "notice" in Path(n).name.lower())
        native_entries = sorted(
            n for n in names if n.endswith((".so", ".pyd", ".dll", ".dylib"))
        )
        record_errors = _verify_wheel_record(zf, names)
    return {
        "kind": "wheel",
        "filename": resolved.name,
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
        "name": dist_name,
        "version": dist_version,
        "license_header": license_header,
        "provides_extras": provides_extras,
        "license_entries": license_entries,
        "notice_entries": notice_entries,
        "native_entries": native_entries,
        "record_errors": record_errors,
    }


def inspect_sdist_archive(path: Path) -> dict[str, Any]:
    """Inspect a source distribution tarball for PKG-INFO, LICENSE, and NOTICE files."""
    resolved = path.resolve()
    with tarfile.open(resolved, "r:gz") as tf:
        names = tf.getnames()
        pkg_infos = [n for n in names if n.count("/") == 1 and n.endswith("/PKG-INFO")]
        pkg_text = (
            tf.extractfile(pkg_infos[0]).read().decode("utf-8", "replace")
            if pkg_infos and tf.extractfile(pkg_infos[0]) is not None
            else ""
        )
        dist_name = ""
        dist_version = ""
        provides_extras: list[str] = []
        license_header = ""
        for line in pkg_text.splitlines():
            if line.startswith("Name:") and not dist_name:
                dist_name = line.split(":", 1)[1].strip()
            elif line.startswith("Version:") and not dist_version:
                dist_version = line.split(":", 1)[1].strip()
            elif line.startswith("Provides-Extra:"):
                provides_extras.append(line.split(":", 1)[1].strip())
            elif (
                line.startswith(("License:", "License-Expression:"))
                and not license_header
            ):
                license_header = line.split(":", 1)[1].strip()
        license_entries = sorted(
            n
            for n in names
            if (n.count("/") == 1 and Path(n).name == "LICENSE")
            or Path(n).name.startswith("LICENSE")
        )
        notice_entries = sorted(n for n in names if "notice" in Path(n).name.lower())
    return {
        "kind": "sdist",
        "filename": resolved.name,
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
        "name": dist_name,
        "version": dist_version,
        "license_header": license_header,
        "provides_extras": provides_extras,
        "license_entries": license_entries,
        "notice_entries": notice_entries,
        "record_errors": [],
    }


def inspect_archive_inventory(
    *, wheel_dirs: list[Path] | None = None, sdist_path: Path | None = None
) -> dict[str, Any]:
    """Inspect all supplied wheels and optional sdist archive."""
    wheels = [
        inspect_wheel_archive(w)
        for d in (wheel_dirs or [])
        for w in sorted(d.resolve().glob("*.whl"))
    ]
    sdist = inspect_sdist_archive(sdist_path) if sdist_path is not None else None
    all_archives = list(wheels) + ([sdist] if sdist is not None else [])
    seen_names: set[str] = set()
    collisions: list[str] = []
    for item in all_archives:
        if item["filename"] in seen_names:
            collisions.append(item["filename"])
        seen_names.add(item["filename"])
    return {
        "wheels": wheels,
        "sdist": sdist,
        "wheel_count": len(wheels),
        "collisions": collisions,
    }


def _select_host_wheel(wheels: list[Path]) -> Path:
    tag = f"-cp{sys.version_info.major}{sys.version_info.minor}-"
    matches = [w for w in wheels if tag in w.name]
    if not matches:
        raise RuntimeError(
            f"no wheel matching {tag} found in {[w.name for w in wheels]}"
        )
    if len(matches) == 1:
        return matches[0]
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        arm_matches = [w for w in matches if "arm64" in w.name or "aarch64" in w.name]
        if arm_matches:
            return arm_matches[0]
    if machine in ("x86_64", "amd64"):
        x64_matches = [w for w in matches if "x86_64" in w.name or "amd64" in w.name]
        if x64_matches:
            return x64_matches[0]
    return matches[0]


def validate_truthful_gpu_metadata(payload: dict[str, Any]) -> tuple[bool, str]:
    """Validate GPU availability metadata reports compiled vs device routes truthfully."""
    caps = payload.get("gpu_backend_capabilities")
    backends = payload.get("gpu_backends")
    default_backend = payload.get("default_gpu_backend")
    if not isinstance(caps, list) or not caps or not isinstance(backends, list):
        return False, "gpu_backend_capabilities() or gpu_backends() invalid"
    if not isinstance(default_backend, str):
        return False, "default_gpu_backend() invalid"
    cap_names = {c.get("name") for c in caps if isinstance(c, dict)}
    back_names = {b.get("name") for b in backends if isinstance(b, dict)}
    if {"cuda", "metal"} - cap_names or {"cuda", "metal"} - back_names:
        return (
            False,
            f"expected cuda and metal entries, got caps={sorted(cap_names)} backends={sorted(back_names)}",
        )
    available_names: set[str] = set()
    route_summary: dict[str, list[str]] = {}
    for entry in caps:
        if not isinstance(entry, dict):
            return False, "invalid capability entry"
        name = str(entry.get("name", ""))
        compiled = entry.get("compiled")
        available = entry.get("available")
        routes = entry.get("implemented_routes")
        if (
            not isinstance(compiled, bool)
            or not isinstance(available, bool)
            or not isinstance(routes, list)
        ):
            return False, f"malformed capability metadata for {name}: {entry}"
        if not compiled and (available or routes):
            return (
                False,
                f"uncompiled backend {name} must not report available or routes: {entry}",
            )
        if available:
            available_names.add(name)
        if (
            compiled
            and name == "metal"
            and not (
                "finite_batch_ssa" in routes and "nfnext_unary_state_change" in routes
            )
        ):
            return (
                False,
                f"compiled metal routes must separate batch_ssa and nfnext: {routes}",
            )
        route_summary[name] = [str(r) for r in routes]
    if default_backend != "none" and default_backend not in available_names:
        return (
            False,
            f"default_gpu_backend={default_backend!r} not in available={sorted(available_names)}",
        )
    if payload.get("gpu_qualified_by_this_receipt") is not False:
        return False, "CPU install receipt must not claim GPU qualification"
    if payload.get("gpu_scope_deferred_to") != "#474":
        return False, "GPU scope deferral must explicitly reference #474"
    return (
        True,
        f"backends={route_summary}, available={sorted(available_names)}, default={default_backend!r}, gpu_scope=#474",
    )


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_cli(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "bionetgen.exe"
    return venv_dir / "bin" / "bionetgen"


def _guide_parameter_scan_snippet(root: Path) -> tuple[str, str]:
    text = (root / "docs" / "migration_guide.md").read_text(encoding="utf-8")
    section = re.search(
        r"^### Parameter Scans\n(.*?)(?=^##(?:#)? |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if section is None:
        raise RuntimeError(
            "docs/migration_guide.md missing '### Parameter Scans' section"
        )
    bngl = re.findall(r"```bngl\n(.*?)```", section.group(1), re.DOTALL)
    py = re.findall(r"```python\n(.*?)```", section.group(1), re.DOTALL)
    if not bngl or not py:
        raise RuntimeError(
            "docs/migration_guide.md '### Parameter Scans' missing fenced code"
        )
    return bngl[-1], py[-1]


def _run_clean_env(
    cmd: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def _execute_installed_probe(
    venv_py: Path,
    venv_cli: Path,
    root: Path,
    revision: str,
    requested_extras: list[str],
) -> dict[str, Any]:
    root = root.resolve()
    bngl_text, py_example = _guide_parameter_scan_snippet(root)
    with tempfile.TemporaryDirectory(prefix="bng3-184-probe-") as tmp:
        work = Path(tmp)
        model_path = work / "model.bngl"
        model_path.write_text(bngl_text, encoding="utf-8")
        probe_out = work / "probe_result.json"

        identity_proc = _run_clean_env(
            [
                str(venv_py),
                str(root / "scripts" / "ci" / "check_python_package_identity.py"),
                "--source-revision",
                revision,
            ],
            cwd=work,
        )
        if identity_proc.returncode != 0:
            raise RuntimeError(
                f"package identity failed: {identity_proc.stderr or identity_proc.stdout}"
            )
        identity = json.loads(identity_proc.stdout)

        cli_ver = _run_clean_env([str(venv_cli), "--version"], cwd=work)
        cli_help = _run_clean_env([str(venv_cli), "--help"], cwd=work)
        cli_chk = _run_clean_env([str(venv_cli), "check", str(model_path)], cwd=work)
        ode_dir = work / "cli_ode"
        cli_ode = _run_clean_env(
            [
                str(venv_cli),
                "run",
                "-i",
                str(model_path),
                "-m",
                "ode",
                "--t-end",
                "2.0",
                "--n-steps",
                "10",
                "-o",
                str(ode_dir),
            ],
            cwd=work,
        )
        if any(p.returncode != 0 for p in (cli_ver, cli_help, cli_chk, cli_ode)):
            raise RuntimeError(
                "CLI probe failed: "
                f"ver={cli_ver.returncode} help={cli_help.returncode} "
                f"chk={cli_chk.returncode} ode={cli_ode.returncode} "
                f"stderr={cli_ode.stderr or cli_chk.stderr}"
            )

        probe_script = work / "probe_installed.py"
        probe_script.write_text(
            """\
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import bionetgen

work = Path(sys.argv[1])
model_path = Path(sys.argv[2])
guide_py = Path(sys.argv[3]).read_text(encoding="utf-8")
requested_extras = json.loads(sys.argv[4])
extra_imports = json.loads(sys.argv[5])
out_file = Path(sys.argv[6])

ns = {"__name__": "__migration_guide_example__"}
exec(compile(guide_py, "docs/migration_guide.md", "exec"), ns)
scan = ns["scan"]
endpoints = [float(x) for x in scan.final("A_total")]
expected = [100.0 * math.exp(-0.1 * 2.0), 100.0 * math.exp(-1.0 * 2.0)]
if not all(
    math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    for a, b in zip(endpoints, expected)
):
    raise AssertionError(f"guide scan endpoints mismatch: {endpoints} != {expected}")

m = bionetgen.bngmodel(str(model_path))
modern_ode = bionetgen.run(model_path, method="ode", t_end=2.0, n_steps=10)
compat_dir = work / "compat_out"
compat_res = bionetgen.run(
    model_path, out=compat_dir, method="ode", t_span=(0.0, 2.0), n_points=11
)
compat_gdat = compat_res.gdats[model_path.stem]
ssa_res = bionetgen.run(model_path, method="ssa", t_end=2.0, n_steps=10, seed=42)
nf_res = bionetgen.run(model_path, method="nf", t_end=2.0, n_steps=10, seed=42)

ssa_vals = [float(x) for x in ssa_res.observables["A_total"]]
nf_vals = [float(x) for x in nf_res.observables["A_total"]]
if not (ssa_vals[0] == 100.0 and 0.0 <= ssa_vals[-1] <= 100.0):
    raise AssertionError(f"SSA decay out of bounds: {ssa_vals}")
if not (nf_vals[0] == 100.0 and 0.0 <= nf_vals[-1] <= 100.0):
    raise AssertionError(f"NF decay out of bounds: {nf_vals}")

imported_extras = {}
for extra in requested_extras:
    mods = extra_imports.get(extra, [])
    for mod in mods:
        __import__(mod)
    imported_extras[extra] = list(mods)

out_file.write_text(
    json.dumps(
        {
            "version": bionetgen.__version__,
            "package_file": str(Path(bionetgen.__file__).resolve()),
            "model_param_count": len(list(m.parameters)),
            "guide_scan_endpoints": endpoints,
            "guide_scan_expected": expected,
            "modern_ode_final": float(modern_ode.observables["A_total"][-1]),
            "compat_gdat_len": len(compat_gdat),
            "ssa_final": ssa_vals[-1],
            "nf_final": nf_vals[-1],
            "imported_extras": imported_extras,
            "gpu_backend_capabilities": bionetgen.gpu_backend_capabilities(),
            "gpu_backends": bionetgen.gpu_backends(),
            "default_gpu_backend": bionetgen.default_gpu_backend(),
            "gpu_qualified_by_this_receipt": False,
            "gpu_scope_deferred_to": "#474",
        }
    ),
    encoding="utf-8",
)
""",
            encoding="utf-8",
        )
        guide_py_file = work / "guide_scan.py"
        guide_py_file.write_text(py_example, encoding="utf-8")
        py_probe = _run_clean_env(
            [
                str(venv_py),
                str(probe_script),
                str(work),
                str(model_path),
                str(guide_py_file),
                json.dumps(requested_extras),
                json.dumps(EXTRA_IMPORTS),
                str(probe_out),
            ],
            cwd=work,
        )
        if py_probe.returncode != 0 or not probe_out.is_file():
            raise RuntimeError(
                f"Python installed probe failed:\n{py_probe.stdout}\n{py_probe.stderr}"
            )
        probe_data = json.loads(probe_out.read_text(encoding="utf-8"))
        probe_data["identity"] = identity
        probe_data["cli_version"] = cli_ver.stdout.strip()
        return probe_data


def _result_row(check_id: str, ok: bool, detail: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "PASS" if ok else "FAIL",
        "evidence_kind": "supported-execution",
        "supported_execution": ok,
        "related_issues": [184],
        "detail": detail,
    }


def _declared_cpu_extras_ok(root: Path) -> tuple[bool, list[str]]:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    missing = [
        extra
        for extra in CPU_EXTRAS
        if not re.search(rf"^{extra}\s*=\s*\[", text, re.M)
    ]
    has_gpu = bool(re.search(r"^gpu\s*=\s*\[", text, re.M))
    return (not missing and not has_gpu), missing


def _build_receipt(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = args.root.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain"], text=True
    ).strip()
    if head != args.revision or (dirty and not args.allow_dirty):
        raise RuntimeError(
            "install receipt requires a clean checkout matching --revision"
        )

    wheel_dirs = [d.resolve() for d in (args.wheel_dir or [])]
    sdist_path = (
        args.artifact.resolve()
        if args.artifact and args.artifact.name.endswith(".tar.gz")
        else None
    )
    inv = inspect_archive_inventory(wheel_dirs=wheel_dirs, sdist_path=sdist_path)

    if args.artifact is not None:
        target_artifact = args.artifact.resolve()
        if target_artifact.suffix == ".whl":
            target_info = inspect_wheel_archive(target_artifact)
            if not any(w["path"] == target_info["path"] for w in inv["wheels"]):
                inv["wheels"].append(target_info)
                inv["wheel_count"] = len(inv["wheels"])
        elif target_artifact.name.endswith(".tar.gz"):
            target_info = inv["sdist"] or inspect_sdist_archive(target_artifact)
        else:
            raise RuntimeError(f"unsupported artifact extension: {target_artifact}")
    elif inv["wheels"]:
        target_artifact = _select_host_wheel([Path(w["path"]) for w in inv["wheels"]])
        target_info = next(
            w for w in inv["wheels"] if w["path"] == str(target_artifact)
        )
    else:
        raise RuntimeError("provide --artifact or --wheel-dir with at least one wheel")

    extras = [e.strip() for e in (args.extras or "").split(",") if e.strip()]
    install_target = (
        f"{target_artifact}[{','.join(extras)}]" if extras else str(target_artifact)
    )
    extra_build_env = {"CMAKE_ARGS": "-DBUILD_TESTS=OFF -DBUILD_CLI=OFF"}
    if sys.platform == "darwin" and os.environ.get("MACOSX_DEPLOYMENT_TARGET"):
        extra_build_env["MACOSX_DEPLOYMENT_TARGET"] = os.environ[
            "MACOSX_DEPLOYMENT_TARGET"
        ]

    probe_before: dict[str, Any] = {}
    probe_after: dict[str, Any] = {}
    upgrade_ok = False
    clean_ok = False
    clean_err = ""
    upgrade_err = ""

    if args.skip_install_probe:
        clean_err = "skipped install probe (--skip-install-probe)"
        upgrade_err = clean_err
    else:
        with tempfile.TemporaryDirectory(prefix="bng3-184-venv-") as tmp_venv:
            venv_dir = Path(tmp_venv) / "venv"
            venv.EnvBuilder(with_pip=True).create(venv_dir)
            venv_py = _venv_python(venv_dir)
            venv_cli = _venv_cli(venv_dir)
            pip_base = [str(venv_py), "-m", "pip", "install", "--no-cache-dir"]
            if args.no_index:
                pip_base.append("--no-index")
                if args.find_links:
                    pip_base.extend(["--find-links", str(args.find_links.resolve())])
            inst = _run_clean_env(
                [*pip_base, install_target],
                cwd=venv_dir.parent,
                extra_env=extra_build_env,
            )
            if inst.returncode != 0:
                clean_err = f"pip install failed: {inst.stderr or inst.stdout}"
            else:
                try:
                    probe_before = _execute_installed_probe(
                        venv_py, venv_cli, root, args.revision, extras
                    )
                    clean_ok = True
                except (
                    RuntimeError,
                    AssertionError,
                    json.JSONDecodeError,
                    OSError,
                ) as exc:
                    clean_err = str(exc)

            if clean_ok:
                upg_cmd = [
                    str(venv_py),
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--upgrade",
                    "--force-reinstall",
                    "--no-deps",
                    str(target_artifact),
                ]
                upg = _run_clean_env(
                    upg_cmd, cwd=venv_dir.parent, extra_env=extra_build_env
                )
                if upg.returncode != 0:
                    upgrade_err = f"pip upgrade failed: {upg.stderr or upg.stdout}"
                else:
                    try:
                        probe_after = _execute_installed_probe(
                            venv_py, venv_cli, root, args.revision, extras
                        )
                        before_ext = probe_before["identity"]["native_extension_sha256"]
                        after_ext = probe_after["identity"]["native_extension_sha256"]
                        upgrade_ok = bool(before_ext and before_ext == after_ext)
                        if not upgrade_ok:
                            upgrade_err = (
                                f"native extension hash changed on upgrade: "
                                f"{before_ext} != {after_ext}"
                            )
                    except (
                        RuntimeError,
                        AssertionError,
                        json.JSONDecodeError,
                        OSError,
                    ) as exc:
                        upgrade_err = str(exc)

    all_inspected = list(inv["wheels"]) + ([inv["sdist"]] if inv["sdist"] else [])
    archive_ok = (
        bool(all_inspected)
        and not inv["collisions"]
        and all(
            item["license_entries"] and item["version"] and not item["record_errors"]
            for item in all_inspected
        )
    )
    extras_decl_ok, missing_extras = _declared_cpu_extras_ok(root)
    extras_runtime_ok = all(
        extra in probe_before.get("imported_extras", {}) for extra in extras
    )
    extras_ok = extras_decl_ok and (not extras or extras_runtime_ok) and clean_ok

    gpu_ok, gpu_detail = (
        validate_truthful_gpu_metadata(probe_before)
        if probe_before
        else (False, "no installed GPU metadata probed")
    )

    plat = args.platform or detect_platform()
    results = [
        _result_row(
            "clean_install",
            clean_ok,
            (
                (
                    f"{target_info['filename']} sha256={target_info['sha256'][:12]} "
                    f"version={probe_before.get('version')}"
                )
                if clean_ok
                else clean_err
            ),
        ),
        _result_row(
            "upgrade_path",
            upgrade_ok,
            (
                (
                    f"--upgrade --force-reinstall preserved native_sha256="
                    f"{probe_after.get('identity', {}).get('native_extension_sha256', '')[:12]}"
                )
                if upgrade_ok
                else upgrade_err
            ),
        ),
        _result_row(
            "cli_execution",
            clean_ok and bool(probe_before.get("cli_version")),
            probe_before.get("cli_version", clean_err),
        ),
        _result_row(
            "compat_api_execution",
            clean_ok and probe_before.get("compat_gdat_len", 0) == 11,
            f"compat_gdat_len={probe_before.get('compat_gdat_len', 0)}",
        ),
        _result_row(
            "public_examples",
            clean_ok and len(probe_before.get("guide_scan_endpoints", [])) == 2,
            f"docs/migration_guide.md Parameter Scans endpoints={probe_before.get('guide_scan_endpoints')}",
        ),
        _result_row(
            "representative_cpu_workloads",
            clean_ok
            and all(
                k in probe_before for k in ("modern_ode_final", "ssa_final", "nf_final")
            ),
            f"ode={probe_before.get('modern_ode_final')} ssa={probe_before.get('ssa_final')} nf={probe_before.get('nf_final')}",
        ),
        _result_row(
            "cpu_extras",
            extras_ok,
            f"declared={list(CPU_EXTRAS)}, installed_verified={extras}, missing_decl={missing_extras}",
        ),
        _result_row("truthful_gpu_metadata", gpu_ok, gpu_detail),
        _result_row(
            "archive_inventory",
            archive_ok,
            f"archives={len(all_inspected)} collisions={len(inv['collisions'])}",
        ),
    ]

    report = {
        "schema_version": 1,
        "check_id": "issue184-install-receipt",
        "source": {"revision": args.revision, "dirty": False},
        "references": {
            "platform": plat,
            "sys_platform": sys.platform,
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "artifact_kind": target_info["kind"],
            "artifact_name": target_info["filename"],
            "artifact_sha256": target_info["sha256"],
            "distribution_version": target_info["version"],
            "native_extension_sha256": probe_before.get("identity", {}).get(
                "native_extension_sha256"
            ),
            "extras_verified": extras,
            "gpu_scope_deferred_to": "#474",
            "gpu_qualified_by_this_receipt": False,
        },
        "archive_inventory": inv,
        "installed_probe": probe_before,
        "results": results,
    }
    return report, int(any(r["status"] != "PASS" for r in results))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--platform", default=None)
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument("--wheel-dir", type=Path, action="append", default=[])
    parser.add_argument("--extras", default="")
    parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--find-links", type=Path, default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--skip-install-probe", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report, code = _build_receipt(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report["results"]:
        print(f"{row['id']}: {row['status']} ({row['detail'][:90]})")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
