"""Patents for a topic, as background to what is already known, from the patent records in Europe PMC.

Europe PMC holds patent abstracts from the European Patent Office, with inventors, countries and CPC classes, free of
charge. Its patent records end in 2014, so this source covers older prior art; newer patents need a patent office
service such as Espacenet. https://europepmc.org/RestfulWebService
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..http import Http
from ..models import Patent
from .europepmc import SEARCH

LAST_YEAR = 2014  # the newest patent records in Europe PMC


def _patent(r: dict[str, Any]) -> Patent:
    details = r.get("patentDetails") or {}
    classes = [c.get("classification", "") for c in (details.get("classifierList") or {}).get("classifier", [])]
    year = r.get("pubYear")
    inventors = [n.strip().rstrip(".").title() for n in (r.get("authorString") or "").split(",") if n.strip(" .")]
    return Patent(
        number=r.get("id", ""),
        title=(r.get("title") or "").strip().capitalize(),
        year=int(year) if str(year or "").isdigit() else None,
        inventors=inventors,
        country=details.get("country", ""),
        kind=details.get("typeDescription", ""),
        classifications=[c for c in dict.fromkeys(classes) if c][:5],
    )


def search(http: Http, query: str, start: int | None = None, end: int | None = None, limit: int = 25) -> list[Patent]:
    q = f"({query}) AND SRC:PAT"
    if start or end:
        q += f" AND (PUB_YEAR:[{start or 1800} TO {end or date.today().year}])"
    data = http.get_json(
        SEARCH,
        {"query": q, "format": "json", "resultType": "core", "pageSize": min(limit, 100), "sort": "P_PDATE_D desc"},
    )
    return [_patent(r) for r in data.get("resultList", {}).get("result", [])][:limit]
