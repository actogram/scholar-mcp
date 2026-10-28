import anyio

from labscout import server
from labscout.labs import build
from labscout.models import Author, Organization, Paper
from labscout.pipeline import Result


def test_tools_are_listed_and_read_only():
    tools = anyio.run(server.mcp.list_tools)
    names = {t.name for t in tools}
    assert names == {"find_labs", "search_papers", "lab_profile", "find_trials", "find_grants", "find_patents"}
    assert all(t.annotations.read_only_hint for t in tools)


def test_find_grants_needs_a_name_or_words():
    result = anyio.run(server.find_grants)
    assert "error" in result


def test_find_labs_returns_the_summary(monkeypatch):
    org = Organization(name="Uni", city="Oslo", country="NO", country_name="Norway", lat=1.0, lon=2.0, match="ror")
    papers = [Paper(title="T", year=2025, authors=[Author("Nordmann", "Ola", affiliations=["x"])])]
    seen = {}

    def fake(topic, start, end, limit, sources, top=None, grants=0, order="relevance"):
        seen.update(topic=topic, limit=limit, sources=sources, grants=grants, order=order)
        return Result(
            query=topic,
            start=start,
            end=end,
            sources=sources,
            papers=papers,
            labs=build(papers, lambda a: org),
            counts={"papers": 1, "labs": 1},
        )

    monkeypatch.setattr(server, "_find_labs", fake)
    out = anyio.run(lambda: server.find_labs("sleep", max_papers=50000, sources=["pubmed", "nope"], order="odd"))
    assert out["labs"][0]["lead"] == "Ola Nordmann"
    assert seen["limit"] == 10000 and seen["sources"] == ["pubmed"] and seen["grants"] == 0
    assert seen["order"] == "relevance"  # an unknown order falls back to the default


def test_search_papers_reads_in_the_asked_order_and_says_what_was_found(monkeypatch):
    seen = {}

    def fake_collect(http, topic, start, end, limit, sources, order="relevance", info=None, progress=None):
        seen.update(order=order)
        info.update(found={"pubmed": 4200}, failed=[])
        return [Paper(title="T", year=2025, pmid="1", authors=[Author("Lee", "Kim")])], {"pubmed": 1, "papers": 1}

    monkeypatch.setattr(server, "collect", fake_collect)
    out = anyio.run(lambda: server.search_papers("sleep", order="newest"))
    assert seen["order"] == "newest" and out["found"] == {"pubmed": 4200}
    assert out["papers"][0]["senior_author"] == "Kim Lee"


def test_a_source_outage_becomes_a_message(monkeypatch):
    import httpx

    def down(*a, **k):
        req = httpx.Request("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search")
        raise httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))

    monkeypatch.setattr(server.patents, "search", down)
    out = anyio.run(lambda: server.find_patents("sleep"))
    assert out["error"].startswith("www.ebi.ac.uk is not answering right now (HTTP 503)")


def test_a_search_that_cannot_be_read_becomes_a_message():
    out = anyio.run(lambda: server.find_labs('"sleep regularity'))
    assert out["error"].startswith("The search has a quote mark without its pair")
