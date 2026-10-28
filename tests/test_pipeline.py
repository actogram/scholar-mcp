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


def test_collect_tells_what_was_found_and_which_source_failed(monkeypatch):
    import pytest

    from labscout import pipeline
    from labscout.errors import SearchError

    def pm(http, query, start, end, limit, sort="newest", info=None, progress=None):
        info.update(total=4200, translation="sleep[All Fields]")
        return [Paper(title="A paper", year=2025, pmid="9")]

    def down(*a, **k):
        raise ConnectionError("no answer")

    monkeypatch.setattr(pipeline.pubmed, "search", pm)
    monkeypatch.setattr(pipeline.europepmc, "search", down)
    steps = []
    info = {}
    papers, counts = pipeline.collect(object(), "sleep", info=info, progress=lambda s, t: steps.append((s, t)))
    assert counts == {"pubmed": 1, "europepmc": 0, "papers": 1}
    assert info == {"found": {"pubmed": 4200}, "failed": ["europepmc"], "translation": "sleep[All Fields]"}
    assert ("pubmed", "PubMed: 4,200 papers found, read the 1 most relevant") in steps
    assert ("europepmc", "Europe PMC did not answer; going on without it") in steps
    with pytest.raises(SearchError):
        pipeline.collect(object(), "sleep", order="random")


def test_people_who_asked_are_hidden(monkeypatch):
    from labscout import pipeline
    from labscout.models import Organization

    monkeypatch.setenv("LABSCOUT_HIDE", "0000-0002-0000-0001; Kim Lee")
    papers = [
        Paper(title="A", year=2025, pmid="1", authors=[Author("Lee", "Kim", affiliations=["x"])]),
        Paper(title="B", year=2025, pmid="2", authors=[Author("Ray", "Ann", orcid="0000-0002-0000-0001")]),
        Paper(title="C", year=2025, pmid="3", authors=[Author("Ode", "Una", affiliations=["x"])]),
    ]
    monkeypatch.setattr(pipeline, "collect", lambda *a, **k: (papers, {"papers": 3}))
    monkeypatch.setattr(pipeline, "Resolver", lambda http: lambda aff: Organization(name="Uni", city="Oslo"))
    res = pipeline.find_labs("sleep", http=object())
    assert [lab.lead for lab in res.labs] == ["Una Ode"] and res.counts["labs"] == 1
    assert "error" in pipeline.profile("Lee, Kim", http=object())


def test_an_unclosed_quote_or_bracket_is_reported_before_searching():
    import pytest

    from labscout import pipeline
    from labscout.errors import SearchError

    for bad in ('"sleep regularity', "(sleep AND", "sleep) OR (wake"):
        with pytest.raises(SearchError):
            pipeline.check_query(bad)
    pipeline.check_query('"social (jetlag" AND (sleep OR wake)')  # a bracket inside quotes is just text
