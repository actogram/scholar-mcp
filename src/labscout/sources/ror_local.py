"""A local copy of the Research Organization Registry, so that affiliations are matched in memory instead of with one
or more requests to the ROR API per paper (the API allows about 6 requests a second, which made a search of a few
thousand papers take many minutes).

The index is built from ROR's own data dump (CC0, published on Zenodo) with `labscout ror-index OUT`, once, for
example when the Docker image is built. LABSCOUT_ROR_INDEX names the file; without it the API is used as before.
A name matches an affiliation under the same rule as the API name search: every significant word of the name is in
the affiliation and the country agrees. A one word name must be a whole part of the affiliation ("Inserm").
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import urllib.request
import zipfile
from functools import lru_cache
from typing import Any

from ..models import Organization
from ..text import fold, significant

log = logging.getLogger(__name__)

ZENODO = "https://zenodo.org/api/communities/ror-data/records?sort=newest&size=1"
# names made only of these words ("Department of Public Health", "Faculty of Medicine") name no single organisation
_GENERIC_WORDS = """department faculty school college university universite universidad universita universitat
hospital clinic clinical centre center institute institut instituto istituto national public health medicine medical
research science sciences general foundation unit laboratory laboratories group division service services city
regional central state federal royal children women community care sleep"""
GENERIC = set(_GENERIC_WORDS.split())
TYPES = {"education": 0, "healthcare": 1, "facility": 2, "funder": 3, "government": 3, "nonprofit": 3, "company": 4}


def _row(org: dict[str, Any]) -> list[Any] | None:
    if org.get("status") != "active":
        return None
    names = org.get("names", [])
    first = names[0]["value"] if names else ""
    display = next((n["value"] for n in names if "ror_display" in n.get("types", [])), first)
    labels = sorted({n["value"] for n in names if {"ror_display", "label", "alias"} & set(n.get("types", []))})
    acronyms = sorted({n["value"] for n in names if "acronym" in n.get("types", [])})
    loc = ((org.get("locations") or [{}])[0]).get("geonames_details") or {}
    kind = min((TYPES.get(t, 5) for t in org.get("types", [])), default=5)
    return [
        org["id"],
        display,
        labels,
        acronyms,
        loc.get("name", ""),
        loc.get("country_code", ""),
        loc.get("country_name", ""),
        loc.get("lat"),
        loc.get("lng"),
        kind,
    ]


def build(out: str, source: str = "") -> int:
    """Writes the compact index (gzipped JSON rows) from a ROR dump zip, a file path or, by default, the newest dump."""
    if not source:
        meta = json.load(urllib.request.urlopen(ZENODO, timeout=60))
        files = meta["hits"]["hits"][0]["files"]
        source = next(f["links"]["self"] for f in files if f["key"].endswith(".zip"))
    if source.startswith("http"):
        blob = urllib.request.urlopen(source, timeout=300).read()
    else:
        with open(source, "rb") as f:
            blob = f.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.endswith(".json"))
        data = json.loads(z.read(name))
    rows = [r for r in map(_row, data) if r]
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    return len(rows)


class LocalRor:
    def __init__(self, path: str) -> None:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            self.rows = json.load(f)
        # each name is filed under its rarest significant word, so an affiliation only checks a few candidates
        freq: dict[str, int] = {}
        names: list[tuple[frozenset[str], int, str]] = []
        for i, r in enumerate(self.rows):
            for label in r[2]:
                need = frozenset(significant(label))
                if need:
                    names.append((need, i, fold(label).strip()))
                    for w in need:
                        freq[w] = freq.get(w, 0) + 1
        self.index: dict[str, list[tuple[frozenset[str], int, str]]] = {}
        for need, i, label in names:
            self.index.setdefault(min(need, key=lambda w: (freq[w], w)), []).append((need, i, label))
        self.exact = {fold(a).strip(): i for i, r in enumerate(self.rows) for a in r[3] if len(a) >= 4}

    def match(self, affiliation: str, country: str) -> Organization | None:
        parts = [p.strip(" .") for p in affiliation.replace(";", ",").split(",") if p.strip(" .")]
        segs = [significant(p) for p in parts]
        folded = {fold(p) for p in parts}
        have = set().union(*segs) if segs else set()
        best: tuple[tuple[int, ...], int] | None = None
        for w in have:
            for need, i, label in self.index.get(w, ()):
                if need <= GENERIC:
                    continue
                if len(need) == 1 and label not in folded:
                    continue
                at = next((k for k, seg in enumerate(segs) if need <= seg), None)
                if at is None:  # all words of the name must stand in one part of the affiliation
                    continue
                r = self.rows[i]
                if country and r[5] and r[5] != country:
                    continue
                score = (len(need), -r[9], -at)
                if best is None or score > best[0]:
                    best = (score, i)
        if best is None:
            for p in folded:  # a part that starts with an acronym such as "INSERM U1219" or "CNRS"
                i = self.exact.get(p.split(" ")[0]) if p else None
                if i is not None and (not country or self.rows[i][5] in ("", country)):
                    best = ((0,), i)
                    break
        if best is None:
            return None
        r = self.rows[best[1]]
        return Organization(
            name=r[1], ror=r[0], city=r[4], country=r[5], country_name=r[6], lat=r[7], lon=r[8], match="ror-local"
        )


@lru_cache(maxsize=1)
def load() -> LocalRor | None:
    path = os.environ.get("LABSCOUT_ROR_INDEX", "").strip()
    if not path or not os.path.exists(path):
        return None
    try:
        return LocalRor(path)
    except Exception as err:  # a broken file should not stop searches; the API still works
        log.warning("ROR index %s could not be read (%s); using the ROR API", path, err)
        return None
