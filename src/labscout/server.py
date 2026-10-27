"""The MCP server: the same searches as the command line, as tools an AI assistant can call.

Run locally over stdio (`labscout mcp`), as a web service (`labscout mcp --http`), or together with the web page
(`labscout serve`, see web.py).
"""

from __future__ import annotations

from typing import Any

import anyio
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .config import REPO
from .http import Http
from .pipeline import collect, profile, split_name
from .pipeline import find_labs as _find_labs
from .sources import PUBLICATION_SOURCES, clinicaltrials, nih_reporter, patents, ukri
from .text import signals_of, species_of

INSTRUCTIONS = (
    "LabScout finds the labs, people and studies behind a research topic from public sources: PubMed, Europe PMC, the "
    "Research Organization Registry, NIH RePORTER, UKRI Gateway to Research, ClinicalTrials.gov and the patent records "
    "in Europe PMC. Start with find_labs for a topic, then use lab_profile for a person. Results show names and "
    "affiliations as published; e-mail addresses are never returned. Organisations are matched automatically: the "
    "field organization_match says how each one was found. Use the results to discover research and "
    "collaborators, not to judge people."
)
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    name="labscout", title="Actogram LabScout", instructions=INSTRUCTIONS, website_url=REPO, version=__version__
)


def _sources(sources: list[str] | None) -> list[str]:
    chosen = [s for s in (sources or PUBLICATION_SOURCES) if s in PUBLICATION_SOURCES]
    return chosen or list(PUBLICATION_SOURCES)


def _clip(n: int, low: int, high: int) -> int:
    return max(low, min(high, int(n)))


def _down(err: Exception) -> dict[str, Any]:
    """A source that does not answer becomes a plain message for the assistant instead of a failed call."""
    if isinstance(err, httpx.HTTPStatusError):
        host = err.request.url.host
        return {
            "error": f"{host} is not answering right now (HTTP {err.response.status_code}). Please try again later."
        }
    return {"error": f"A source is not reachable right now ({type(err).__name__}). Please try again later."}


async def _safely(fn: Any) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(fn)
    except httpx.HTTPError as err:
        return _down(err)


@mcp.tool(annotations=READ)
async def find_labs(
    topic: str,
    from_year: int | None = None,
    to_year: int | None = None,
    max_papers: int = 200,
    top: int = 20,
    sources: list[str] | None = None,
    with_grants: bool = False,
) -> dict[str, Any]:
    """Find the labs working on a topic: who leads them, where they are, and why each one came up.

    topic: search words, PubMed style ("actigraphy AND sleep regularity" works).
    from_year, to_year: limit the publication years. max_papers: papers read per source (up to 1000).
    top: labs returned (up to 100). sources: "pubmed", "europepmc" or both (default both).
    with_grants: also look up NIH grants for the five top labs (slower).
    """

    def run() -> dict[str, Any]:
        res = _find_labs(
            topic,
            from_year,
            to_year,
            _clip(max_papers, 10, 1000),
            _sources(sources),
            top=_clip(top, 1, 100),
            grants=5 if with_grants else 0,
        )
        return res.summary(top=_clip(top, 1, 100))

    return await _safely(run)


@mcp.tool(annotations=READ)
async def search_papers(
    topic: str,
    from_year: int | None = None,
    to_year: int | None = None,
    max_papers: int = 25,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Papers on a topic from PubMed and Europe PMC, newest first, merged across sources, with species and data
    hints."""

    def run() -> dict[str, Any]:
        with Http() as http:
            papers, counts = collect(http, topic, from_year, to_year, _clip(max_papers, 1, 200), _sources(sources))
        papers.sort(key=lambda p: -(p.year or 0))
        return {
            "topic": topic,
            "counts": counts,
            "papers": [
                p.brief()
                | {
                    "first_author": p.authors[0].display if p.authors else "",
                    "senior_author": p.authors[-1].display if p.authors else "",
                    "species": species_of(p.mesh, p.title + " " + p.abstract),
                    "data_signals": signals_of(" ".join([p.title, p.abstract, " ".join(p.keywords)])),
                    "sources": p.sources,
                }
                for p in papers[: _clip(max_papers, 1, 200)]
            ],
        }

    return await _safely(run)


@mcp.tool(annotations=READ)
async def lab_profile(name: str, topic: str = "", organization: str = "", max_papers: int = 100) -> dict[str, Any]:
    """One researcher: organisations, years, frequent co-authors and topics, species, data hints, recent papers and NIH
    grants. name: "Susan Redline" or "Redline, Susan". topic and organization narrow the search when a name is
    common."""
    return await _safely(lambda: profile(name, topic, organization, _clip(max_papers, 5, 300)))


@mcp.tool(annotations=READ)
async def find_trials(topic: str, max_studies: int = 25) -> dict[str, Any]:
    """Registered studies on ClinicalTrials.gov for a topic, with their responsible investigators and their sites."""

    def run() -> dict[str, Any]:
        with Http() as http:
            trials = clinicaltrials.search(http, topic, _clip(max_studies, 1, 200))
        return {
            "topic": topic,
            "studies": [
                {
                    "nct_id": t.nct_id,
                    "title": t.title,
                    "status": t.status,
                    "start": t.start,
                    "sponsor": t.sponsor,
                    "investigators": t.officials,
                    "sites": t.sites[:20],
                    "url": t.url,
                }
                for t in trials
            ],
        }

    return await _safely(run)


@mcp.tool(annotations=READ)
async def find_grants(
    investigator: str = "",
    text: str = "",
    since: int | None = None,
    max_grants: int = 25,
    funders: list[str] | None = None,
) -> dict[str, Any]:
    """Funded projects by investigator name ("Susan Redline") or by words in their title and terms.

    funders: "nih" (NIH RePORTER, USA) and "ukri" (UKRI Gateway to Research, UK); both by default. A search by
    investigator name uses NIH RePORTER only.
    """
    if not investigator and not text:
        return {"error": "Give an investigator name, words to search for, or both."}
    chosen = [f for f in (funders or ["nih", "ukri"]) if f in ("nih", "ukri")] or ["nih", "ukri"]

    def run() -> dict[str, Any]:
        last, first = split_name(investigator) if investigator else ("", "")
        found = []
        with Http() as http:
            if "nih" in chosen:
                found += nih_reporter.search(
                    http,
                    pi_last=last,
                    pi_first=first.split(" ")[0] if first else "",
                    text=text,
                    since=since,
                    limit=_clip(max_grants, 1, 200),
                )
            if "ukri" in chosen and text and not investigator:
                found += ukri.search(http, text, limit=_clip(max_grants, 1, 100))
        return {"investigator": investigator, "text": text, "funders": chosen, "grants": [g.brief() for g in found]}

    return await _safely(run)


@mcp.tool(annotations=READ)
async def find_patents(
    topic: str, from_year: int | None = None, to_year: int | None = None, max_patents: int = 25
) -> dict[str, Any]:
    """Patents on a topic, as background to what is already known: inventors, country, CPC classes and an Espacenet
    link. Source: the patent records in Europe PMC, which end in 2014; newer patents need a patent office service."""

    def run() -> dict[str, Any]:
        with Http() as http:
            found = patents.search(http, topic, from_year, to_year, _clip(max_patents, 1, 100))
        return {"topic": topic, "covers_up_to": patents.LAST_YEAR, "patents": [p.brief() for p in found]}

    return await _safely(run)


def run(http: bool = False, host: str = "127.0.0.1", port: int = 8000) -> None:
    if http:
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run()
