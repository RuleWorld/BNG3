"""Small, cached UniProt REST client used by the modern Atomizer."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class UniProtEntry:
    """Subset of UniProtKB metadata consumed by Atomizer callers."""

    accession: str
    name: Optional[str] = None
    protein_name: Optional[str] = None
    gene_name: Optional[str] = None
    organism: Optional[str] = None
    function: Optional[str] = None
    subcellular_location: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    @property
    def proteinName(self) -> Optional[str]:
        return self.protein_name

    @property
    def geneName(self) -> Optional[str]:
        return self.gene_name

    @property
    def subcellularLocation(self) -> List[str]:
        return self.subcellular_location


_CACHE_LIMIT = 200
_cache: "OrderedDict[str, Optional[UniProtEntry]]" = OrderedDict()


def _cache_set(key: str, value: Optional[UniProtEntry]) -> None:
    if key in _cache:
        del _cache[key]
    _cache[key] = value
    while len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)


def _request_json(url: str, timeout: float) -> Tuple[bool, Optional[Mapping[str, Any]]]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        if not 200 <= status < 300:
            return False, None
        data = json.loads(response.read().decode("utf-8"))
        return True, data if isinstance(data, Mapping) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _value(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        value = value.get("value")
    return str(value) if value is not None and value != "" else None


def _parse_entry(key: str, data: Mapping[str, Any]) -> UniProtEntry:
    protein_description = _mapping(data.get("proteinDescription"))
    recommended_name = _mapping(protein_description.get("recommendedName"))
    full_name = _value(_mapping(recommended_name.get("fullName")))

    genes = _list(data.get("genes"))
    first_gene = _mapping(genes[0]) if genes else {}
    gene_name = _value(_mapping(first_gene.get("geneName")))
    if gene_name is None:
        synonyms = _list(first_gene.get("synonyms"))
        gene_name = _value(synonyms[0]) if synonyms else None

    comments = [_mapping(comment) for comment in _list(data.get("comments"))]
    function = None
    locations: List[str] = []
    for comment in comments:
        comment_type = comment.get("type")
        if comment_type == "FUNCTION" and function is None:
            texts = _list(comment.get("texts"))
            function = _value(texts[0]) if texts else None
        if comment_type != "SUBCELLULAR_LOCATION":
            continue
        for location in _list(comment.get("subcellularLocations")):
            location_value = _value(_mapping(location).get("location"))
            if location_value:
                locations.append(location_value)

    keywords = [
        value
        for keyword in _list(data.get("keywords"))
        if (value := _value(keyword)) is not None
    ]
    primary_accession = _value(data.get("primaryAccession"))
    name = primary_accession or _value(data.get("accession")) or key
    organism = _value(_mapping(data.get("organism")).get("scientificName"))
    return UniProtEntry(
        accession=key,
        name=name,
        protein_name=full_name,
        gene_name=gene_name,
        organism=organism,
        function=function,
        subcellular_location=locations,
        keywords=keywords,
    )


def fetch_uniprot_entry(
    accession: str, timeout: float = 20.0
) -> Optional[UniProtEntry]:
    """Fetch one UniProtKB entry, returning ``None`` on network/API failure."""

    key = str(accession).upper()
    if key in _cache:
        return _cache[key]

    url = f"https://rest.uniprot.org/uniprotkb/{quote(key, safe='')}.json"
    try:
        ok, data = _request_json(url, timeout)
        if not ok or data is None:
            _cache_set(key, None)
            return None
        entry = _parse_entry(key, data)
        _cache_set(key, entry)
        return entry
    except Exception:
        _cache_set(key, None)
        return None


def clear_uniprot_cache() -> None:
    """Clear cached successful and failed lookups."""

    _cache.clear()


fetchUniProtEntry = fetch_uniprot_entry
clearUniProtCache = clear_uniprot_cache


__all__ = [
    "UniProtEntry",
    "clearUniProtCache",
    "clear_uniprot_cache",
    "fetchUniProtEntry",
    "fetch_uniprot_entry",
]
