import gzip
import json

from labscout.sources import ror, ror_local


def _index(tmp_path, rows):
    path = tmp_path / "ror_index.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f)
    return str(path)


ROWS = [
    [
        "https://ror.org/murdoch",
        "Murdoch University",
        ["Murdoch University"],
        [],
        "Perth",
        "AU",
        "Australia",
        -32.0,
        115.8,
        0,
    ],
    [
        "https://ror.org/uwa",
        "The University of Western Australia",
        ["University of Western Australia"],
        ["UWA"],
        "Perth",
        "AU",
        "Australia",
        -31.9,
        115.8,
        0,
    ],
    [
        "https://ror.org/dph",
        "Department of Public Health",
        ["Department of Public Health"],
        [],
        "Pasadena",
        "US",
        "United States",
        34.1,
        -118.1,
        3,
    ],
    ["https://ror.org/inserm", "Inserm", ["Inserm"], ["INSERM"], "Paris", "FR", "France", 48.8, 2.3, 3],
    [
        "https://ror.org/flinders",
        "Flinders University",
        ["Flinders University"],
        [],
        "Adelaide",
        "AU",
        "Australia",
        -35.0,
        138.6,
        0,
    ],
]


def test_names_must_stand_in_one_part_of_the_affiliation(tmp_path):
    local = ror_local.LocalRor(_index(tmp_path, ROWS))
    aff = "Centre for Healthy Ageing, Health Futures Institute, Murdoch University, Perth, Western Australia, Australia"
    org = local.match(aff, "AU")
    assert org.name == "Murdoch University" and org.city == "Perth" and org.match == "ror-local"


def test_generic_names_and_wrong_countries_are_not_taken(tmp_path):
    local = ror_local.LocalRor(_index(tmp_path, ROWS))
    assert (
        local.match("Department of Public Health, Harvard T.H. Chan School of Public Health, Boston, MA, USA", "US")
        is None
    )
    assert local.match("College of Medicine, Flinders University, Adelaide, Australia", "NZ") is None


def test_one_word_names_and_acronyms_need_a_whole_part(tmp_path):
    local = ror_local.LocalRor(_index(tmp_path, ROWS))
    assert local.match("Inserm, Paris, France", "FR").name == "Inserm"
    assert local.match("INSERM U1219, Bordeaux, France", "FR").name == "Inserm"
    assert local.match("Unit of Inserm studies in Lyon, France", "FR") is None


def test_resolver_uses_the_local_copy_before_the_api(tmp_path, monkeypatch):
    monkeypatch.setenv("LABSCOUT_ROR_INDEX", _index(tmp_path, ROWS))
    ror_local.load.cache_clear()

    class NoApi:
        def get_json(self, *a, **k):
            raise AssertionError("the API should not be called")

    try:
        org = ror.Resolver(NoApi())(
            "Flinders Health and Medical Research Institute, Flinders University, Adelaide, Australia"
        )
        assert org.name == "Flinders University" and org.match == "ror-local"
    finally:
        ror_local.load.cache_clear()


def test_the_api_budget_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("LABSCOUT_ROR_INDEX", _index(tmp_path, ROWS))
    monkeypatch.setenv("LABSCOUT_ROR_API_BUDGET", "1")
    ror_local.load.cache_clear()
    calls = []

    class Api:
        def get_json(self, url, params):
            calls.append(params)
            return {"items": []}

    try:
        resolve = ror.Resolver(Api())
        resolve("Some Lab, Somewhere Unknown Place One, Norway")
        resolve("Other Lab, Another Unknown Place Two, Norway")
        assert len([c for c in calls if "affiliation" in c]) == 1
        assert resolve("Third Lab, Elsewhere, Norway").country == "NO"
    finally:
        ror_local.load.cache_clear()
