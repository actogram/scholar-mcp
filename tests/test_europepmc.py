import re

from conftest import FakeHttp, fixture_json

from labscout.sources import europepmc


def test_parse_result(epmc_papers):
    p = epmc_papers[0]
    assert p.pmid == "41341996" and p.doi == "10.1093/sleepadvances/zpaf077" and p.year == 2025
    assert p.authors[0].last_name == "D'Agata" and p.authors[0].orcid == "0000-0002-6166-9627"
    assert p.authors[0].affiliations[0].startswith("Department of Kinesiology")
    assert p.sources == ["europepmc"]


def test_search_pages_with_the_cursor_and_stops():
    page = fixture_json("europepmc_search.json")
    http = FakeHttp(
        {
            "europepmc": lambda url, params: (
                page if params.get("cursorMark", "*") == "*" else {"resultList": {"result": []}}
            )
        }
    )
    papers = europepmc.search(http, "actigraphy", 2025, 2025, limit=10)
    assert len(papers) == 3
    assert "PUB_YEAR:[2025 TO 2025]" in http.calls[0][2]["query"]
    assert len(http.calls) == 3  # the count, then the pages; the second page is empty, so the search stops


def test_relevance_uses_europe_pmc_order_and_reports_the_hits():
    page = fixture_json("europepmc_search.json") | {"hitCount": 1577}
    http = FakeHttp(
        {"europepmc": lambda url, params: page if params.get("cursorMark", "*") == "*" else {"resultList": {}}}
    )
    info = {}
    europepmc.search(http, "actigraphy", 2021, None, limit=3, sort="relevance", info=info)
    assert http.calls[1][2]["sort"] == "CITED desc" and info == {"total": 1577}
    assert http.calls[0][2]["query"].startswith("(TITLE_ABS:(actigraphy)) AND (PUB_YEAR:[2021 TO ")
    europepmc.search(http, "actigraphy", limit=3)
    assert http.calls[-1][2]["sort"] == "P_PDATE_D desc"


def test_pubmed_searches_are_put_in_europe_pmc_terms():
    f = europepmc.from_pubmed
    assert f("sleep regularity") == "TITLE_ABS:(sleep regularity)"
    assert f('"social jetlag" OR chronotype') == 'TITLE_ABS:("social jetlag" OR chronotype)'
    assert f("chronotype[tiab] adolescents") == "TITLE_ABS:chronotype adolescents"
    assert f('"sleep regularity"[ti] AND Redline S[au]') == 'TITLE:"sleep regularity" AND AUTH:"Redline S"'
    assert f("sleep[MeSH Terms] AND 2020:2022[dp]") == "MESH:sleep AND PUB_YEAR:[2020 TO 2022]"
    assert f("actigraphy[xyz]") == "TITLE_ABS:(actigraphy)"  # an unknown tag is dropped


def test_empty_values_in_a_record_are_dropped():
    raw = fixture_json("europepmc_search.json")["resultList"]["result"][0] | {
        "meshHeadingList": {"meshHeading": [{"descriptorName": None}, {"descriptorName": "Sleep"}]},
        "keywordList": {"keyword": [None, "actigraphy"]},
    }
    p = europepmc.parse_result(raw)
    assert p.mesh == ["Sleep"] and p.keywords == ["actigraphy"]


def test_a_search_read_in_full_goes_by_year_ranges_side_by_side():
    page = fixture_json("europepmc_search.json")

    def answer(url, params):
        q = params["query"]
        years = re.search(r"PUB_YEAR:\[(\d+) TO (\d+)\]", q)
        a, b = int(years.group(1)), int(years.group(2))
        if params["resultType"] == "idlist":
            return {"hitCount": 500 * (b - a + 1)}
        return page if params["cursorMark"] == "*" else {"resultList": {"result": []}}

    http = FakeHttp({"europepmc": answer})
    notes = []
    info = {}
    papers = europepmc.search(http, "actigraphy", 2021, 2025, limit=10000, info=info, progress=notes.append)
    read = sorted(
        {
            re.search(r"PUB_YEAR:\[(\d+ TO \d+)\]", c[2]["query"]).group(1)
            for c in http.calls
            if c[2]["resultType"] == "core"
        }
    )
    assert info["total"] == 2500 and read == ["2021 TO 2023", "2024 TO 2025"]
    assert len(papers) == 6 and "2 year ranges side by side" in notes[0]
