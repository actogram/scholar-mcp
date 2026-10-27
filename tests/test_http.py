import httpx

from labscout.config import Settings
from labscout.http import Http


def test_retries_busy_answers_then_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("labscout.http.time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ok": True})

    settings = Settings(email="me@example.org", cache_dir=tmp_path)
    with Http(settings, transport=httpx.MockTransport(handler), pace=False) as http:
        assert http.get_json("https://api.ror.org/v2/organizations", {"query": "x"}) == {"ok": True}
        assert http.get_json("https://api.ror.org/v2/organizations", {"query": "x"}) == {"ok": True}
    assert len(calls) == 2  # one busy answer, one real answer, then the cache


def test_user_agent_names_the_tool_and_contact():
    assert Settings(email="me@example.org").user_agent.startswith("labscout/")
    assert "mailto:me@example.org" in Settings(email="me@example.org").user_agent


def test_pacing_is_shared_by_all_clients(monkeypatch):
    import pytest

    from labscout import http as h

    slept = []
    monkeypatch.setattr(h.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(h.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(h, "_NEXT", {})
    a, b = Http(Settings(cache_dir=None)), Http(Settings(cache_dir=None))
    a._wait("api.ror.org")
    b._wait("api.ror.org")  # a second search must wait for the first one's gap
    a._wait("api.ror.org")
    a._wait("www.ebi.ac.uk")  # another host has its own gap
    assert slept == pytest.approx([0.16, 0.32])
