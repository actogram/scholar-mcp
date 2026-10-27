"""Shared test helpers: recorded answers of the real APIs, served by a stand-in for the HTTP client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from labscout.config import Settings

FIX = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> Any:
    return json.loads(fixture_text(name))


class FakeHttp:
    """Answers like `labscout.http.Http`, from fixtures, and records every call."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        self.settings = Settings(email="test@example.org", cache_dir=None)
        self.routes = routes or {}
        self.calls: list[tuple[str, str, Any]] = []

    def _answer(self, method: str, url: str, payload: Any) -> Any:
        self.calls.append((method, url, payload))
        for key, value in self.routes.items():
            if key in url:
                return value(url, payload) if callable(value) else value
        raise AssertionError(f"no fixture for {method} {url} {payload}")

    def get_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        return self._answer("GET", url, params)

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return self._answer("GET", url, params)

    def post_form_text(self, url: str, data: dict[str, Any]) -> str:
        return self._answer("POST", url, data)

    def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        return self._answer("POST", url, payload)

    def close(self) -> None:
        pass


@pytest.fixture
def pubmed_papers():
    from labscout.sources import pubmed

    return pubmed.parse(fixture_text("pubmed_efetch.xml"))


@pytest.fixture
def epmc_papers():
    from labscout.sources import europepmc

    return [europepmc.parse_result(r) for r in fixture_json("europepmc_search.json")["resultList"]["result"]]
