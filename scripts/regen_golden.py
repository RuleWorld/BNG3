"""Regenerate committed golden reference outputs from the Perl oracle.

Golden files are the regression spine: tests load them instead of invoking Perl
on every run. This script is the *only* sanctioned way to (re)populate
tests/validation/golden/. It is run deliberately, reviewed, and committed —
never implicitly refreshed by the test suite. Scheduled tests may reuse the
ensemble generator with an explicit scratch destination and pinned oracle.

Usage:
    python scripts/regen_golden.py --tier p          # all on-disk compatible models
    python scripts/regen_golden.py --models blbr egfr_net
    python scripts/regen_golden.py --tier s                  # deterministic goldens

Requires BNG2_PERL to point into an explicitly checked-out, locked BNG2 oracle.
Create it with `python scripts/ci/checkout_oracle.py --name bionetgen
--destination /tmp/oracle-bionetgen`, then set BNG2_PERL to
`/tmp/oracle-bionetgen/bng2/BNG2.pl`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.validation import corpus, oracle_perl  # noqa: E402
from scripts.ci.oracle_sources import load_lock, load_oracle_source  # noqa: E402

GOLDEN = corpus.REPO / "tests" / "validation" / "golden"
ENSEMBLE_EVIDENCE = (
    corpus.REPO / "tests" / "validation" / "evidence" / "bng2-ssa-ensembles"
)
ENSEMBLE_T_END = 10
ENSEMBLE_N_STEPS = 50
ENSEMBLE_MIN_RUNS = 200


def ensemble_seeds(n_runs: int) -> list[int]:
    """Return the frozen ensemble seed contract: seeds ``1..n_runs``.

    The committed references (``tests/validation/golden/<model>.ens``) and
    their manifest record ``seed_range [1, 200]``, and
    ``tests/test_ci_contract.py`` checks that contract.  Regeneration keeps
    the same seeds so that a new reference can be compared member by member
    with the one it replaces.
    """
    if n_runs < 1:
        raise ValueError("ensemble requires at least one seed")
    return list(range(1, n_runs + 1))


# BNG2's run_network seeds the C library generator with srand(seed) and reads
# rand()/RAND_MAX.  On a C library whose first rand() after srand(seed) is a
# small multiple of the seed (the 16807 Lehmer generator of macOS libc), the
# consecutive seeds 1..200 give first uniforms below 0.002, which biases every
# member's first SSA draw.  glibc does not have that property.  The check below
# runs the generator of the C library on this host, the one run_network links,
# and refuses to generate references when the first draws are not uniform.
_FIRST_DRAW_UNIFORMITY_ALPHA = 1e-3


def _c_library_first_draws(seeds) -> tuple[list[float], str]:
    import ctypes
    import ctypes.util

    if sys.platform == "win32":
        library_name = "msvcrt"
        rand_max = 32767
    else:
        library_name = ctypes.util.find_library("c") or "libc.so.6"
        rand_max = 2147483647
    library = ctypes.CDLL(library_name)
    library.srand.argtypes = [ctypes.c_uint]
    library.srand.restype = None
    library.rand.argtypes = []
    library.rand.restype = ctypes.c_int
    draws = []
    for seed in seeds:
        library.srand(int(seed))
        draws.append(library.rand() / rand_max)
    return draws, library_name


def _uniform_ks_test(values) -> tuple[float, float]:
    """One-sample Kolmogorov-Smirnov statistic and asymptotic p-value for U(0, 1)."""

    ordered = sorted(min(max(float(value), 0.0), 1.0) for value in values)
    count = len(ordered)
    statistic = max(
        max((index + 1) / count - value, value - index / count)
        for index, value in enumerate(ordered)
    )
    # Kolmogorov's limiting distribution with Stephens' finite-sample scaling.
    root = math.sqrt(count)
    scaled = (root + 0.12 + 0.11 / root) * statistic
    if scaled < 1e-3:
        return statistic, 1.0
    pvalue = 2.0 * sum(
        (-1.0) ** (term - 1) * math.exp(-2.0 * term * term * scaled * scaled)
        for term in range(1, 101)
    )
    return statistic, min(max(pvalue, 0.0), 1.0)


def check_seed_first_draws(seeds, *, draws=None) -> dict:
    """Fail when the host C library's first draws over ``seeds`` are not uniform.

    ``draws`` replaces the host generator in tests.  The decision is a
    one-sample Kolmogorov-Smirnov test against U(0, 1) at a fixed level, so a
    generator whose first draws cluster near zero is rejected.
    """
    seed_list = list(seeds)
    library = "supplied"
    if draws is None:
        draws, library = _c_library_first_draws(seed_list)
    draws = [float(value) for value in draws]
    if len(draws) != len(seed_list):
        raise ValueError("one first draw is required per seed")
    statistic, pvalue = _uniform_ks_test(draws)
    summary = {
        "c_library": library,
        "platform": sys.platform,
        "seed_count": len(seed_list),
        "mean": sum(draws) / len(draws),
        "minimum": min(draws),
        "maximum": max(draws),
        "ks_statistic": statistic,
        "ks_pvalue": pvalue,
        "alpha": _FIRST_DRAW_UNIFORMITY_ALPHA,
    }
    if pvalue < _FIRST_DRAW_UNIFORMITY_ALPHA:
        raise RuntimeError(
            "the C library's first rand() after srand(seed) is not uniform over "
            f"seeds {seed_list[0]}..{seed_list[-1]} on {sys.platform} "
            f"(mean {summary['mean']:.6f}, KS p={pvalue:.3g}); run_network "
            "would give every reference member a biased first SSA draw. "
            "Generate the references on a host whose C library passes this "
            "check (glibc does)."
        )
    return summary


def ensemble_model_source(
    source_text: str, *, seeds, t_end: int | float, n_steps: int
) -> str:
    """Keep model definitions and replace fixture actions with seeded SSA runs."""
    end = re.search(r"(?im)^end model[ \t]*(?:\r?\n|$)", source_text)
    if end is None:
        end = re.search(r"(?im)^end reaction rules[ \t]*(?:\r?\n|$)", source_text)
    if end is None:
        raise ValueError("model source has no end model or end reaction rules")

    seed_list = list(seeds)
    if not seed_list or any(int(seed) < 1 for seed in seed_list):
        raise ValueError(
            "ensemble seeds must be a non-empty sequence of positive integers"
        )
    if len({int(seed) for seed in seed_list}) != len(seed_list):
        raise ValueError("ensemble seeds must be unique")
    if n_steps < 1 or t_end <= 0:
        raise ValueError("ensemble horizon and step count must be positive")

    t_end_text = str(int(t_end)) if float(t_end).is_integer() else repr(float(t_end))
    actions = ["## actions ##", "generate_network({overwrite=>1})"]
    for seed_value in seed_list:
        seed = int(seed_value)
        actions.extend(
            [
                "resetConcentrations()",
                (
                    f'simulate_ssa({{suffix=>"seed_{seed:04d}",seed=>{seed},'
                    f"t_start=>0,t_end=>{t_end_text},n_steps=>{n_steps}}})"
                ),
            ]
        )
    definitions = source_text[: end.end()].rstrip()
    return definitions + "\n\n" + "\n".join(actions) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bng2_oracle_identity(*, require_network: bool = False) -> dict:
    bng2 = oracle_perl._bng2_path()
    if bng2 is None:
        raise RuntimeError("Perl BNG2 not available (set BNG2_PERL)")
    helper_paths = {
        "BNG2.pl": bng2,
        "Perl2/BNGAction.pm": bng2.parent / "Perl2" / "BNGAction.pm",
    }
    if require_network:
        helper_paths["bin/run_network"] = bng2.parent / "bin" / "run_network"
    revision = None
    try:
        revision = subprocess.run(
            ["git", "-C", str(bng2.parent), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    expected_revision = load_oracle_source(load_lock(), "bionetgen")["revision"]
    if revision != expected_revision:
        raise RuntimeError(
            f"BNG2 oracle revision {revision or 'unknown'} does not match locked "
            f"revision {expected_revision}; run scripts/ci/checkout_oracle.py "
            "--name bionetgen and set BNG2_PERL to that checkout"
        )
    missing = [str(path) for path in helper_paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError("missing BNG2 oracle files: " + ", ".join(missing))
    return {
        "name": "Perl BNG2.pl plus run_network",
        "revision": revision,
        "BNG2_PERL": str(bng2.resolve()),
        "sha256": {name: _sha256(path) for name, path in helper_paths.items()},
    }


def _generate_ensemble(
    model_name: str,
    n_runs: int,
    identity: dict,
    *,
    destination_root: Path | None = None,
) -> dict:
    source = corpus.resolve(model_name)
    if source is None:
        raise RuntimeError(f"model {model_name!r} not on disk")
    source = Path(source).resolve()
    stem = source.stem
    source_text = source.read_text(encoding="utf-8")
    seeds = ensemble_seeds(n_runs)
    wrapper = ensemble_model_source(
        source_text,
        seeds=seeds,
        t_end=ENSEMBLE_T_END,
        n_steps=ENSEMBLE_N_STEPS,
    )
    bng2 = Path(identity["BNG2_PERL"])
    env = os.environ.copy()
    env["BNGPATH"] = str(bng2.parent)
    with tempfile.TemporaryDirectory(prefix=f"bng2-{stem}-ensemble-") as td:
        scratch = Path(td)
        wrapper_path = scratch / f"{stem}.bngl"
        output_dir = scratch / "out"
        output_dir.mkdir()
        wrapper_path.write_text(wrapper, encoding="utf-8")
        command = [
            os.environ.get("PERL", "perl"),
            str(bng2),
            "--outdir",
            str(output_dir),
            "--no-nfsim",
            str(wrapper_path),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=source.parent,
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"BNG2 timed out after 3600 seconds for {stem}") from exc
        if result.returncode:
            raise RuntimeError(
                f"BNG2 failed for {stem} (exit {result.returncode}):\n"
                + (result.stderr or result.stdout)
            )

        if destination_root is not None:
            root = Path(destination_root)
            root.mkdir(parents=True, exist_ok=True)
            (root / f"{stem}-wrapper.bngl").write_text(wrapper, encoding="utf-8")
            (root / f"{stem}-oracle.log").write_text(result.stdout + result.stderr)

        from tests.validation.compare import parse_gdat

        members = []
        expected = []
        runs = []
        for seed in seeds:
            output = output_dir / f"{stem}_seed_{seed:04d}.gdat"
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError(
                    f"BNG2 did not produce a valid member for seed {seed}"
                )
            data, columns = parse_gdat(output)
            if (
                data is None
                or columns is None
                or data.shape[0] != ENSEMBLE_N_STEPS + 1
                or not columns
            ):
                raise RuntimeError(f"invalid BNG2 ensemble member: {output.name}")
            runs.append((data, columns))
            expected.append(output)
            members.append(
                {
                    "path": f"seed_{seed:04d}.gdat",
                    "seed": seed,
                    "bytes": output.stat().st_size,
                    "sha256": _sha256(output),
                    "rows": int(data.shape[0]),
                    "columns": list(columns),
                }
            )
        unexpected = sorted(output_dir.glob(f"{stem}_seed_*.gdat"))
        if len(unexpected) != n_runs:
            raise RuntimeError(
                f"BNG2 produced {len(unexpected)} gdat members for {stem}; expected {n_runs}"
            )

        oracle_perl.qualify_model_ensemble(model_name, runs, label="BNG2 reference")
        root = GOLDEN if destination_root is None else Path(destination_root)
        destination = root / f"{stem}.ens"
        root.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{stem}.ens-", dir=root))
        backup = None
        try:
            for output, member in zip(expected, members):
                shutil.copy2(output, stage / member["path"])
            if destination.exists():
                backup = destination.with_name(f".{destination.name}-backup")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(destination, backup)
            os.replace(stage, destination)
        except Exception:
            if destination.exists() and backup is not None and backup.exists():
                shutil.rmtree(destination)
            if backup is not None and backup.exists():
                os.replace(backup, destination)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)

    aggregate = hashlib.sha256()
    for member in members:
        aggregate.update(f"{member['path']}\t{member['sha256']}\n".encode("utf-8"))
    return {
        "source_path": source.relative_to(corpus.REPO).as_posix(),
        "source_sha256": _sha256(source),
        "wrapper_sha256": hashlib.sha256(wrapper.encode("utf-8")).hexdigest(),
        "reference_path": (
            f"tests/validation/golden/{stem}.ens"
            if destination_root is None
            else str(destination.resolve())
        ),
        "seeds": seeds,
        "member_count": len(members),
        "aggregate_sha256": aggregate.hexdigest(),
        "members": members,
    }


def _write_ensemble_manifest(
    models: dict, identity: dict, n_runs: int, first_draws: dict | None = None
) -> None:
    ENSEMBLE_EVIDENCE.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "oracle": identity,
        "generation": {
            "method": "ssa",
            "t_start": 0,
            "t_end": ENSEMBLE_T_END,
            "n_steps": ENSEMBLE_N_STEPS,
            "seed_range": [1, n_runs],
            "reset_before_each_member": True,
            "command_template": [
                "perl",
                "<pinned BNG2_PERL>",
                "--outdir",
                "<scratch>/out",
                "--no-nfsim",
                "<scratch>/<model>.bngl",
            ],
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "models": models,
    }
    if first_draws is not None:
        manifest["generation"]["c_library_first_draws"] = first_draws
    path = ENSEMBLE_EVIDENCE / "manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def regen(models: list[str], ensemble: int) -> int:
    try:
        identity = _bng2_oracle_identity()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if ensemble:
        if ensemble < ENSEMBLE_MIN_RUNS:
            print(
                f"ERROR: ensemble generation requires at least {ENSEMBLE_MIN_RUNS} runs.",
                file=sys.stderr,
            )
            return 2
        if not oracle_perl.perl_available():
            print("ERROR: Perl BNG2 not available (set BNG2_PERL).", file=sys.stderr)
            return 2
        results = {}
        try:
            identity = _bng2_oracle_identity(require_network=True)
            first_draws = check_seed_first_draws(ensemble_seeds(ensemble))
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        for name in models:
            stem = Path(name).stem
            try:
                results[stem] = _generate_ensemble(name, ensemble, identity)
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"  FAIL {stem}: {exc}")
                continue
            print(f"  OK   {stem} ({ensemble} fixed-seed SSA members)")
        if results:
            _write_ensemble_manifest(results, identity, ensemble, first_draws)
        print(
            f"\n{len(results)}/{len(models)} ensembles regenerated into {GOLDEN}; "
            f"provenance: {ENSEMBLE_EVIDENCE / 'manifest.json'}"
        )
        return 0 if len(results) == len(models) else 1
    if not oracle_perl.perl_available():
        print("ERROR: Perl BNG2 not available (set BNG2_PERL).", file=sys.stderr)
        return 2
    GOLDEN.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for name in models:
        stem = Path(name).stem
        with tempfile.TemporaryDirectory() as td:
            net, gdat, err = oracle_perl.run_perl(name, Path(td))
            if net is None and gdat is None:
                print(f"  FAIL {stem}: {err}")
                continue
            if net is not None:
                shutil.copy2(net, GOLDEN / f"{stem}.net")
            if gdat is not None:
                shutil.copy2(gdat, GOLDEN / f"{stem}.gdat")
            print(
                f"  OK   {stem}  "
                f"({'net ' if net else ''}{'gdat' if gdat else ''})".rstrip()
            )
            n_ok += 1
    print(f"\n{n_ok}/{len(models)} models regenerated into {GOLDEN}")
    return 0 if n_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", choices=["s", "p", "nf", "expr"], default=None)
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument(
        "--ensemble",
        type=int,
        default=0,
        help="generate this many fixed-seed BNG2 SSA members per selected model (minimum 200)",
    )
    args = ap.parse_args()

    if args.models:
        models = args.models
    elif args.tier == "s":
        models = corpus.tier_s()
    elif args.tier == "nf":
        models = corpus.tier_nf()
    elif args.tier == "expr":
        models = corpus.tier_expr()
    else:
        models = corpus.tier_p()

    print(f"Regenerating golden for {len(models)} model(s)...")
    return regen(models, args.ensemble)


if __name__ == "__main__":
    raise SystemExit(main())
