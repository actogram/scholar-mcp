"""Real requests to the public APIs. Run with: pytest -m network"""

import pytest

from labscout.http import Http
from labscout.pipeline import find_labs
from labscout.sources import clinicaltrials, nih_reporter

pytestmark = pytest.mark.network


def test_find_labs_end_to_end():
    res = find_labs("actigraphy sleep regularity older adults", 2024, 2025, limit=20)
    assert res.counts["papers"] > 0 and res.labs
    assert any(lab.organization.ror for lab in res.labs)


def test_grants_and_trials():
    with Http() as http:
        assert nih_reporter.search(http, pi_last="Redline", pi_first="Susan", limit=3)
        assert clinicaltrials.search(http, "actigraphy sleep", limit=2)


def test_uk_grants_and_patents():
    import httpx

    from labscout.sources import patents, ukri

    with Http() as http:
        grants = ukri.search(http, "circadian actigraphy", limit=2)
        assert grants and grants[0].number and grants[0].organization
        try:
            found = patents.search(http, "actigraphy AND sleep", limit=2)
        except httpx.HTTPStatusError as err:  # Europe PMC has outages; that is not a failure of this code
            pytest.skip(f"Europe PMC answered {err.response.status_code}")
        assert found and found[0].number
