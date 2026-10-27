"""Real requests to the public APIs. Run with: pytest -m network"""

import pytest

from actogram_scholar.http import Http
from actogram_scholar.pipeline import find_labs
from actogram_scholar.sources import clinicaltrials, nih_reporter

pytestmark = pytest.mark.network


def test_find_labs_end_to_end():
    res = find_labs("actigraphy sleep regularity older adults", 2024, 2025, limit=20)
    assert res.counts["papers"] > 0 and res.labs
    assert any(lab.organization.ror for lab in res.labs)


def test_grants_and_trials():
    with Http() as http:
        assert nih_reporter.search(http, pi_last="Redline", pi_first="Susan", limit=3)
        assert clinicaltrials.search(http, "actigraphy sleep", limit=2)
