"""UKRI Gateway to Research: projects funded by UK Research and Innovation, with the lead investigator and
organisation. Public API, no key: https://gtr.ukri.org/resources/api.html

Investigator and organisation names are separate records; each is fetched once per run and only names and ORCID iDs
are kept (the person records can carry e-mail addresses, which are never read further).
"""

from __future__ import annotations

from typing import Any

from ..http import Http
from ..models import Grant

API = "https://gtr.ukri.org/gtr/api"
HEADERS = {"Accept": "application/vnd.rcuk.gtr.json-v7"}


SMALL = {"of", "and", "the", "for", "in", "at", "on", "de", "la", "le"}


def _title(name: str) -> str:
    """'UNIVERSITY OF MANCHESTER' to 'University of Manchester'; names already in mixed case stay as they are."""
    if not name.isupper():
        return name
    words = name.lower().split()
    return " ".join(w if (i and w in SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _href(project: dict[str, Any], rel: str) -> str:
    for link in (project.get("links") or {}).get("link", []):
        if link.get("rel") == rel and link.get("href"):
            return link["href"].replace("http://", "https://", 1)
    return ""


def _person(http: Http, href: str) -> str:
    if not href:
        return ""
    p = http.get_json(href, headers=HEADERS)
    return " ".join(x for x in (p.get("firstName"), p.get("otherNames"), p.get("surname")) if x).strip()


def _organisation(http: Http, href: str) -> str:
    if not href:
        return ""
    return _title(http.get_json(href, headers=HEADERS).get("name") or "")


def search(http: Http, text: str, limit: int = 25) -> list[Grant]:
    data = http.get_json(f"{API}/projects", {"q": text, "s": max(10, min(limit, 100)), "p": 1}, headers=HEADERS)
    grants = []
    for p in (data.get("project") or [])[:limit]:
        number = next(
            (i.get("value", "") for i in (p.get("identifiers") or {}).get("identifier", []) if i.get("type") == "RCUK"),
            "",
        )
        pi = _person(http, _href(p, "PI_PER"))
        org = _organisation(http, _href(p, "LEAD_ORG"))
        dept = p.get("leadOrganisationDepartment") or ""
        grants.append(
            Grant(
                title=(p.get("title") or "").strip(),
                number=number,
                fiscal_year=None,
                organization=", ".join(x for x in (dept, org) if x),
                investigators=[pi] if pi else [],
                source="UKRI Gateway to Research",
                funder=p.get("leadFunder") or "UKRI",
                status=(p.get("status") or "").lower(),
            )
        )
    return grants
