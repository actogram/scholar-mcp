"""Europe PMC REST API: journal articles and preprints, with affiliations, ORCID iDs, funders and data links.

https://europepmc.org/RestfulWebService
"""

from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from ..http import Http
from ..models import Author, Paper
from ..text import clean_affiliation

SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Europe PMC's own relevance order puts the newest papers first, so "most relevant" reads the most cited matches.
SORT = {"relevance": "CITED desc", "newest": "P_PDATE_D desc"}
FIELDS = {"tiab": "TITLE_ABS", "tw": "TITLE_ABS", "ti": "TITLE", "ab": "ABSTRACT", "mh": "MESH", "mesh": "MESH"}
FIELDS |= {"mesh terms": "MESH", "majr": "MESH", "la": "LANG", "pt": "PUB_TYPE"}
AUTHOR = re.compile(r"([\w'-]+(?:\s+[A-Z]{1,3})?)\[(?i:au|author)\]")
TAG = re.compile(r'("[^"]+"|[^\s()"\[\]]+)\[([^\]]+)\]')


def from_pubmed(query: str) -> str:
    """A PubMed search in Europe PMC's terms. Field tags become fields ("chronotype[tiab]" is TITLE_ABS:chronotype);
    a search without fields looks at titles and abstracts, as PubMed does, rather than at whole texts, where a word
    mentioned once in passing would match."""

    def tag(m: re.Match[str]) -> str:
        term, name = m.group(1), m.group(2).strip().lower()
        if name in ("dp", "pdat"):
            years = re.fullmatch(r"(\d{4})(?::(\d{4}))?", term.strip('"'))
            return f"PUB_YEAR:[{years.group(1)} TO {years.group(2) or years.group(1)}]" if years else term
        field = FIELDS.get(name)
        return f"{field}:{term}" if field else term

    q = AUTHOR.sub(lambda m: f'AUTH:"{m.group(1)}"', query)
    q = TAG.sub(tag, q)
    return q if re.search(r"\b[A-Z_]{3,}:", q) else f"TITLE_ABS:({q})"


def _query(query: str, start: int | None, end: int | None, preprints: bool) -> str:
    q = f"({from_pubmed(query)})"
    if start or end:
        q += f" AND (PUB_YEAR:[{start or 1800} TO {end or date.today().year}])"
    if not preprints:
        q += " NOT (SRC:PPR)"
    return q


Progress = Callable[[str], None]
CHUNK = 1500  # records per year range when a search is read in full, side by side


def _count(http: Http, q: str) -> int:
    data = http.get_json(SEARCH, {"query": q, "format": "json", "resultType": "idlist", "pageSize": 1})
    return int(data.get("hitCount") or 0)


def _read(http: Http, q: str, limit: int, sort: str, info: dict[str, object] | None = None) -> list[Paper]:
    papers: list[Paper] = []
    cursor = "*"
    while len(papers) < limit:
        params = {
            "query": q,
            "format": "json",
            "resultType": "core",
            "pageSize": min(1000, limit - len(papers)),
            "cursorMark": cursor,
            "sort": SORT[sort],
        }
        data = http.get_json(SEARCH, params)
        if info is not None and cursor == "*":
            info["total"] = int(data.get("hitCount") or 0)
        results = data.get("resultList", {}).get("result", [])
        papers += [parse_result(r) for r in results]
        nxt = data.get("nextCursorMark")
        if not results or not nxt or nxt == cursor:
            break
        cursor = nxt
    return papers[:limit]


