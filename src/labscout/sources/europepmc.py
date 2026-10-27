"""Europe PMC REST API: journal articles and preprints, with affiliations, ORCID iDs, funders and data links.

https://europepmc.org/RestfulWebService
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..http import Http
from ..models import Author, Paper
from ..text import clean_affiliation

SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _query(query: str, start: int | None, end: int | None, preprints: bool) -> str:
    q = f"({query})"
    if start or end:
        q += f" AND (PUB_YEAR:[{start or 1800} TO {end or date.today().year}])"
    if not preprints:
        q += " NOT (SRC:PPR)"
    return q


def search(
    http: Http, query: str, start: int | None = None, end: int | None = None, limit: int = 300, preprints: bool = True
) -> list[Paper]:
    papers: list[Paper] = []
    cursor = "*"
    while len(papers) < limit:
        data = http.get_json(
            SEARCH,
            {
                "query": _query(query, start, end, preprints),
                "format": "json",
                "resultType": "core",
                "pageSize": min(1000, limit - len(papers)),
                "cursorMark": cursor,
                "sort": "P_PDATE_D desc",
            },
        )
        results = data.get("resultList", {}).get("result", [])
        papers += [parse_result(r) for r in results]
        nxt = data.get("nextCursorMark")
        if not results or not nxt or nxt == cursor:
            break
        cursor = nxt
    return papers[:limit]


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
        mesh=[m.get("descriptorName", "") for m in (r.get("meshHeadingList") or {}).get("meshHeading", [])],
        keywords=list((r.get("keywordList") or {}).get("keyword", [])),
        publication_types=list((r.get("pubTypeList") or {}).get("pubType", [])),
        abstract=(r.get("abstractText") or "").strip(),
        funders=sorted({g.get("agency", "") for g in (r.get("grantsList") or {}).get("grant", []) if g.get("agency")}),
        has_data_links=r.get("hasData") == "Y" or bool(r.get("dataLinksTagsList")),
        is_preprint=r.get("source") == "PPR",
        sources=["europepmc"],
    )
