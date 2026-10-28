"""The search behind every command and tool: collect papers from the sources, merge them, find the labs."""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .errors import SearchError
from .http import Http
from .labs import build, lead_affiliation
from .models import Lab, Paper
from .sources import PUBLICATION_SOURCES, europepmc, nih_reporter, pubmed
from .sources.ror import Resolver
from .text import fold, name_key

log = logging.getLogger(__name__)

LABELS = {"pubmed": "PubMed", "europepmc": "Europe PMC"}
ORDERS = ("relevance", "newest")
# Long searches that may run at the same time, from the web page and from assistants together.
SEARCH_SLOTS = threading.BoundedSemaphore(int(os.environ.get("LABSCOUT_PARALLEL_SEARCHES", "2")))
# progress(step, text): step is a source name, "organisations" or "labs"; text says what is happening, for people
Progress = Callable[[str, str], None]


@dataclass
class Result:
    query: str
    start: int | None
    end: int | None
    sources: list[str]
    papers: list[Paper] = field(default_factory=list)
    labs: list[Lab] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    found: dict[str, int] = field(default_factory=dict)  # hits per source; `counts` says how many were read
    failed: list[str] = field(default_factory=list)  # sources that did not answer
    translation: str = ""  # how PubMed read the search
    order: str = "relevance"
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    version: str = __version__

    def summary(self, top: int = 25, papers_per_lab: int = 3) -> dict[str, Any]:
        return {
            "query": self.query,
            "years": [self.start, self.end],
            "sources": self.sources,
            "order": self.order,
            "counts": self.counts,
            "found": self.found,
            "sources_not_answering": self.failed,
            "pubmed_reading": self.translation,
            "created": self.created,
            "labs": [lab.summary(papers_per_lab) for lab in self.labs[:top]],
        }


def _title_key(p: Paper) -> str:
    return re.sub(r"[^a-z0-9]", "", fold(p.title))[:80] + str(p.year or "")


def merge(papers: Iterable[Paper]) -> list[Paper]:
    """One record per paper across sources: matched by PMID, then DOI, then title and year."""
    out: list[Paper] = []
    index: dict[str, Paper] = {}
    for p in papers:
        keys = [
            k
            for k in (
                f"pmid:{p.pmid}" if p.pmid else "",
                f"doi:{p.doi}" if p.doi else "",
                f"t:{_title_key(p)}" if p.title else "",
            )
            if k
        ]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            out.append(p)
            hit = p
        else:
            _absorb(hit, p)
        for k in keys:
            index[k] = hit
    return out


def _absorb(into: Paper, other: Paper) -> None:
    into.pmid = into.pmid or other.pmid
    into.doi = into.doi or other.doi
    into.pmcid = into.pmcid or other.pmcid
    into.abstract = into.abstract or other.abstract
    into.journal = into.journal or other.journal
    into.year = into.year or other.year
    if sum(bool(a.affiliations) for a in other.authors) > sum(bool(a.affiliations) for a in into.authors):
        into.authors = other.authors
    else:  # keep the authors, but take ORCID iDs the other record has
        orcids = {a.key: a.orcid for a in other.authors if a.orcid}
        for a in into.authors:
            a.orcid = a.orcid or orcids.get(a.key, "")
    for attr in ("mesh", "keywords", "publication_types", "funders", "sources"):
        merged = list(dict.fromkeys(getattr(into, attr) + getattr(other, attr)))
        setattr(into, attr, merged)
    into.has_data_links = into.has_data_links or other.has_data_links
    into.is_preprint = into.is_preprint and other.is_preprint


