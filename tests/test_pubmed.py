from conftest import FakeHttp, fixture_json, fixture_text

from labscout.sources import pubmed


def test_parse_records(pubmed_papers):
    assert [p.pmid for p in pubmed_papers] == ["40903419", "41205918", "41345970"]
    p = pubmed_papers[0]
    assert p.title and isinstance(p.year, int)
    assert p.doi and p.doi == p.doi.lower()
    assert p.authors and all(a.last_name for a in p.authors)
    assert any(a.affiliations for a in p.authors)
    assert p.sources == ["pubmed"]
    assert p.url == "https://pubmed.ncbi.nlm.nih.gov/40903419/"


def test_doi_comes_from_the_article_not_its_references(pubmed_papers):
    # the recorded XML had reference lists with other DOIs; each paper keeps its own
    assert len({p.doi for p in pubmed_papers}) == 3


def test_affiliations_carry_no_email_addresses(pubmed_papers):
    for p in pubmed_papers:
        for a in p.authors:
            assert all("@" not in x for x in a.affiliations)


def test_search_sends_tool_and_email_and_fetches_by_post():
    http = FakeHttp(
        {"esearch.fcgi": fixture_json("pubmed_esearch.json"), "efetch.fcgi": fixture_text("pubmed_efetch.xml")}
    )
    papers = pubmed.search(http, "actigraphy sleep regularity", 2025, 2025, limit=3)
    assert len(papers) == 3
    method, _, params = http.calls[0]
    assert method == "GET" and params["tool"] == "labscout" and params["email"] == "test@example.org"
    assert "(2025:2025[dp])" in params["term"]
    method, _, data = http.calls[1]
    assert method == "POST" and data["id"] == "40903419,41205918,41345970"


def test_large_searches_are_split_by_year():
    def esearch(url, params):
        term = params["term"]
        if "(2020:2025[dp])" in term:
            return {"esearchresult": {"count": "15000", "idlist": ["1"] * min(params["retmax"], 9999)}}
        year = term.split("(")[-1][:4]
        return {"esearchresult": {"count": "4000", "idlist": [f"{year}{i}" for i in range(params["retmax"] and 2)]}}

    http = FakeHttp({"esearch.fcgi": esearch})
    ids = pubmed.search_ids(http, "sleep", 2020, 2025, limit=10000)
    years = [c[2]["term"] for c in http.calls[1:]]
    assert years[0].endswith("(2025:2025[dp])") and years[-1].endswith("(2020:2020[dp])")
    assert ids[:2] == ["20250", "20251"]


def test_most_relevant_first_and_what_pubmed_found():
    def esearch(url, params):
        return {"esearchresult": {"count": "4321", "idlist": ["1"], "querytranslation": '"sleep"[MeSH Terms]'}}

    http = FakeHttp({"esearch.fcgi": esearch})
    info = {}
    assert pubmed.search_ids(http, "sleep", 2021, None, limit=1, sort="relevance", info=info) == ["1"]
    assert http.calls[0][2]["sort"] == "relevance"
    assert info == {"total": 4321, "translation": '"sleep"[MeSH Terms]'}
    pubmed.search_ids(http, "sleep", limit=1)
    assert http.calls[1][2]["sort"] == "pub_date"  # newest first is still the default of the source itself
