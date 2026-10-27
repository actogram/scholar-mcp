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
