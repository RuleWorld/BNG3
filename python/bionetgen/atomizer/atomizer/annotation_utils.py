"""Helpers for validating and classifying external annotation URLs."""

from collections.abc import Iterable
from typing import Optional
from urllib.parse import urlsplit


def identifiers_org_database(value: str) -> Optional[str]:
    """Return the database segment of an identifiers.org URL.

    Annotation values are read from user-supplied SBML.  Parse the URL and
    validate its host before inspecting its path so a malicious URL cannot
    smuggle ``identifiers.org`` into an unrelated host or path.
    """

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None

    if hostname is None or hostname.casefold() != "identifiers.org":
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None
    return segments[-2]


def identifiers_org_databases(values: Iterable[str]) -> set[str]:
    """Return database names from valid identifiers.org annotation URLs."""

    databases: set[str] = set()
    for value in values:
        database = identifiers_org_database(value)
        if database is not None:
            databases.add(database)
    return databases
