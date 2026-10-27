"""Plain data records shared by the sources, the lab builder and the exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .text import name_key


@dataclass
class Author:
    last_name: str
    fore_name: str = ""
    initials: str = ""
    orcid: str = ""
    affiliations: list[str] = field(default_factory=list)

    @property
    def display(self) -> str:
        return f"{self.fore_name} {self.last_name}".strip() or self.last_name

    @property
    def key(self) -> str:
        return name_key(self.last_name, self.fore_name, self.initials)


@dataclass
class Paper:
    title: str
    year: int | None = None
    journal: str = ""
    pmid: str = ""
    doi: str = ""
    pmcid: str = ""
    authors: list[Author] = field(default_factory=list)
    mesh: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    publication_types: list[str] = field(default_factory=list)
    abstract: str = ""
    funders: list[str] = field(default_factory=list)
    has_data_links: bool = False
    is_preprint: bool = False
    sources: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return ""

    def brief(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "year": self.year,
            "journal": self.journal,
            "url": self.url,
            "pmid": self.pmid,
            "doi": self.doi,
            "preprint": self.is_preprint,
        }


@dataclass
class Organization:
    name: str
    ror: str = ""
    city: str = ""
    country: str = ""  # ISO 3166-1 alpha-2
    country_name: str = ""
    lat: float | None = None
    lon: float | None = None
    match: str = ""  # how it was found: "ror" (ROR affiliation match), "ror-name" (checked name search) or "text"


@dataclass
class Grant:
    title: str
    number: str
    fiscal_year: int | None
    organization: str
    investigators: list[str] = field(default_factory=list)
    end_date: str = ""
    source: str = "NIH RePORTER"
    funder: str = "NIH"
    status: str = ""

    @property
    def url(self) -> str:
        if not self.number:
            return ""
        if self.source.startswith("UKRI"):
            return f"https://gtr.ukri.org/projects?ref={self.number}"
        return f"https://reporter.nih.gov/search/results?query={self.number}"

    def brief(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "number": self.number,
            "funder": self.funder,
            "fiscal_year": self.fiscal_year,
            "status": self.status,
            "organization": self.organization,
            "investigators": self.investigators,
            "end_date": self.end_date,
            "source": self.source,
            "url": self.url,
        }


@dataclass
class Patent:
    number: str
    title: str
    year: int | None = None
    inventors: list[str] = field(default_factory=list)
    country: str = ""
    kind: str = ""
    classifications: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://worldwide.espacenet.com/patent/search?q=pn%3D{self.number}"

    def brief(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "year": self.year,
            "inventors": self.inventors,
            "country": self.country,
            "kind": self.kind,
            "classifications": self.classifications,
            "url": self.url,
        }


@dataclass
class Trial:
    nct_id: str
    title: str
    status: str = ""
    start: str = ""
    sponsor: str = ""
    officials: list[dict[str, str]] = field(default_factory=list)
    sites: list[dict[str, Any]] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://clinicaltrials.gov/study/{self.nct_id}"


@dataclass
class Lab:
    lead: str
    lead_key: str
    organization: Organization
    last_name: str = ""
    fore_name: str = ""
    orcid: str = ""
    papers: list[Paper] = field(default_factory=list)
    senior_papers: int = 0
    other_papers: int = 0
    first_year: int | None = None
    last_year: int | None = None
    species: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    funders: list[str] = field(default_factory=list)
    grants: list[Grant] = field(default_factory=list)
    score: float = 0.0
    why: str = ""

    def summary(self, max_papers: int = 5) -> dict[str, Any]:
        org = self.organization
        return {
            "lead": self.lead,
            "orcid": self.orcid,
            "organization": org.name,
            "ror": org.ror,
            "city": org.city,
            "country": org.country_name or org.country,
            "lat": org.lat,
            "lon": org.lon,
            "organization_match": org.match,
            "papers_as_senior_author": self.senior_papers,
            "papers_as_coauthor": self.other_papers,
            "years": [self.first_year, self.last_year],
            "species": self.species,
            "data_signals": self.signals,
            "matched_terms": self.matched_terms,
            "funders": self.funders[:8],
            "score": round(self.score, 2),
            "why": self.why,
            "top_papers": [p.brief() for p in self.papers[:max_papers]],
            "grants": [g.brief() for g in self.grants],
        }
