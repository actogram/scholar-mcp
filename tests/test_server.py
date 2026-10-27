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

    def fake(topic, start, end, limit, sources, top=None, grants=0):
        seen.update(topic=topic, limit=limit, sources=sources, grants=grants)
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
    out = anyio.run(lambda: server.find_labs("sleep", max_papers=5000, sources=["pubmed", "nope"]))
    assert out["labs"][0]["lead"] == "Ola Nordmann"
    assert seen["limit"] == 1000 and seen["sources"] == ["pubmed"] and seen["grants"] == 0


def test_a_source_outage_becomes_a_message(monkeypatch):
    import httpx

    def down(*a, **k):
        req = httpx.Request("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search")
        raise httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))

    monkeypatch.setattr(server.patents, "search", down)
    out = anyio.run(lambda: server.find_patents("sleep"))
    assert out["error"].startswith("www.ebi.ac.uk is not answering right now (HTTP 503)")
