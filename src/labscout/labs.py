"""From papers to labs: the senior (last) author and their organisation make a lab, ranked with a plain reason."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date

from .models import Author, Lab, Organization, Paper
from .text import fold, query_terms, signals_of, species_of

Resolve = Callable[[str], "Organization | None"]


def _paper_text(p: Paper) -> str:
    return " ".join([p.title, p.abstract, " ".join(p.keywords), " ".join(p.mesh)])


def lead_affiliation(p: Paper) -> tuple[Author | None, str]:
    """The senior author and the affiliation to place the lab with. Older PubMed records list an affiliation only for
    the first author; then the lab is placed with that one."""
    if not p.authors:
        return None, ""
    last = p.authors[-1]
    if last.affiliations:
        return last, last.affiliations[0]
    first_aff = next((a.affiliations[0] for a in p.authors if a.affiliations), "")
    return last, first_aff


def build(papers: list[Paper], resolve: Resolve, query: str = "", top: int | None = None) -> list[Lab]:
    terms = query_terms(query)
    groups: dict[tuple[str, str], list[tuple[Paper, Author, Organization]]] = defaultdict(list)
    for p in papers:
        lead, aff = lead_affiliation(p)
        if lead is None:
            continue
        org = resolve(aff) if aff else None
        org = org or Organization(name=aff.split(",")[0].strip() if aff else "Unknown organisation", match="")
        place = org.ror or fold(org.name)
        groups[(lead.key, place)].append((p, lead, org))
    groups = _join_same_person(groups)

    # where each name appears on the papers in any position, for "also co-author of"
    appearances: dict[str, list[tuple[Paper, Author]]] = defaultdict(list)
    for p in papers:
        seen: set[str] = set()
        for a in p.authors:
            if a.key not in seen:
                seen.add(a.key)
                appearances[a.key].append((p, a))

    labs = []
    this_year = date.today().year
    for (key, _), items in groups.items():
        items.sort(key=lambda t: t[0].year or 0, reverse=True)
        lead = max((t[1] for t in items), key=lambda a: (bool(a.orcid), len(a.fore_name)))
        org = items[0][2]
        lab_papers = [t[0] for t in items]
        years = [p.year for p in lab_papers if p.year]
        text = " ".join(_paper_text(p) for p in lab_papers)
        species = sorted({s for p in lab_papers for s in species_of(p.mesh, _paper_text(p))})
        signals = signals_of(text)
        matched = [t for t in terms if t in fold(text)]
        funders = [f for f, _ in Counter(f for p in lab_papers for f in p.funders).most_common(8)]
        senior = len(lab_papers)
        other = _coauthored(appearances[key], items, org)
        recent = bool(years) and max(years) >= this_year - 2
        score = 3 * senior + other + (2 if recent else 0) + 0.5 * len(signals) + 0.5 * len(matched)
        if any(p.has_data_links for p in lab_papers):
            score += 1
        labs.append(
            Lab(
                lead=lead.display,
                lead_key=key,
                organization=org,
                last_name=lead.last_name,
                fore_name=lead.fore_name,
                orcid=lead.orcid,
                papers=lab_papers,
                senior_papers=senior,
                other_papers=other,
                first_year=min(years) if years else None,
                last_year=max(years) if years else None,
                species=species,
                signals=signals,
                matched_terms=matched,
                funders=funders,
                score=score,
            )
        )
    labs.sort(key=lambda lab: (-lab.score, -(lab.last_year or 0), lab.lead))
    for lab in labs:
        lab.why = explain(lab)
    return labs[:top] if top else labs


def _coauthored(appearances: list[tuple[Paper, Author]], items: list, org: Organization) -> int:
    """Papers the lab's lead co-authored, counted only where the co-author is clearly the same person: the same ORCID
    iD, or an affiliation naming the lab's city or organisation. A common name such as "Li J" is many people, so a bare
    name does not count."""
    led = {id(t[0]) for t in items}
    orcids = {t[1].orcid for t in items if t[1].orcid}
    own = {fold(t[1].affiliations[0]) for t in items if t[1].affiliations}
    marks = [fold(x) for x in (org.city, org.name) if x and len(x) >= 4]
    n = 0
    for p, a in appearances:
        if id(p) in led:
            continue
        if a.orcid and a.orcid in orcids:
            n += 1
            continue
        text = fold(" ".join(a.affiliations))
        if text and (any(m in text for m in marks) or any(o and o == fold(x) for o in own for x in a.affiliations)):
            n += 1
    return n


def _join_same_person(groups: dict[tuple[str, str], list]) -> dict[tuple[str, str], list]:
    """One person at two organisations is one lab when it is clearly the same person: the same city (a university and
    its hospital) or the same ORCID iD. The organisation of the most recent paper names the lab. The same name in
    different cities without a shared ORCID iD stays apart: it may be two people."""
    by_person: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in groups:
        by_person[key[0]].append(key)
    for keys in by_person.values():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: -len(groups[k]))
        for k in keys[1:]:
            org = groups[k][0][2]
            ids = {t[1].orcid for t in groups[k] if t[1].orcid}
            for main in keys:
                if main == k or main not in groups:
                    continue
                morg = groups[main][0][2]
                same = org.city and morg.city and fold(org.city) == fold(morg.city) and org.country == morg.country
                same = same or bool(ids & {t[1].orcid for t in groups[main] if t[1].orcid})
                if same and len(groups[main]) >= len(groups[k]):
                    groups[main] += groups.pop(k)
                    break
    return groups


def explain(lab: Lab) -> str:
    """One plain sentence on why the lab came up."""
    span = (
        (f"{lab.first_year}" if lab.first_year == lab.last_year else f"{lab.first_year} to {lab.last_year}")
        if lab.first_year
        else "years not given"
    )
    n = lab.senior_papers
    parts = [f"{n} paper{'s' if n != 1 else ''} on the topic as senior author ({span})"]
    if lab.other_papers:
        parts.append(f"{lab.other_papers} more as co-author")
    if lab.signals:
        parts.append("data: " + ", ".join(lab.signals[:4]))
    if lab.species:
        parts.append("species: " + ", ".join(lab.species))
    if any(p.has_data_links for p in lab.papers):
        parts.append("linked datasets")
    return "; ".join(parts) + "."
