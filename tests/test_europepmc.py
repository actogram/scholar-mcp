from conftest import FakeHttp, fixture_json

from actogram_scholar.sources import europepmc


def test_parse_result(epmc_papers):
    p = epmc_papers[0]
    assert p.pmid == "41341996" and p.doi == "10.1093/sleepadvances/zpaf077" and p.year == 2025
    assert p.authors[0].last_name == "D'Agata" and p.authors[0].orcid == "0000-0002-6166-9627"
    assert p.authors[0].affiliations[0].startswith("Department of Kinesiology")
    assert p.sources == ["europepmc"]


def test_search_pages_with_the_cursor_and_stops():
    page = fixture_json("europepmc_search.json")
    http = FakeHttp(
        {"europepmc": lambda url, params: page if params["cursorMark"] == "*" else {"resultList": {"result": []}}}
    )
    papers = europepmc.search(http, "actigraphy", 2025, 2025, limit=10)
    assert len(papers) == 3
    assert "PUB_YEAR:[2025 TO 2025]" in http.calls[0][2]["query"]
    assert len(http.calls) == 2  # the second page is empty, so the search stops
