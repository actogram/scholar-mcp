"""ClinicalTrials.gov API v2: registered studies with their responsible investigators and their sites.

https://clinicaltrials.gov/data-api/api
"""

from __future__ import annotations

from typing import Any

from ..http import Http
from ..models import Trial

API = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ",".join(
    [
        "protocolSection.identificationModule.nctId",
        "protocolSection.identificationModule.briefTitle",
        "protocolSection.statusModule.overallStatus",
        "protocolSection.statusModule.startDateStruct",
        "protocolSection.sponsorCollaboratorsModule.leadSponsor",
        "protocolSection.contactsLocationsModule.overallOfficials",
        "protocolSection.contactsLocationsModule.locations",
    ]
)


def _trial(s: dict[str, Any]) -> Trial:
    p = s.get("protocolSection") or {}
    ident, status = p.get("identificationModule") or {}, p.get("statusModule") or {}
    cl = p.get("contactsLocationsModule") or {}
    officials = [
        {
            "name": o.get("name", ""),
            "role": (o.get("role") or "").replace("_", " ").lower(),
            "affiliation": o.get("affiliation", ""),
        }
        for o in cl.get("overallOfficials") or []
    ]
    sites = []
    for loc in cl.get("locations") or []:
        geo = loc.get("geoPoint") or {}
        sites.append(
            {
                "facility": loc.get("facility", ""),
                "city": loc.get("city", ""),
                "country": loc.get("country", ""),
                "lat": geo.get("lat"),
                "lon": geo.get("lon"),
            }
        )
    return Trial(
        nct_id=ident.get("nctId", ""),
        title=ident.get("briefTitle", ""),
        status=(status.get("overallStatus") or "").replace("_", " ").lower(),
        start=(status.get("startDateStruct") or {}).get("date", ""),
        sponsor=((p.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name", ""),
        officials=officials,
        sites=sites,
    )


def search(http: Http, query: str, limit: int = 50) -> list[Trial]:
    trials: list[Trial] = []
    token = None
    while len(trials) < limit:
        params: dict[str, Any] = {"query.term": query, "pageSize": min(100, limit - len(trials)), "fields": FIELDS}
        if token:
            params["pageToken"] = token
        data = http.get_json(API, params)
        trials += [_trial(s) for s in data.get("studies") or []]
        token = data.get("nextPageToken")
        if not token:
            break
    return trials[:limit]