def _ranges(http: Http, query: str, start: int, end: int, preprints: bool) -> list[tuple[int, int, int]]:
    """Year ranges of at most CHUNK records each (a single year may hold more), found by halving."""
    out: list[tuple[int, int, int]] = []
    todo = [(start, end)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        while todo:
            counts = list(pool.map(lambda r: _count(http, _query(query, r[0], r[1], preprints)), todo))
            nxt = []
            for (a, b), n in zip(todo, counts, strict=True):
                if not n:
                    continue
                if n <= CHUNK or a == b:
                    out.append((a, b, n))
                else:
                    mid = (a + b) // 2
                    nxt += [(a, mid), (mid + 1, b)]
            todo = nxt
    return sorted(out)


def search(
    http: Http,
    query: str,
    start: int | None = None,
    end: int | None = None,
    limit: int = 300,
    preprints: bool = True,
    sort: str = "newest",
    info: dict[str, object] | None = None,
    progress: Progress | None = None,
) -> list[Paper]:
    """Papers for the search, the most cited ("relevance") or the newest first; `info` receives the number of hits
    ("total"). When every hit fits in `limit`, the order does not change what is read, so the years are read as
    ranges side by side; otherwise the first `limit` in the chosen order are read one page after another."""
    total = _count(http, _query(query, start, end, preprints))
    if info is not None:
        info["total"] = total
    if total <= 1000 or total > limit:
        if progress and total > limit:
            progress(f"Europe PMC has {total:,} papers; reading the first {limit:,} in its order, page by page")
        return _read(http, _query(query, start, end, preprints), limit, sort)
    first, last = start or 1900, end or date.today().year
    ranges = _ranges(http, query, first, last, preprints)
    if progress:
        shown = ", ".join(f"{a}" if a == b else f"{a} to {b}" for a, b, _ in ranges[:6])
        more = f" and {len(ranges) - 6} more" if len(ranges) > 6 else ""
        progress(
            f"Europe PMC has {total:,} papers; reading all of them in {len(ranges)} year ranges side by side "
            f"({shown}{more})"
        )
    done = [0]

    def one(r: tuple[int, int, int]) -> list[Paper]:
        got = _read(http, _query(query, r[0], r[1], preprints), r[2] + 100, sort)
        done[0] += len(got)
        if progress:
            progress(f"Europe PMC: {done[0]:,} of {total:,} records read")
        return got

    with ThreadPoolExecutor(max_workers=6) as pool:
        papers = [p for part in pool.map(one, ranges) for p in part]
    return papers


def _author(a: dict[str, Any]) -> Author | None:
    last = (a.get("lastName") or "").strip()
    if not last:
        return None
    affs = [
        clean_affiliation(x.get("affiliation", ""))
        for x in (a.get("authorAffiliationDetailsList") or {}).get("authorAffiliation", [])
    ]
    orcid = ""
    aid = a.get("authorId") or {}
    if (aid.get("type") or "").upper() == "ORCID":
        orcid = aid.get("value", "")
    return Author(
        last_name=last,
        fore_name=(a.get("firstName") or "").strip(),
        initials=(a.get("initials") or "").strip(),
        orcid=orcid,
        affiliations=[x for x in affs if x],
    )


def parse_result(r: dict[str, Any]) -> Paper:
    authors = [x for x in (_author(a) for a in (r.get("authorList") or {}).get("author", [])) if x]
    year = r.get("pubYear")
    return Paper(
        title=(r.get("title") or "").strip().rstrip("."),
        year=int(year) if str(year or "").isdigit() else None,
        journal=((r.get("journalInfo") or {}).get("journal") or {}).get("title", "")
        or r.get("bookOrReportDetails", {}).get("publisher", ""),
        pmid=r.get("pmid", "") or "",
        doi=(r.get("doi") or "").lower(),
        pmcid=r.get("pmcid", "") or "",
        authors=authors,
        mesh=[
            m["descriptorName"]
            for m in (r.get("meshHeadingList") or {}).get("meshHeading", [])
            if m.get("descriptorName")
        ],
        keywords=[k for k in (r.get("keywordList") or {}).get("keyword", []) if k],
        publication_types=[t for t in (r.get("pubTypeList") or {}).get("pubType", []) if t],
        abstract=(r.get("abstractText") or "").strip(),
        funders=sorted({g.get("agency", "") for g in (r.get("grantsList") or {}).get("grant", []) if g.get("agency")}),
        has_data_links=r.get("hasData") == "Y" or bool(r.get("dataLinksTagsList")),
        is_preprint=r.get("source") == "PPR",
        sources=["europepmc"],
    )
