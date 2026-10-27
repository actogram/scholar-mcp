"""NIH RePORTER: research projects funded by the US National Institutes of Health, with their investigators.

https://api.reporter.nih.gov/ (public, no key; about one request per second)
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..http import Http
from ..models import Grant
from ..text import fold, significant

API = "https://api.reporter.nih.gov/v2/projects/search"
FIELDS = ["ProjectTitle", "ProjectNum", "FiscalYear", "Organization", "PrincipalInvestigators", "ProjectEndDate"]


def _grant(r: dict[str, Any]) -> Grant:
    org = r.get("organization") or {}
    return Grant(
        title=(r.get("project_title") or "").strip(),
        number=r.get("project_num") or "",
        fiscal_year=r.get("fiscal_year"),
        organization=" ".join(x for x in (org.get("org_name"), org.get("org_city")) if x),
        investigators=[
            p.get("full_name", "").replace("  ", " ").strip() for p in r.get("principal_investigators") or []
        ],
        end_date=(r.get("project_end_date") or "")[:10],
    )


def search(
    http: Http, *, pi_last: str = "", pi_first: str = "", text: str = "", since: int | None = None, limit: int = 50
) -> list[Grant]:
    years = list(range(since or date.today().year - 4, date.today().year + 2))
    criteria: dict[str, Any] = {"fiscal_years": years}
    if pi_last:
        criteria["pi_names"] = (
            [{"last_name": pi_last, "first_name": pi_first}] if pi_first else [{"last_name": pi_last}]
        )
    if text:
        criteria["advanced_text_search"] = {
            "operator": "and",
            "search_field": "projecttitle,terms",
            "search_text": text,
        }
    data = http.post_json(
        API,
        {
            "criteria": criteria,
            "include_fields": FIELDS,
            "offset": 0,
            "limit": min(limit, 500),
            "sort_field": "fiscal_year",
            "sort_order": "desc",
        },
    )
    seen, out = set(), []
    for r in data.get("results") or []:
        g = _grant(r)
        base = g.number.split("-")[0][1:] if g.number else g.title  # the same project over several years counts once
        if base in seen:
            continue
        seen.add(base)
        out.append(g)
    return out


def for_investigator(
    http: Http, last: str, first: str, organization: str = "", since: int | None = None
) -> list[Grant]:
    """Grants of one person; when an organisation is known, keep those whose organisation shares a name word with it."""
    grants = search(http, pi_last=last, pi_first=first, since=since, limit=50)
    if not organization:
        return grants
    want = significant(organization) - {"university", "hospital", "institute", "school", "medical", "center", "centre"}
    if not want:
        return grants
    return [g for g in grants if want & significant(fold(g.organization))]
