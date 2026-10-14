"""Flush individual pytest outcomes so crashes/timeouts cannot erase triage."""

import json
import os
from pathlib import Path


def _emit(value):
    destination = os.environ.get("BNG3_TEST_EVENT_LOG")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value) + "\n")


def pytest_collection_finish(session):
    _emit(
        {
            "event": "collection",
            "cases": [
                {"nodeid": item.nodeid, "file": item.location[0]}
                for item in session.items
            ],
        }
    )


def pytest_runtest_logreport(report):
    _emit(
        {
            "event": "case",
            "nodeid": report.nodeid,
            "file": report.location[0],
            "when": report.when,
            "outcome": report.outcome,
            "duration": report.duration,
            "detail": report.longreprtext,
            "xfail": getattr(report, "wasxfail", None),
        }
    )


def pytest_collectreport(report):
    if report.failed or report.skipped:
        _emit(
            {
                "event": "case",
                "nodeid": report.nodeid,
                "file": report.nodeid,
                "when": "collection",
                "outcome": report.outcome,
                "duration": 0,
                "detail": str(report.longrepr),
            }
        )
