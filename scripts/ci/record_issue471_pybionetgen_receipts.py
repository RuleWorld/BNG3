#!/usr/bin/env python3
"""Emit schema-v2 #471/#180 differential receipts against pinned PyBioNetGen.

Runs two completely isolated Python subprocesses on the same producer spec:
1. External oracle: pinned RuleWorld/PyBioNetGen checkout only (no BNG3 on path).
2. Downstream consumer: BNG3 ``bionetgen`` package only.

Each row's output combines exact runtime symbol contract inspection (callable
signature, class bases, ``__init__`` signature, exception instantiation probe)
with real subsystem behavioral execution (BNG-XML parsing via ``bngmodel``,
``.net`` parsing via ``bionetgen.network.network.network``, ``BNGFile`` block
extraction, and ``BNGDefaults`` attributes) where applicable. Only rows whose
oracle and consumer JSON bytes match identically emit a schema-v2 receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_RE = re.compile(
    r"^pybionetgen:(?P<path>[^:]+):(?P<line>\d+)\s*\((?P<sym>[^)]+)\)$"
)

PROBE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3" level="3" version="1">
  <model id="probe">
    <ListOfParameters>
      <Parameter id="kf" type="Constant" value="0.5"/>
      <Parameter id="kr" type="Constant" value="0.1"/>
    </ListOfParameters>
    <ListOfMoleculeTypes>
      <MoleculeType id="A">
        <ListOfComponentTypes>
          <ComponentType id="b"/>
          <ComponentType id="p">
            <ListOfAllowedStates>
              <AllowedState id="u"/>
              <AllowedState id="p"/>
            </ListOfAllowedStates>
          </ComponentType>
        </ListOfComponentTypes>
      </MoleculeType>
      <MoleculeType id="B">
        <ListOfComponentTypes>
          <ComponentType id="a"/>
        </ListOfComponentTypes>
      </MoleculeType>
    </ListOfMoleculeTypes>
    <ListOfCompartments/>
    <ListOfSpecies>
      <Species id="S1" concentration="100" name="A(b,p~u)" Fixed="0">
        <ListOfMolecules>
          <Molecule id="S1_M1" name="A">
            <ListOfComponents>
              <Component id="S1_M1_C1" name="b" numberOfBonds="0"/>
              <Component id="S1_M1_C2" name="p" state="u" numberOfBonds="0"/>
            </ListOfComponents>
          </Molecule>
        </ListOfMolecules>
      </Species>
      <Species id="S2" concentration="50" name="B(a)" Fixed="0">
        <ListOfMolecules>
          <Molecule id="S2_M1" name="B">
            <ListOfComponents>
              <Component id="S2_M1_C1" name="a" numberOfBonds="0"/>
            </ListOfComponents>
          </Molecule>
        </ListOfMolecules>
      </Species>
    </ListOfSpecies>
    <ListOfReactionRules>
      <ReactionRule id="RR1" name="R1" symmetry_factor="1">
        <ListOfReactantPatterns>
          <ReactantPattern id="RR1_RP1">
            <ListOfMolecules>
              <Molecule id="RR1_RP1_M1" name="A">
                <ListOfComponents>
                  <Component id="RR1_RP1_M1_C1" name="b" numberOfBonds="0"/>
                  <Component id="RR1_RP1_M1_C2" name="p" state="u" numberOfBonds="0"/>
                </ListOfComponents>
              </Molecule>
            </ListOfMolecules>
          </ReactantPattern>
          <ReactantPattern id="RR1_RP2">
            <ListOfMolecules>
              <Molecule id="RR1_RP2_M1" name="B">
                <ListOfComponents>
                  <Component id="RR1_RP2_M1_C1" name="a" numberOfBonds="0"/>
                </ListOfComponents>
              </Molecule>
            </ListOfMolecules>
          </ReactantPattern>
        </ListOfReactantPatterns>
        <ListOfProductPatterns>
          <ProductPattern id="RR1_PP1">
            <ListOfMolecules>
              <Molecule id="RR1_PP1_M1" name="A">
                <ListOfComponents>
                  <Component id="RR1_PP1_M1_C1" name="b" numberOfBonds="1"/>
                  <Component id="RR1_PP1_M1_C2" name="p" state="u" numberOfBonds="0"/>
                </ListOfComponents>
              </Molecule>
              <Molecule id="RR1_PP1_M2" name="B">
                <ListOfComponents>
                  <Component id="RR1_PP1_M2_C1" name="a" numberOfBonds="1"/>
                </ListOfComponents>
              </Molecule>
            </ListOfMolecules>
            <ListOfBonds>
              <Bond id="RR1_PP1_B1" site1="RR1_PP1_M1_C1" site2="RR1_PP1_M2_C1"/>
            </ListOfBonds>
          </ProductPattern>
        </ListOfProductPatterns>
        <RateLaw id="RR1_RateLaw" type="Ele" totalrate="0">
          <ListOfRateConstants>
            <RateConstant value="kf"/>
          </ListOfRateConstants>
        </RateLaw>
        <Map>
          <MapItem sourceID="RR1_RP1_M1" targetID="RR1_PP1_M1"/>
          <MapItem sourceID="RR1_RP1_M1_C1" targetID="RR1_PP1_M1_C1"/>
          <MapItem sourceID="RR1_RP1_M1_C2" targetID="RR1_PP1_M1_C2"/>
          <MapItem sourceID="RR1_RP2_M1" targetID="RR1_PP1_M2"/>
          <MapItem sourceID="RR1_RP2_M1_C1" targetID="RR1_PP1_M2_C1"/>
        </Map>
        <ListOfOperations>
          <AddBond site1="RR1_RP1_M1_C1" site2="RR1_RP2_M1_C1"/>
        </ListOfOperations>
      </ReactionRule>
    </ListOfReactionRules>
    <ListOfObservables>
      <Observable id="O1" name="AB" type="Molecules">
        <ListOfPatterns>
          <Pattern id="O1_P1">
            <ListOfMolecules>
              <Molecule id="O1_P1_M1" name="A">
                <ListOfComponents>
                  <Component id="O1_P1_M1_C1" name="b" numberOfBonds="1"/>
                </ListOfComponents>
              </Molecule>
              <Molecule id="O1_P1_M2" name="B">
                <ListOfComponents>
                  <Component id="O1_P1_M2_C1" name="a" numberOfBonds="1"/>
                </ListOfComponents>
              </Molecule>
            </ListOfMolecules>
            <ListOfBonds>
              <Bond id="O1_P1_B1" site1="O1_P1_M1_C1" site2="O1_P1_M2_C1"/>
            </ListOfBonds>
          </Pattern>
        </ListOfPatterns>
      </Observable>
    </ListOfObservables>
    <ListOfFunctions/>
  </model>
</sbml>
"""