def collect(
    http: Http,
    query: str,
    start: int | None = None,
    end: int | None = None,
    limit: int = 200,
    sources: Iterable[str] = PUBLICATION_SOURCES,
    order: str = "relevance",
    info: dict[str, Any] | None = None,
    progress: Progress | None = None,
) -> tuple[list[Paper], dict[str, int]]:
    """Papers from each source, merged; `order` picks the most relevant or the newest ones. `info` receives the hits
    each source has ("found"), the sources that did not answer ("failed") and PubMed's reading ("translation")."""
    if order not in ORDERS:
        raise SearchError(f"unknown order {order!r}; use relevance or newest")
    check_query(query)
    info = {} if info is None else info
    found_by: dict[str, int] = info.setdefault("found", {})
    failed: list[str] = info.setdefault("failed", [])
    papers: list[Paper] = []
    counts: dict[str, int] = {}
    srcs = list(sources)
    for src in srcs:
        if src not in ("pubmed", "europepmc"):
            raise SearchError(f"unknown source {src!r}; use one of {', '.join(PUBLICATION_SOURCES)}")

    def run(src: str) -> tuple[list[Paper], dict[str, Any], bool]:
        if progress:
            progress(src, f"Searching {LABELS.get(src, src)}")
        meta: dict[str, Any] = {}
        try:
            fn = pubmed.search if src == "pubmed" else europepmc.search
            return fn(http, query, start, end, limit, sort=order, info=meta), meta, False
        except SearchError:
            raise
        except Exception as err:  # one source being down should not stop the others
            log.warning("%s failed: %s", src, err)
            return [], meta, True

    # the sources answer side by side: a big search takes as long as the slower source, not the sum of both
    with ThreadPoolExecutor(max_workers=max(1, len(srcs))) as pool:
        answers = list(pool.map(run, srcs))
    for src, (found, meta, down) in zip(srcs, answers, strict=True):
        name = LABELS.get(src, src)
        if down:
            failed.append(src)
        counts[src] = len(found)
        if "total" in meta:
            found_by[src] = int(meta["total"])
        if meta.get("translation"):
            info["translation"] = meta["translation"]
        if progress:
            if down:
                progress(src, f"{name} did not answer; going on without it")
            else:
                which = read_as(src, order)
                hits = found_by.get(src, len(found))
                progress(
                    src, f"{name}: {hits:,} {'paper' if hits == 1 else 'papers'} found, read the {len(found):,} {which}"
                )
        papers += found
    merged = merge(papers)
    counts["papers"] = len(merged)
    return merged, counts


def check_query(query: str) -> None:
    """Stop a search with an unclosed quote or bracket: the sources would read it another way without saying so (an
    open bracket can drop the years, for example)."""
    if query.count('"') % 2:
        raise SearchError('The search has a quote mark without its pair. Please check the quotes (").')
    depth = 0
    for ch in re.sub(r'"[^"]*"', "", query):
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            break
    if depth:
        raise SearchError("The search has a bracket without its pair. Please check the brackets ( ).")


def read_as(source: str, order: str) -> str:
    """Which papers a source gives first: "most relevant" (PubMed's Best Match), "most cited" (Europe PMC, whose own
    relevance order is mostly by date) or "newest"."""
    if order == "newest":
        return "newest"
    return "most cited" if source == "europepmc" else "most relevant"


def hidden_people() -> tuple[set[str], set[str]]:
    """People who asked not to be shown: LABSCOUT_HIDE lists ORCID iDs or names ("Susan Redline"), separated by ";".
    A name hides everyone with that last name and first initial, so an ORCID iD is better where there is one."""
    orcids: set[str] = set()
    names: set[str] = set()
    for item in os.environ.get("LABSCOUT_HIDE", "").split(";"):
        item = item.strip()
        if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", item):
            orcids.add(item)
        elif item:
            last, first = split_name(item)
            names.add(name_key(last, first))
    return orcids, names


def find_labs(
    query: str,
    start: int | None = None,
    end: int | None = None,
    limit: int = 200,
    sources: Iterable[str] = PUBLICATION_SOURCES,
    top: int | None = None,
    grants: int = 0,
    http: Http | None = None,
    order: str = "relevance",
    progress: Progress | None = None,
) -> Result:
    """Search the topic, then group the papers into labs; `grants` > 0 adds NIH grants for that many top labs."""
    own = http is None
    http = http or Http()
    try:
        srcs = list(sources)
        info: dict[str, Any] = {}
        papers, counts = collect(http, query, start, end, limit, srcs, order, info, progress)
        resolve = Resolver(http)
        if progress:
            total = sum(1 for p in papers if lead_affiliation(p)[1])
            done = 0

            def counted(aff: str) -> Any:
                nonlocal done
                done += 1
                if done % 10 == 0 or done == total:
                    progress("organisations", f"Matching organisations: {done} of {total} papers")
                return resolve(aff)

            progress("organisations", f"Matching organisations: 0 of {total} papers")
        labs = build(papers, counted if progress else resolve, query=query)
        orcids, names = hidden_people()
        labs = [lab for lab in labs if lab.lead_key not in names and not (lab.orcid and lab.orcid in orcids)]
        counts["labs"] = len(labs)
        if progress:
            progress("labs", f"Ranking {len(labs)} labs and drawing the map")
        if top:
            labs = labs[:top]
        for lab in labs[:grants]:
            first = lab.fore_name.split(" ")[0] if lab.fore_name else ""
            try:
                lab.grants = nih_reporter.for_investigator(
                    http, lab.last_name, first, lab.organization.name, since=start
                )
            except Exception as err:
                log.warning("NIH RePORTER failed for %s: %s", lab.lead, err)
        return Result(
            query=query,
            start=start,
            end=end,
            sources=srcs,
            papers=papers,
            labs=labs,
            counts=counts,
            found=info.get("found", {}),
            failed=info.get("failed", []),
            translation=info.get("translation", ""),
            order=order,
        )
    finally:
        if own:
            http.close()


