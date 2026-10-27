"""The MCP server: the same searches as the command line, as tools an AI assistant can call.

Run locally over stdio (`actogram-scholar mcp`) or as a web service (`actogram-scholar mcp --http`).
"""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .config import REPO
from .http import Http
from .pipeline import collect, profile
from .pipeline import find_labs as _find_labs
from .sources import PUBLICATION_SOURCES, clinicaltrials, nih_reporter
from .text import signals_of, species_of

INSTRUCTIONS = (
    "Scholar finds the labs, people and studies behind a research topic from public sources: PubMed, Europe PMC, the "
    "Research Organization Registry, NIH RePORTER and ClinicalTrials.gov. Start with find_labs for a topic, then use "
    "lab_profile for a person. Results show names and affiliations as published; e-mail addresses are never returned. "
    "Organisations are matched automatically: the field organization_match says how each one was found. Use the "
    "results to discover research and collaborators, not to judge people."
)
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    name="actogram-scholar", title="Actogram Scholar", instructions=INSTRUCTIONS, website_url=REPO, version=__version__
)


def _sources(sources: list[str] | None) -> list[str]:
    chosen = [s for s in (sources or PUBLICATION_SOURCES) if s in PUBLICATION_SOURCES]
    return chosen or list(PUBLICATION_SOURCES)


def _clip(n: int, low: int, high: int) -> int:
    return max(low, min(high, int(n)))


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

    return await anyio.to_thread.run_sync(run)


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

    return await anyio.to_thread.run_sync(run)


@mcp.tool(annotations=READ)
async def lab_profile(name: str, topic: str = "", organization: str = "", max_papers: int = 100) -> dict[str, Any]:
    """One researcher: organisations, years, frequent co-authors and topics, species, data hints, recent papers and NIH
    grants. name: "Susan Redline" or "Redline, Susan". topic and organization narrow the search when a name is
    common."""
    return await anyio.to_thread.run_sync(lambda: profile(name, topic, organization, _clip(max_papers, 5, 300)))


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

    return await anyio.to_thread.run_sync(run)


@mcp.tool(annotations=READ)
async def find_grants(
    investigator: str = "", text: str = "", since: int | None = None, max_grants: int = 25
) -> dict[str, Any]:
    """NIH-funded projects from NIH RePORTER, by investigator name ("Susan Redline") or by words in title and terms."""
    from .pipeline import split_name

    def run() -> dict[str, Any]:
        last, first = split_name(investigator) if investigator else ("", "")
        with Http() as http:
            grants = nih_reporter.search(
                http,
                pi_last=last,
                pi_first=first.split(" ")[0] if first else "",
                text=text,
                since=since,
                limit=_clip(max_grants, 1, 200),
            )
        return {
            "investigator": investigator,
            "text": text,
            "grants": [
                {
                    "title": g.title,
                    "number": g.number,
                    "fiscal_year": g.fiscal_year,
                    "organization": g.organization,
                    "investigators": g.investigators,
                    "end_date": g.end_date,
                    "url": g.url,
                }
                for g in grants
            ],
        }

    if not investigator and not text:
        return {"error": "Give an investigator name, words to search for, or both."}
    return await anyio.to_thread.run_sync(run)


def run(http: bool = False, host: str = "127.0.0.1", port: int = 8000) -> None:
    if http:
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run()
