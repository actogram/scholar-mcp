import pytest
from starlette.testclient import TestClient

from labscout import web
from labscout.labs import build
from labscout.models import Author, Organization, Paper
from labscout.pipeline import Result

CALLS = []


def _fake_find_labs(topic, start, end, limit, sources, top=None, grants=0, order="relevance", progress=None):
    CALLS.append({"topic": topic, "start": start, "end": end, "order": order})
    if progress:
        progress("pubmed", "PubMed: 1 paper found, read the 1 most relevant")
    org = Organization(name="Uni", city="Oslo", country="NO", country_name="Norway", lat=59.9, lon=10.7, match="ror")
    papers = [
        Paper(title="Steps and sleep", year=2025, pmid="1", authors=[Author("Nordmann", "Ola", affiliations=["x"])])
    ]
    return Result(
        query=topic,
        start=start,
        end=end,
        sources=sources,
        papers=papers,
        labs=build(papers, lambda a: org),
        counts={"pubmed": 1, "papers": 1, "labs": 1},
        found={"pubmed": 1},
        order=order,
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web, "find_labs", _fake_find_labs)
    monkeypatch.setenv("LABSCOUT_ALLOWED_HOSTS", "testserver")
    web._results.clear()
    web._visits.clear()
    web._jobs.clear()
    CALLS.clear()
    with TestClient(web.create_app()) as c:
        yield c


def test_home_page_has_the_form_and_the_mcp_address(client):
    r = client.get("/")
    assert r.status_code == 200 and 'name="topic"' in r.text
    assert "http://testserver/mcp" in r.text
    assert "frame-ancestors" in r.headers["content-security-policy"]


def _search(client, **params):
    """The first answer is the waiting page; the search runs in a thread, so ask again until the report is there."""
    import time

    for _ in range(50):
        r = client.get("/search", params=params)
        if "Searching for" not in r.text:
            return r
        assert r.headers.get("refresh") == "2"
        time.sleep(0.05)
    raise AssertionError("the search did not finish")


def test_search_shows_the_report_and_offers_downloads(client):
    r = _search(client, topic="steps sleep", **{"from": "2020", "source": "pubmed"})
    assert r.status_code == 200 and "Labs for: steps sleep" in r.text and "Ola Nordmann" in r.text
    key = r.text.split('href="download/')[1].split(".xlsx")[0]
    x = client.get(f"/download/{key}.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert client.get(f"/download/{key}.csv").text.startswith("rank,lead")
    assert client.get(f"/download/{key}.json").json()["labs"][0]["lead"] == "Ola Nordmann"
    assert client.get("/download/0000000000000000.json").status_code == 404


def test_empty_topic_and_too_many_searches(client, monkeypatch):
    assert client.get("/search").status_code == 400
    monkeypatch.setattr(web, "PER_HOUR", 1)
    assert _search(client, topic="a").status_code == 200
    assert _search(client, topic="a").status_code == 200  # the same search comes from memory
    assert client.get("/search", params={"topic": "b"}).status_code == 429


def test_health_and_mcp_on_the_same_server(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert r.status_code == 200 and "labscout" in r.text


def test_mcp_refuses_unknown_host_names(monkeypatch):
    monkeypatch.delenv("LABSCOUT_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("SPACE_HOST", raising=False)
    with TestClient(web.create_app(), base_url="http://evil.example") as c:
        r = c.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert r.status_code == 421


def test_space_host_is_allowed(monkeypatch):
    monkeypatch.setenv("SPACE_HOST", "actogram-labscout.hf.space")
    assert "actogram-labscout.hf.space" in web.mcp_security().allowed_hosts


def test_home_page_explains_the_tool_and_starts_five_years_back(client):
    from datetime import date

    r = client.get("/")
    since = str(date.today().year - 5)
    assert f'name="from" min="1900" max="2100" value="{since}"' in r.text
    assert "How it works" in r.text and "Search tips" in r.text and "<svg" in r.text
    assert f"search?topic=actigraphy+sleep+regularity&amp;from={since}" in r.text
    assert 'name="order" value="relevance" checked' in r.text
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_pages_are_compressed_but_mcp_is_not(client):
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    m = client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream", "Accept-Encoding": "gzip"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    assert m.status_code == 200 and "content-encoding" not in m.headers


def test_get_on_mcp_is_not_offered(client):
    r = client.get("/mcp")
    assert r.status_code == 405 and r.headers["allow"] == "POST"


def test_privacy_page(client):
    r = client.get("/privacy")
    assert r.status_code == 200 and "services@actogram.ai" in r.text and "hide your entry" in r.text


def test_years_are_put_in_order_and_the_order_is_passed_on(client):
    r = _search(client, topic="steps", **{"from": "2025", "to": "2021", "order": "newest"})
    assert r.status_code == 200
    assert CALLS[-1] == {"topic": "steps", "start": 2021, "end": 2025, "order": "newest"}
    assert "PubMed has 1 paper for this search" in r.text and 'href="privacy"' in r.text


def test_the_waiting_page_shows_the_steps(monkeypatch):
    job = {"started": 0, "sources": ["pubmed", "europepmc"], "steps": {"pubmed": "PubMed: 9 papers found"}}
    html = web._steps(job)
    assert '<li class="now">PubMed: 9 papers found</li>' in html
    assert '<li class="todo">Search Europe PMC</li>' in html and "Rank the labs" in html
    job["steps"]["europepmc"] = "Searching Europe PMC"
    assert '<li class="done">PubMed: 9 papers found</li>' in web._steps(job)


def test_robots_keep_crawlers_away_from_searches(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and "Disallow: /search" in r.text and "Disallow: /download/" in r.text