def split_name(name: str) -> tuple[str, str]:
    """'Susan Redline', 'Redline, Susan' or 'Redline S' to (last name, first name or initial)."""
    name = re.sub(r"\s+", " ", (name or "").strip())
    if "," in name:
        last, _, first = name.partition(",")
        return last.strip(), first.strip()
    parts = name.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    if len(parts[-1]) <= 2 and parts[-1].isupper():  # "Redline S" or "Redline SS"
        return " ".join(parts[:-1]), parts[-1]
    return parts[-1], " ".join(parts[:-1])


def profile(
    name: str, topic: str = "", organization: str = "", limit: int = 100, grants: bool = True, http: Http | None = None
) -> dict[str, Any]:
    """One person's papers on PubMed (optionally on a topic), where they work, with whom, on what, and NIH grants."""
    from collections import Counter

    from .text import signals_of, species_of

    last, first = split_name(name)
    if name_key(last, first) in hidden_people()[1]:
        return {"name": name, "error": "This researcher asked not to be shown in LabScout."}
    own = http is None
    http = http or Http()
    try:
        query = f'"{last} {first[:1]}"[au]' if first else f"{last}[au]"
        if topic:
            query += f" AND ({topic})"
        papers = pubmed.search(http, query, limit=limit)
        key = name_key(last, first)
        resolve = Resolver(http)
        places: Counter[str] = Counter()
        orgs: dict[str, Any] = {}
        coauthors: Counter[str] = Counter()
        for p in papers:
            me = next((a for a in p.authors if a.key == key), None)
            if me and me.affiliations:
                org = resolve(me.affiliations[0])
                if org:
                    k = org.ror or org.name
                    places[k] += 1
                    orgs[k] = org
            for a in p.authors:
                if a.key != key:
                    coauthors[a.display] += 1
        if organization:
            want = fold(organization)
            papers = [
                p for p in papers if any(want in fold(" ".join(a.affiliations)) for a in p.authors if a.key == key)
            ] or papers
        text = " ".join(" ".join([p.title, p.abstract, " ".join(p.mesh)]) for p in papers)
        topics = Counter(
            m
            for p in papers
            for m in p.mesh
            if m not in ("Humans", "Male", "Female", "Adult", "Aged", "Middle Aged", "Young Adult", "Adolescent")
        )
        out: dict[str, Any] = {
            "name": name,
            "pubmed_query": query,
            "papers_found": len(papers),
            "years": [
                min((p.year for p in papers if p.year), default=None),
                max((p.year for p in papers if p.year), default=None),
            ],
            "organizations": [
                {
                    "name": orgs[k].name,
                    "ror": orgs[k].ror,
                    "city": orgs[k].city,
                    "country": orgs[k].country_name or orgs[k].country,
                    "papers": n,
                    "match": orgs[k].match,
                }
                for k, n in places.most_common(5)
            ],
            "frequent_coauthors": [{"name": n, "papers": c} for n, c in coauthors.most_common(10)],
            "frequent_topics": [{"mesh": m, "papers": c} for m, c in topics.most_common(12)],
            "species": sorted({s for p in papers for s in species_of(p.mesh, p.title + " " + p.abstract)}),
            "data_signals": signals_of(text),
            "recent_papers": [p.brief() for p in sorted(papers, key=lambda x: -(x.year or 0))[:10]],
            "grants": [],
        }
        if grants and last:
            org_name = out["organizations"][0]["name"] if out["organizations"] else organization
            try:
                gs = nih_reporter.for_investigator(http, last, first.split(" ")[0] if first else "", org_name)
                out["grants"] = [
                    {
                        "title": g.title,
                        "number": g.number,
                        "fiscal_year": g.fiscal_year,
                        "organization": g.organization,
                        "end_date": g.end_date,
                        "url": g.url,
                    }
                    for g in gs[:10]
                ]
            except Exception as err:
                log.warning("NIH RePORTER failed for %s: %s", name, err)
        return out
    finally:
        if own:
            http.close()
