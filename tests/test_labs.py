from labscout.labs import build
from labscout.models import Author, Organization, Paper


def _paper(title, year, authors, mesh=("Humans",), abstract=""):
    return Paper(
        title=title, year=year, authors=authors, mesh=list(mesh), abstract=abstract, pmid=str(year) + title[:3]
    )


def _a(last, first, aff):
    return Author(last_name=last, fore_name=first, initials=first[:1], affiliations=[aff] if aff else [])


PITT = Organization(
    name="University of Pittsburgh",
    ror="https://ror.org/01an3r305",
    city="Pittsburgh",
    country="US",
    country_name="United States",
    lat=40.4,
    lon=-79.9,
    match="ror",
)
VA = Organization(
    name="VA Pittsburgh Healthcare System",
    ror="https://ror.org/va",
    city="Pittsburgh",
    country="US",
    country_name="United States",
    lat=40.4,
    lon=-79.9,
    match="ror",
)
SYD = Organization(
    name="The University of Sydney",
    ror="https://ror.org/0384j8v12",
    city="Sydney",
    country="AU",
    country_name="Australia",
    lat=-33.9,
    lon=151.2,
    match="ror",
)


def resolve(aff):
    return {"pitt": PITT, "va": VA, "syd": SYD}.get(aff)


def test_senior_author_and_organisation_make_a_lab_with_a_reason():
    papers = [
        _paper(
            "Actigraphy and sleep regularity",
            2025,
            [_a("Smith", "Ann", "syd"), _a("Buysse", "Daniel", "pitt")],
            abstract="wrist actigraphy in a prospective cohort",
        ),
        _paper("Sleep regularity in older adults", 2024, [_a("Lee", "Kim", ""), _a("Buysse", "Daniel", "va")]),
        _paper(
            "Steps and rhythm",
            2023,
            [_a("Buysse", "Daniel", "pitt"), _a("Stamatakis", "Emmanuel", "syd")],
            abstract="accelerometer step counts",
        ),
    ]
    labs = build(papers, resolve, query="actigraphy sleep regularity")
    assert [lab.lead for lab in labs] == ["Daniel Buysse", "Emmanuel Stamatakis"]
    buysse = labs[0]
    assert buysse.organization.name == "University of Pittsburgh"  # the VA hospital in the same city joins this lab
    assert buysse.senior_papers == 2 and buysse.other_papers == 1
    assert buysse.first_year == 2024 and buysse.last_year == 2025
    assert "actigraphy" in buysse.signals and buysse.species == ["human"]
    assert buysse.why.startswith("2 papers on the topic as senior author (2024 to 2025); 1 more as co-author")


def test_same_name_in_different_cities_stays_apart():
    papers = [_paper("A", 2025, [_a("Lee", "Kim", "pitt")]), _paper("B", 2025, [_a("Lee", "Kim", "syd")])]
    assert len(build(papers, resolve)) == 2


def test_older_records_use_the_first_author_affiliation():
    papers = [_paper("Old record", 2001, [_a("First", "Ann", "syd"), _a("Senior", "Bob", "")])]
    lab = build(papers, resolve)[0]
    assert lab.lead == "Bob Senior" and lab.organization.name == "The University of Sydney"
