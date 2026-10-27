"""PubMed through NCBI's official E-utilities: search, then fetch the records as XML.

NCBI asks programs to use E-utilities rather than the PubMed website, to send a tool name and a contact e-mail, and to
stay within 3 requests per second (10 with an API key): https://www.ncbi.nlm.nih.gov/books/NBK25497/
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date

from ..errors import SearchError
from ..http import Http
from ..models import Author, Paper
from ..text import clean_affiliation

log = logging.getLogger(__name__)

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "actogram-scholar"
ESEARCH_CAP = 9999  # esearch cannot page past 10,000 records; larger searches are split by year


def _params(http: Http, **extra: object) -> dict[str, object]:
    p: dict[str, object] = {"db": "pubmed", "tool": TOOL}
    if http.settings.email:
        p["email"] = http.settings.email
    if http.settings.ncbi_api_key:
        p["api_key"] = http.settings.ncbi_api_key
    p.update(extra)
    return p


def _term(query: str, start: int | None, end: int | None) -> str:
    if start or end:
        s, e = start or 1800, end or date.today().year
        return f"({query}) AND ({s}:{e}[dp])"
    return query


def _esearch(http: Http, term: str, retmax: int) -> tuple[int, list[str]]:
    data = http.get_json(
        f"{BASE}/esearch.fcgi", _params(http, term=term, retmode="json", retmax=retmax, sort="pub_date")
    )
    res = data.get("esearchresult", {})
    if "ERROR" in res:
        raise SearchError(f"PubMed did not accept the search: {res['ERROR']}")
    return int(res.get("count", 0)), list(res.get("idlist", []))


def count(http: Http, query: str, start: int | None = None, end: int | None = None) -> int:
    return _esearch(http, _term(query, start, end), 0)[0]


def search_ids(http: Http, query: str, start: int | None = None, end: int | None = None, limit: int = 300) -> list[str]:
    """PubMed ids for the search, newest first, at most `limit`. Searches over 9,999 hits are split year by year."""
    total, ids = _esearch(http, _term(query, start, end), min(limit, ESEARCH_CAP))
    if total <= ESEARCH_CAP or len(ids) >= limit:
        return ids[:limit]
    ids = []
    year = end or date.today().year
    first = start or 1800
    while year >= first and len(ids) < limit:
        n, chunk = _esearch(http, _term(query, year, year), min(limit - len(ids), ESEARCH_CAP))
        if n > ESEARCH_CAP:
            log.warning("PubMed has %s records for %s alone; only the newest %s are used", n, year, ESEARCH_CAP)
        ids += chunk
        year -= 1
    return ids[:limit]


def fetch(http: Http, ids: list[str], batch: int = 200) -> list[Paper]:
    papers: list[Paper] = []
    for i in range(0, len(ids), batch):
        chunk = ids[i : i + batch]
        xml = http.post_form_text(f"{BASE}/efetch.fcgi", _params(http, id=",".join(chunk), retmode="xml"))
        papers += parse(xml)
    return papers


def search(http: Http, query: str, start: int | None = None, end: int | None = None, limit: int = 300) -> list[Paper]:
    return fetch(http, search_ids(http, query, start, end, limit))


# ---- parsing --------------------------------------------------------------------------------------------------------
def _text(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _year(article: ET.Element) -> int | None:
    for path in ("Journal/JournalIssue/PubDate/Year", "ArticleDate/Year"):
        el = article.find(path)
        if el is not None and (el.text or "").strip().isdigit():
            return int(el.text.strip())
    m = re.search(r"(19|20)\d{2}", _text(article.find("Journal/JournalIssue/PubDate/MedlineDate")))
    return int(m.group(0)) if m else None


def _author(el: ET.Element) -> Author | None:
    last = _text(el.find("LastName"))
    if not last:
        return None  # a group author such as a consortium
    orcid = ""
    for ident in el.findall("Identifier"):
        if (ident.get("Source") or "").upper() == "ORCID":
            orcid = re.sub(r"^https?://orcid\.org/", "", (ident.text or "").strip())
    affs = [clean_affiliation(_text(a)) for a in el.findall("AffiliationInfo/Affiliation")]
    return Author(
        last_name=last,
        fore_name=_text(el.find("ForeName")),
        initials=_text(el.find("Initials")),
        orcid=orcid,
        affiliations=[a for a in affs if a],
    )


def parse(xml: str) -> list[Paper]:
    root = ET.fromstring(xml)
    papers = []
    for art in root.findall("PubmedArticle"):
        cit = art.find("MedlineCitation")
        article = cit.find("Article") if cit is not None else None
        if cit is None or article is None:
            continue
        ids = {i.get("IdType"): (i.text or "").strip() for i in art.findall("PubmedData/ArticleIdList/ArticleId")}
        authors = [a for a in (_author(x) for x in article.findall("AuthorList/Author")) if a]
        papers.append(
            Paper(
                title=_text(article.find("ArticleTitle")),
                year=_year(article),
                journal=_text(article.find("Journal/Title")),
                pmid=_text(cit.find("PMID")),
                doi=ids.get("doi", "").lower(),
                pmcid=ids.get("pmc", ""),
                authors=authors,
                mesh=[_text(m) for m in cit.findall("MeshHeadingList/MeshHeading/DescriptorName")],
                keywords=[_text(k) for k in cit.findall("KeywordList/Keyword")],
                publication_types=[_text(t) for t in article.findall("PublicationTypeList/PublicationType")],
                abstract=" ".join(_text(a) for a in article.findall("Abstract/AbstractText")),
                funders=sorted(
                    {
                        _text(g.find("Agency"))
                        for g in article.findall("GrantList/Grant")
                        if g.find("Agency") is not None
                    }
                ),
                is_preprint=any(
                    "preprint" in _text(t).lower() for t in article.findall("PublicationTypeList/PublicationType")
                ),
                sources=["pubmed"],
            )
        )
    return papers
