"""Research Organization Registry (ROR): which organisation an affiliation names, and where it is.

ROR data is CC0. The affiliation matcher marks a confident match as "chosen"; other suggestions can be wrong (for
example "Harvard T.H. Chan School of Public Health" scores 0.93 for "Hanoi School of Public Health"). So a match is
accepted only when ROR chose it, or when a name search finds an organisation whose name words all appear in the
affiliation and whose country agrees with it. Otherwise only the country is taken from the text.
https://ror.readme.io/docs/rest-api
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..http import Http
from ..models import Organization
from ..text import clean_affiliation, country_from_text, country_name, fold, significant

log = logging.getLogger(__name__)

API = "https://api.ror.org/v2/organizations"
INSTITUTION = re.compile(
    r"univ|institut|hospital|college|school|centre|center|clinic|foundation|laborator|academy|council|agency|"
    r"ministry|consortium|society|trust|faculty|polytechn|ecole|hochschule|inserm|cnrs|nih\b|nhs\b",
    re.I,
)
ACRONYM = re.compile(r"^[A-Z][A-Z0-9&-]{3,}$")


def _display(org: dict[str, Any]) -> str:
    for n in org.get("names", []):
        if "ror_display" in n.get("types", []):
            return n.get("value", "")
    names = org.get("names") or [{}]
    return names[0].get("value", "")


def _labels(org: dict[str, Any]) -> list[str]:
    return [
        n.get("value", "") for n in org.get("names", []) if {"ror_display", "label", "alias"} & set(n.get("types", []))
    ]


def _organization(org: dict[str, Any], how: str) -> Organization:
    loc = ((org.get("locations") or [{}])[0]).get("geonames_details") or {}
    return Organization(
        name=_display(org),
        ror=org.get("id", ""),
        city=loc.get("name", ""),
        country=loc.get("country_code", ""),
        country_name=loc.get("country_name", ""),
        lat=loc.get("lat"),
        lon=loc.get("lng"),
        match=how,
    )


def _segments(affiliation: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,;]", affiliation) if p.strip()]
    found = [p for p in parts if INSTITUTION.search(p) or ACRONYM.match(p)]
    # the larger body usually comes after the department ("Department of X, University of Y, City")
    return sorted(found, key=lambda p: (0 if re.search(r"univ|hospital|institut", p, re.I) else 1, parts.index(p)))[:2]


def _fits(org: dict[str, Any], affiliation: str, country: str) -> bool:
    if country and ((org.get("locations") or [{}])[0].get("geonames_details") or {}).get("country_code") not in (
        "",
        country,
    ):
        return False
    have = significant(affiliation)
    for label in _labels(org):
        need = significant(label)
        if need and need <= have:
            return True
    return False


class Resolver:
    """Affiliation text to Organization, with a memory so that each text is looked up once per run."""

    def __init__(self, http: Http) -> None:
        self.http = http
        self.memo: dict[str, Organization | None] = {}

    def __call__(self, affiliation: str) -> Organization | None:
        aff = clean_affiliation(affiliation)
        if not aff:
            return None
        key = fold(aff)
        if key not in self.memo:
            try:
                self.memo[key] = self._resolve(aff)
            except Exception as err:  # ROR busy or down: keep the country from the text and go on
                log.warning("ROR lookup failed (%s); using the text of the affiliation", err)
                code = country_from_text(aff)
                self.memo[key] = (
                    Organization(name=aff.split(",")[0], country=code, country_name=country_name(code), match="text")
                    if code
                    else None
                )
        return self.memo[key]

    def _resolve(self, aff: str) -> Organization | None:
        country = country_from_text(aff)
        data = self.http.get_json(API, {"affiliation": aff})
        for item in data.get("items", []):
            if item.get("chosen"):
                return _organization(item["organization"], "ror")
        for seg in _segments(aff):
            q = re.sub(r"[^\w\s&-]", " ", seg)
            data = self.http.get_json(API, {"query": q})
            for org in (data.get("items") or [])[:3]:
                if _fits(org, aff, country):
                    return _organization(org, "ror-name")
        if country:
            name = _segments(aff)[0] if _segments(aff) else aff.split(",")[0]
            return Organization(name=name, country=country, country_name=country_name(country), match="text")
        return None
