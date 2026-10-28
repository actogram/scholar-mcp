"""Research Organization Registry (ROR): which organisation an affiliation names, and where it is.

ROR data is CC0. The affiliation matcher marks a confident match as "chosen"; other suggestions can be wrong (for
example "Harvard T.H. Chan School of Public Health" scores 0.93 for "Hanoi School of Public Health"). So a match is
accepted only when ROR chose it, or when a name search finds an organisation whose name words all appear in the
affiliation and whose country agrees with it. Otherwise only the country is taken from the text.
https://ror.readme.io/docs/rest-api
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..http import Http
from ..models import Organization
from ..text import clean_affiliation, country_from_text, country_name, fold, significant
from . import ror_local

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
        self.texts: dict[str, str] = {}  # the affiliation as written, for each memo key
        self.local = ror_local.load()
        # with the local copy the API only gets the few affiliations it could not place, so a big search stays fast
        self.api_left = int(os.environ.get("LABSCOUT_ROR_API_BUDGET", "20")) if self.local else -1

    def __call__(self, affiliation: str) -> Organization | None:
        aff = clean_affiliation(affiliation)
        if not aff:
            return None
        key = fold(aff)
        if key not in self.memo:
            self.texts[key] = aff
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

    def prefetch(self, affiliations: list[str]) -> None:
        """Places all affiliations of a search at once: the local copy first, then the misses that the API budget
        allows side by side (the shared pacing keeps them within ROR's limit), the rest by their country."""
        if not self.local:
            return
        misses = []
        for raw in affiliations:
            aff = clean_affiliation(raw)
            key = fold(aff)
            if not aff or key in self.memo:
                continue
            self.texts[key] = aff
            country = country_from_text(aff)
            org = self.local.match(aff, country)
            if org:
                self.memo[key] = org
            else:
                self.memo[key] = self._text_only(aff, country)
                misses.append((key, aff, country))
        ask = misses[: max(self.api_left, 0)]
        self.api_left = 0
        if ask:

            def one(item: tuple[str, str, str]) -> tuple[str, Organization | None]:
                key, aff, country = item
                try:
                    return key, self._api(aff, country)
                except Exception as err:
                    log.warning("ROR lookup failed (%s); using the text of the affiliation", err)
                    return key, self._text_only(aff, country)

            with ThreadPoolExecutor(max_workers=6) as pool:
                for key, org in pool.map(one, ask):
                    self.memo[key] = org

    def _resolve(self, aff: str) -> Organization | None:
        country = country_from_text(aff)
        if self.local:
            org = self.local.match(aff, country)
            if org:
                return org
            if self.api_left == 0:
                return self._text_only(aff, country)
            self.api_left -= 1
        return self._api(aff, country)

    def _api(self, aff: str, country: str) -> Organization | None:
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
        return self._text_only(aff, country)

    @staticmethod
    def _text_only(aff: str, country: str) -> Organization | None:
        if country:
            name = _segments(aff)[0] if _segments(aff) else aff.split(",")[0]
            return Organization(name=name, country=country, country_name=country_name(country), match="text")
        return None