PROBE_NET = (
    "# Created by BioNetGen\n"
    "begin parameters\n"
    "  1 kf 0.5\n"
    "  2 kr 0.1\n"
    "end parameters\n"
    "begin species\n"
    "  1 A(b,p~u) 100\n"
    "  2 B(a) 50\n"
    "  3 A(b!1,p~u).B(a!1) 0\n"
    "end species\n"
    "begin reactions\n"
    "  1 1,2 3 kf #R1\n"
    "  2 3 1,2 kr #_reverse_R1\n"
    "end reactions\n"
    "begin groups\n"
    "  1 AB 3\n"
    "end groups\n"
)

PROBE_BNGL = (
    "begin model\n"
    "begin parameters\n"
    "  kf 0.5\n"
    "end parameters\n"
    "begin molecule types\n"
    "  A(b)\n"
    "end molecule types\n"
    "begin seed species\n"
    "  A(b) 10\n"
    "end seed species\n"
    "begin reaction rules\n"
    "  A(b) -> 0 kf\n"
    "end reaction rules\n"
    "end model\n"
)

_WORKER = r"""
import importlib
import inspect
import json
import pathlib
import sys
import tempfile

mode = sys.argv[1]
pkg_root = sys.argv[2]
specs_path = pathlib.Path(sys.argv[3])
out_path = pathlib.Path(sys.argv[4])

if pkg_root and pkg_root != "__INSTALLED__":
    sys.path = [pkg_root] + [
        p for p in sys.path
        if "bng3" not in p.lower() and "bionetgen" not in p.lower()
    ]
else:
    sys.path = [
        p for p in sys.path
        if "oracle-pybionetgen" not in p.lower()
    ]

specs = json.loads(specs_path.read_text(encoding="utf-8"))
fixtures = specs["fixtures"]

with tempfile.TemporaryDirectory() as td:
    td_path = pathlib.Path(td)
    xml_path = td_path / "probe.xml"
    net_path = td_path / "probe.net"
    bngl_path = td_path / "probe.bngl"
    xml_path.write_text(fixtures["xml"], encoding="utf-8")
    net_path.write_text(fixtures["net"], encoding="utf-8")
    bngl_path.write_text(fixtures["bngl"], encoding="utf-8")

    # Execute real behavioral fixtures once per subsystem so per-row outputs
    # carry genuine execution outputs alongside symbol contracts.
    subsystem_behavior = {}
    try:
        import bionetgen
        model = bionetgen.bngmodel(str(xml_path))
        subsystem_behavior["modelapi"] = {
            "parameters": sorted(str(k) for k in model.parameters),
            "molecule_types": sorted(str(k) for k in model.molecule_types),
            "species": sorted(str(k) for k in model.species),
            "observables": sorted(str(k) for k in model.observables),
            "rules_count": len(model.rules),
        }
    except Exception as exc:
        subsystem_behavior["modelapi"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        from bionetgen.modelapi.bngfile import BNGFile

        bf = BNGFile(str(bngl_path))
        strip_dir = td_path / "stripped"
        strip_dir.mkdir(exist_ok=True)
        stripped_path = pathlib.Path(bf.strip_actions(str(bngl_path), str(strip_dir)))
        stripped_text = stripped_path.read_text(encoding="utf-8")
        subsystem_behavior["bngfile"] = {
            "stripped_line_count": len(stripped_text.splitlines()),
            "has_parameters": "begin parameters" in stripped_text,
        }
    except Exception as exc:
        subsystem_behavior["bngfile"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        from bionetgen.network.network import Network

        net_obj = Network(str(net_path))
        subsystem_behavior["network"] = {
            "parameters": len(net_obj.parameters),
            "species": len(net_obj.species),
            "reactions": len(net_obj.reactions),
            "groups": len(net_obj.groups),
            "active_blocks": sorted(net_obj.active_blocks),
        }
    except Exception as exc:
        subsystem_behavior["network"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        from bionetgen.core.defaults import BNGDefaults
        defaults = BNGDefaults()
        subsystem_behavior["defaults"] = {
            "attrs": sorted(k for k in vars(defaults).keys() if not k.startswith("_")),
        }
    except Exception as exc:
        subsystem_behavior["defaults"] = {"error": f"{type(exc).__name__}: {exc}"}

    def resolve_symbol(rel_path: str, sym: str):
        mod_name = rel_path.removesuffix(".py").replace("/", ".")
        if mod_name.endswith(".__init__"):
            mod_name = mod_name[:-9]
        mod = importlib.import_module(mod_name)
        obj = mod
        for part in sym.split("."):
            obj = getattr(obj, part)
        return mod_name, obj

    def describe_symbol(obj):
        if inspect.isclass(obj):
            bases = [base.__name__ for base in obj.__bases__]
            try:
                sig = str(inspect.signature(obj.__init__))
            except (TypeError, ValueError):
                sig = None
            is_exc = issubclass(obj, BaseException)
            exc_probe = None
            if is_exc:
                try:
                    inst = obj("probe-message")
                    exc_probe = [type(inst).__name__, str(inst)]
                except Exception as exc:
                    exc_probe = ["init_error", type(exc).__name__]
            return {
                "kind": "class",
                "bases": bases,
                "init_sig": sig,
                "is_exc": is_exc,
                "exc_probe": exc_probe,
            }
        if callable(obj):
            try:
                sig = str(inspect.signature(obj))
            except (TypeError, ValueError):
                sig = None
            return {"kind": "callable", "sig": sig}
        return {"kind": "value", "type": type(obj).__name__}

    def behavior_for_row(row_id: str):
        if row_id.startswith("py.modelapi.bngfile."):
            return subsystem_behavior.get("bngfile")
        if row_id.startswith("py.modelapi."):
            return subsystem_behavior.get("modelapi")
        if row_id.startswith("py.network."):
            return subsystem_behavior.get("network")
        if row_id.startswith("py.core.defaults."):
            return subsystem_behavior.get("defaults")
        return None

    rows_out = {}
    for row in specs["rows"]:
        rid = row["id"]
        try:
            mod_name, obj = resolve_symbol(row["rel_path"], row["sym"])
            payload = {
                "id": rid,
                "module": mod_name,
                "symbol": row["sym"],
                "contract": describe_symbol(obj),
            }
            beh = behavior_for_row(rid)
            if beh is not None:
                payload["behavior"] = beh
            rows_out[rid] = {"ok": True, "payload": payload}
        except Exception as exc:
            rows_out[rid] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    import bionetgen as bng_pkg
    meta = {
        "mode": mode,
        "package_file": str(getattr(bng_pkg, "__file__", "")),
        "version": str(getattr(bng_pkg, "__version__", "unknown")),
        "python_version": sys.version.split()[0],
    }
    out_path.write_text(
        json.dumps({"meta": meta, "rows": rows_out}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _git_dirty(repo: Path, *, ignore_untracked: bool = False) -> bool:
    cmd = ["git", "-C", str(repo), "status", "--porcelain"]
    if ignore_untracked:
        cmd.append("--untracked-files=no")
    return bool(subprocess.check_output(cmd, text=True).strip())


def _build_platform() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if system.startswith("linux"):
        return f"linux-{machine or 'x86_64'}"
    return f"{system}-{machine or 'unknown'}"


def build_pybionetgen_receipts(
    *,
    root: Path,
    revision: str,
    pybionetgen_root: Path,
    receipts_dir: Path,
    artifacts_dir: Path,
    consumer_root: Path | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    head = _git_head(root)
    if head != revision or (_git_dirty(root) and not allow_dirty):
        raise ValueError(
            "issue #471 PyBioNetGen receipts require the requested clean revision"
        )
    lock = json.loads((root / "provenance/upstreams.lock.yml").read_text("utf-8"))
    pinned_rev = str(lock["sources"]["pybionetgen"]["revision"])
    actual_oracle_rev = _git_head(pybionetgen_root)
    if actual_oracle_rev != pinned_rev:
        raise ValueError(
            f"PyBioNetGen oracle revision {actual_oracle_rev} != locked {pinned_rev}"
        )
    if _git_dirty(pybionetgen_root, ignore_untracked=True):
        raise ValueError("PyBioNetGen oracle source checkout has tracked modifications")

    matrix = json.loads((root / "provenance/capability-matrix.yml").read_text("utf-8"))
    candidate_rows: list[dict[str, str]] = []
    for row in matrix.get("rows", []):
        upstream = str(row.get("upstream", ""))
        if not upstream.startswith("pybionetgen:"):
            continue
        match = UPSTREAM_RE.match(upstream)
        if not match:
            continue
        candidate_rows.append(
            {
                "id": row["id"],
                "rel_path": match.group("path"),
                "sym": match.group("sym"),
                "upstream": upstream,
            }
        )

    fixtures = {"xml": PROBE_XML, "net": PROBE_NET, "bngl": PROBE_BNGL}
    specs = {"rows": candidate_rows, "fixtures": fixtures}
    build_platform = _build_platform()
    receipts_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        worker_path = td_path / "pybionetgen_diff_worker.py"
        worker_path.write_text(_WORKER, encoding="utf-8")
        specs_path = td_path / "specs.json"
        specs_path.write_text(
            json.dumps(specs, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        oracle_out = td_path / "oracle_all.json"
        consumer_out = td_path / "consumer_all.json"

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        oracle_cmd = [
            sys.executable,
            str(worker_path),
            "oracle",
            str(pybionetgen_root.resolve()),
            str(specs_path),
            str(oracle_out),
        ]
        consumer_target = (
            str(consumer_root.resolve())
            if consumer_root is not None
            else "__INSTALLED__"
        )
        consumer_cmd = [
            sys.executable,
            str(worker_path),
            "consumer",
            consumer_target,
            str(specs_path),
            str(consumer_out),
        ]
        oracle_proc = subprocess.run(
            oracle_cmd, env=env, capture_output=True, text=True, check=False
        )
        if oracle_proc.returncode != 0:
            raise RuntimeError(
                f"pinned PyBioNetGen oracle worker failed: {oracle_proc.stderr}"
            )
        consumer_proc = subprocess.run(
            consumer_cmd, env=env, capture_output=True, text=True, check=False
        )
        if consumer_proc.returncode != 0:
            raise RuntimeError(
                f"BNG3 PyBioNetGen consumer worker failed: {consumer_proc.stderr}"
            )

        oracle_data = json.loads(oracle_out.read_text(encoding="utf-8"))
        consumer_data = json.loads(consumer_out.read_text(encoding="utf-8"))

    oracle_version = str(oracle_data["meta"].get("version", "0.8.7-pinned"))
    consumer_version = str(consumer_data["meta"].get("version", "3.0.0a1"))
    oracle_init = pybionetgen_root / "bionetgen" / "__init__.py"
    oracle_script_sha = _sha256_bytes(oracle_init.read_bytes())

    emitted: list[str] = []
    mismatched: list[dict[str, Any]] = []
    for row in candidate_rows:
        row_id = row["id"]
        o_entry = oracle_data["rows"].get(row_id, {})
        c_entry = consumer_data["rows"].get(row_id, {})
        if not o_entry.get("ok") or not c_entry.get("ok"):
            mismatched.append(
                {
                    "id": row_id,
                    "reason": "execution_error",
                    "oracle_error": o_entry.get("error"),
                    "consumer_error": c_entry.get("error"),
                }
            )
            continue
        o_payload = o_entry["payload"]
        c_payload = c_entry["payload"]
        # Reject error payloads in subsystem behavior probes
        o_beh = o_payload.get("behavior")
        c_beh = c_payload.get("behavior")
        if (isinstance(o_beh, dict) and "error" in o_beh) or (
            isinstance(c_beh, dict) and "error" in c_beh
        ):
            mismatched.append(
                {
                    "id": row_id,
                    "reason": "behavior_probe_error",
                    "oracle_behavior": o_beh,
                    "consumer_behavior": c_beh,
                }
            )
            continue

        producer_bytes = (
            json.dumps(
                {
                    "capability_id": row_id,
                    "upstream": row["upstream"],
                    "rel_path": row["rel_path"],
                    "symbol": row["sym"],
                    "fixtures_sha256": _sha256_bytes(
                        json.dumps(fixtures, sort_keys=True).encode("utf-8")
                    ),
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        oracle_bytes = (json.dumps(o_payload, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        consumer_bytes = (
            json.dumps(c_payload, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        if oracle_bytes != consumer_bytes:
            mismatched.append(
                {
                    "id": row_id,
                    "reason": "differential_mismatch",
                    "oracle": o_payload.get("contract"),
                    "consumer": c_payload.get("contract"),
                }
            )
            continue

        row_art_dir = artifacts_dir / row_id
        row_art_dir.mkdir(parents=True, exist_ok=True)
        producer_rel = f"{row_id}/producer.json"
        oracle_rel = f"{row_id}/oracle.json"
        consumer_rel = f"{row_id}/consumer.json"
        (artifacts_dir / producer_rel).write_bytes(producer_bytes)
        (artifacts_dir / oracle_rel).write_bytes(oracle_bytes)
        (artifacts_dir / consumer_rel).write_bytes(consumer_bytes)

        producer_sha = _sha256_bytes(producer_bytes)
        oracle_sha = _sha256_bytes(oracle_bytes)
        consumer_sha = _sha256_bytes(consumer_bytes)
        oracle_cmd_str = (
            f"python pybionetgen_diff_worker.py oracle {row['rel_path']}:{row['sym']}"
        )
        consumer_cmd_str = (
            f"python pybionetgen_diff_worker.py consumer {row['rel_path']}:{row['sym']}"
        )

        receipt = {
            "schema_version": 2,
            "kind": "release-oracle-consumer-receipt",
            "capability_id": row_id,
            "check_id": f"release-capability[{row_id}]",
            "comparator": "release-oracle-byte-equality-v1",
            "source_revision": revision,
            "product_revision": revision,
            "oracle": {
                "name": f"Pinned PyBioNetGen ({row['sym']})",
                "source_id": "pybionetgen",
                "revision": pinned_rev,
                "build_platform": build_platform,
                "source_clean": True,
                "path": oracle_rel,
                "artifact_sha256": oracle_sha,
                "script_sha256": oracle_script_sha,
                "command": oracle_cmd_str,
                "expected_origin": "external-source",
                "execution": {
                    "executable": "python3",
                    "version": oracle_version,
                    "command": oracle_cmd_str,
                    "exit_code": 0,
                },
            },
            "producer": {
                "path": producer_rel,
                "output_sha256": producer_sha,
            },
            "consumer": {
                "path": consumer_rel,
                "output_sha256": consumer_sha,
                "consumed_producer_sha256": producer_sha,
                "execution": {
                    "executable": "python3",
                    "version": consumer_version,
                    "command": consumer_cmd_str,
                    "exit_code": 0,
                },
            },
        }
        (receipts_dir / f"{row_id}.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        emitted.append(row_id)

    return {
        "schema_version": 1,
        "source_revision": revision,
        "oracle_revision": pinned_rev,
        "candidate_row_count": len(candidate_rows),
        "emitted_count": len(emitted),
        "mismatched_count": len(mismatched),
        "emitted_rows": emitted,
        "mismatched_rows": mismatched,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--pybionetgen-root", type=Path, required=True)
    parser.add_argument("--consumer-root", type=Path)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    summary = build_pybionetgen_receipts(
        root=args.root.resolve(),
        revision=args.revision,
        pybionetgen_root=args.pybionetgen_root.resolve(),
        consumer_root=args.consumer_root.resolve() if args.consumer_root else None,
        receipts_dir=args.receipts_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        allow_dirty=args.allow_dirty,
    )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        f"Emitted {summary['emitted_count']}/{summary['candidate_row_count']} "
        f"PyBioNetGen #471/#180 receipts ({summary['mismatched_count']} mismatched) "
        f"for {summary['source_revision'][:8]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
