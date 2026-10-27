from labscout import cli
from labscout.labs import build
from labscout.models import Author, Organization, Paper
from labscout.pipeline import Result


def test_labs_prints_and_saves_files(monkeypatch, tmp_path, capsys):
    org = Organization(name="Uni", city="Oslo", country="NO", country_name="Norway", lat=1.0, lon=2.0, match="ror")
    papers = [Paper(title="T", year=2025, authors=[Author("Nordmann", "Ola", affiliations=["x"])])]

    def fake(topic, start, end, limit, sources, top=None, grants=0):
        return Result(
            query=topic,
            start=start,
            end=end,
            sources=sources,
            papers=papers,
            labs=build(papers, lambda a: org),
            counts={"pubmed": 1, "europepmc": 0, "papers": 1, "labs": 1},
        )

    monkeypatch.setattr(cli, "find_labs", fake)
    out_x, out_h = tmp_path / "a.xlsx", tmp_path / "a.html"
    assert cli.main(["labs", "sleep", "--from", "2020", "--xlsx", str(out_x), "--html", str(out_h)]) == 0
    text = capsys.readouterr().out
    assert "1 papers, 1 labs" in text and "Ola Nordmann | Uni (Oslo, Norway)" in text
    assert out_x.exists() and out_h.exists()


def test_unknown_source_is_refused(capsys):
    try:
        cli.main(["labs", "sleep", "--sources", "scopus"])
    except SystemExit as e:
        assert e.code == 2
    assert "unknown source scopus" in capsys.readouterr().err
