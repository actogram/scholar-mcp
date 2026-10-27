from labscout.models import Author, Paper
from labscout.pipeline import merge, split_name


def test_merge_by_pmid_doi_and_title():
    a = Paper(
        title="Sleep regularity and health",
        year=2025,
        pmid="1",
        authors=[Author("Lee", "Kim")],
        sources=["pubmed"],
        mesh=["Humans"],
    )
    b = Paper(
        title="Sleep regularity and health",
        year=2025,
        pmid="1",
        doi="10.1/x",
        sources=["europepmc"],
        authors=[Author("Lee", "Kim", orcid="0000-0001", affiliations=["Uni X"])],
        funders=["NIH"],
    )
    c = Paper(title="Another paper", year=2024, doi="10.1/y", sources=["europepmc"])
    d = Paper(title="Another paper", year=2024, sources=["pubmed"], pmid="2")
    merged = merge([a, b, c, d])
    assert len(merged) == 2
    first = merged[0]
    assert first.doi == "10.1/x" and first.sources == ["pubmed", "europepmc"] and first.funders == ["NIH"]
    assert first.authors[0].affiliations == ["Uni X"] and first.authors[0].orcid == "0000-0001"
    assert merged[1].pmid == "2" and merged[1].doi == "10.1/y"


def test_split_name():
    assert split_name("Susan Redline") == ("Redline", "Susan")
    assert split_name("Redline, Susan") == ("Redline", "Susan")
    assert split_name("Redline S") == ("Redline", "S")
    assert split_name("Redline") == ("Redline", "")


def test_a_broken_source_is_skipped_but_a_bad_search_is_reported(monkeypatch):
    import pytest

    from labscout import pipeline
    from labscout.errors import SearchError

    def broken(*a, **k):
        raise ValueError("not JSON")

    def ok(*a, **k):
        return [Paper(title="A paper", year=2025, pmid="9")]

    monkeypatch.setattr(pipeline.pubmed, "search", broken)
    monkeypatch.setattr(pipeline.europepmc, "search", ok)
    papers, counts = pipeline.collect(object(), "sleep")
    assert counts == {"pubmed": 0, "europepmc": 1, "papers": 1}

    def rejected(*a, **k):
        raise SearchError("PubMed did not accept the search")

    monkeypatch.setattr(pipeline.pubmed, "search", rejected)
    with pytest.raises(SearchError):
        pipeline.collect(object(), "sleep[[")
