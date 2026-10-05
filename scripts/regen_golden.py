"""Regenerate committed golden reference outputs from the Perl oracle.

Golden files are the regression spine: tests load them instead of invoking Perl
on every run. This script is the *only* sanctioned way to (re)populate
tests/validation/golden/. It is run deliberately, reviewed, and committed —
never invoked by the test suite.

Usage:
    python scripts/regen_golden.py --tier p          # all on-disk compatible models
    python scripts/regen_golden.py --models blbr egfr_net
    python scripts/regen_golden.py --tier s                  # deterministic goldens

Requires a working Perl BNG2 (set BNG2_PERL, or have legacy/perl/BNG2.pl present).
"""

from __future__ import annotations

import argparse
import hashlib
import json
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

GOLDEN = corpus.REPO / "tests" / "validation" / "golden"
ENSEMBLE_EVIDENCE = (
    corpus.REPO / "tests" / "validation" / "evidence" / "bng2-ssa-ensembles"
)
ENSEMBLE_T_END = 10
ENSEMBLE_N_STEPS = 50
ENSEMBLE_MIN_RUNS = 200


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


def _ensemble_oracle_identity() -> dict:
    bng2 = oracle_perl._bng2_path()
    if bng2 is None:
        raise RuntimeError("Perl BNG2 not available (set BNG2_PERL)")
    helper_paths = {
        "BNG2.pl": bng2,
        "Perl2/BNGAction.pm": bng2.parent / "Perl2" / "BNGAction.pm",
        "bin/run_network": bng2.parent / "bin" / "run_network",
    }
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
    missing = [str(path) for path in helper_paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError("missing BNG2 oracle files: " + ", ".join(missing))
    return {
        "name": "Perl BNG2.pl plus run_network",
        "revision": revision,
        "BNG2_PERL": str(bng2.resolve()),
        "sha256": {name: _sha256(path) for name, path in helper_paths.items()},
    }


def _generate_ensemble(model_name: str, n_runs: int, identity: dict) -> dict:
    source = corpus.resolve(model_name)
    if source is None:
        raise RuntimeError(f"model {model_name!r} not on disk")
    source = Path(source).resolve()
    stem = source.stem
    source_text = source.read_text(encoding="utf-8")
    wrapper = ensemble_model_source(
        source_text,
        seeds=range(1, n_runs + 1),
        t_end=ENSEMBLE_T_END,
        n_steps=ENSEMBLE_N_STEPS,
    )
    bng2 = Path(identity["BNG2_PERL"])
    env = os.environ.copy()
    env.setdefault("BNGPATH", str(bng2.parent))
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

        from tests.validation.compare import parse_gdat

        members = []
        expected = []
        for seed in range(1, n_runs + 1):
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

        destination = GOLDEN / f"{stem}.ens"
        GOLDEN.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f".{stem}.ens-", dir=GOLDEN))
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
        "reference_path": f"tests/validation/golden/{stem}.ens",
        "member_count": len(members),
        "aggregate_sha256": aggregate.hexdigest(),
        "members": members,
    }


def _write_ensemble_manifest(models: dict, identity: dict, n_runs: int) -> None:
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
    path = ENSEMBLE_EVIDENCE / "manifest.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def regen(models: list[str], ensemble: int) -> int:
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
        try:
            identity = _ensemble_oracle_identity()
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        results = {}
        for name in models:
            stem = Path(name).stem
            try:
                results[stem] = _generate_ensemble(name, ensemble, identity)
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"  FAIL {stem}: {exc}")
                continue
            print(f"  OK   {stem} ({ensemble} fixed-seed SSA members)")
        if results:
            _write_ensemble_manifest(results, identity, ensemble)
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
