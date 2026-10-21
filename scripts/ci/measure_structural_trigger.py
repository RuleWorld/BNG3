#!/usr/bin/env python3
"""Measure the structural-atomization trigger over the curated BioModels corpus.

The modern Atomizer gives a species a molecular interpretation only when its
name carries the structural trigger (a bond character together with a
component separator).  This script counts, per record, how many species carry
that trigger, so the corpus-level structural-atomization rate can be stated
without a second full translation pass.

Usage::

    python scripts/ci/curated_biomodels_corpus_inventory.py  # builds the inventory
    python measure_structural_trigger.py --cache-dir <cache> --json <out>
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _species_names(root: ET.Element) -> list[str]:
    names: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "species":
            continue
        name = element.get("name") or element.get("id") or ""
        names.append(name)
    return names


def _has_structural_trigger(name: str) -> bool:
    """Mirror the Atomizer's structural trigger in ``core.py``.

    ``has_real_structure = ("." in item_name or "(" in item_name) and "!" in
    item_name``: the name must carry a bond character and a component
    separator.
    """

    return ("." in name or "(" in name) and "!" in name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--inventory-json",
        type=Path,
        default=Path(
            "/tmp/bng3-campaign/biomodels-cache/curated-biomodels-inventory.json"
        ),
    )
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()

    inventory = json.loads(args.inventory_json.read_text(encoding="utf-8"))
    models = inventory.get("models") or []

    records: list[dict[str, Any]] = []
    for entry in models:
        path = args.cache_dir / str(entry.get("filename", ""))
        record: dict[str, Any] = {
            "id": entry.get("id"),
            "format": entry.get("format"),
        }
        if not path.exists():
            record["status"] = "source-unavailable"
            records.append(record)
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            record["status"] = "source-unparsable"
            record["error"] = str(exc)[:160]
            records.append(record)
            continue
        names = _species_names(root)
        triggered = [name for name in names if _has_structural_trigger(name)]
        record.update(
            {
                "status": "measured",
                "species": len(names),
                "structural_species": len(triggered),
                "structurally_atomized": bool(triggered),
                "structural_species_fraction": (
                    len(triggered) / len(names) if names else 0.0
                ),
            }
        )
        records.append(record)

    measured = [record for record in records if record.get("status") == "measured"]
    atomized = [record for record in measured if record.get("structurally_atomized")]
    summary = {
        "records_total": len(records),
        "records_measured": len(measured),
        "records_not_measured": len(records) - len(measured),
        "records_structurally_atomized": len(atomized),
        "records_structurally_atomized_fraction": (
            len(atomized) / len(measured) if measured else 0.0
        ),
        "records_with_only_elemental_species": len(measured) - len(atomized),
        "species_total": sum(int(record.get("species", 0)) for record in measured),
        "species_structural": sum(
            int(record.get("structural_species", 0)) for record in measured
        ),
        "species_structural_fraction": (
            sum(int(record.get("structural_species", 0)) for record in measured)
            / sum(int(record.get("species", 0)) for record in measured)
            if measured
            else 0.0
        ),
    }
    payload = {
        "schema_version": 1,
        "description": (
            "Per-record count of the species whose name carries the modern "
            "Atomizer's structural trigger, measured on the curated BioModels "
            "source documents."
        ),
        "corpus": {
            "inventory_query": inventory.get("query"),
            "snapshot_date": inventory.get("snapshot_date"),
        },
        "summary": summary,
        "records": records,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
