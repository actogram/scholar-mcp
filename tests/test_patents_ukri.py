from conftest import FakeHttp, fixture_json

from labscout.sources import patents, ukri


def test_patents_from_europe_pmc():
    http = FakeHttp({"europepmc": fixture_json("europepmc_patents.json")})
    found = patents.search(http, "(actigraphy OR accelerometer) AND sleep", limit=3)
    assert "SRC:PAT" in http.calls[0][2]["query"]
    first = found[0]
    assert first.number and first.year and first.inventors and first.country
    assert first.url.startswith("https://worldwide.espacenet.com/patent/search?q=pn%3D")
    assert first.title[0].isupper() and not first.title.isupper()


def test_ukri_projects_with_investigator_and_organisation():
    def answer(url, params):
        if "/persons/" in url:
            return fixture_json("ukri_person.json")
        if "/organisations/" in url:
            return fixture_json("ukri_organisation.json")
        return fixture_json("ukri_projects.json")

    http = FakeHttp({"gtr.ukri.org": answer})
    grants = ukri.search(http, "circadian actigraphy", limit=2)
    assert http.calls[0][2]["s"] >= 10  # the API refuses pages under 10
    g = grants[0]
    assert g.number == "MR/Y009452/1" and g.funder == "MRC" and g.status == "active"
    assert g.investigators == ["Josh King-Robson"]
    assert g.organization == "Institute of Neurology, University College London"
    assert g.url == "https://gtr.ukri.org/projects?ref=MR/Y009452/1"


def test_organisation_names_get_normal_capitals():
    assert ukri._title("UNIVERSITY OF MANCHESTER") == "University of Manchester"
    assert ukri._title("King's College London") == "King's College London"
