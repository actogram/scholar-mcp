from conftest import FakeHttp, fixture_json

from actogram_scholar.sources.ror import Resolver

FLINDERS = (
    "Flinders Health and Medical Research Institute (Sleep Health), College of Medicine and Public Health, "
    "Flinders University, Adelaide, South Australia, Australia"
)
HARVARD = "Department of Epidemiology, Harvard T.H. Chan School of Public Health, Boston, MA, USA"


def _org(name, city, country, lat=1.0, lng=2.0, ror="https://ror.org/0test"):
    return {
        "id": ror,
        "names": [{"value": name, "types": ["ror_display", "label"]}],
        "locations": [
            {
                "geonames_details": {
                    "name": city,
                    "country_code": country,
                    "country_name": country,
                    "lat": lat,
                    "lng": lng,
                }
            }
        ],
    }


def test_chosen_match_is_accepted_with_its_place():
    http = FakeHttp({"api.ror.org": fixture_json("ror_flinders.json")})
    org = Resolver(http)(FLINDERS)
    assert org.name == "Flinders University" and org.match == "ror"
    assert org.city == "Adelaide" and org.country == "AU" and org.lat and org.lon
    assert org.ror == "https://ror.org/01kpzv902"


def test_a_wrong_suggestion_is_not_taken():
    # ROR suggests "Hanoi School Of Public Health" for Harvard Chan without choosing it
    def answer(url, params):
        if "affiliation" in params:
            return fixture_json("ror_harvard.json")
        return {"items": [_org("Andalusian School of Public Health", "Granada", "ES")]}

    org = Resolver(FakeHttp({"api.ror.org": answer}))(HARVARD)
    assert org.match == "text" and org.country == "US" and org.lat is None
    assert "Hanoi" not in org.name


def test_name_search_is_accepted_only_when_all_words_fit():
    aff = "Centre for Healthy Ageing, Health Futures Institute, Murdoch University, Perth, Western Australia, Australia"

    def answer(url, params):
        if "affiliation" in params:
            return {"items": []}
        return {
            "items": [
                _org("Murdoch Children's Research Institute", "Melbourne", "AU"),
                _org("Murdoch University", "Perth", "AU", ror="https://ror.org/00r4sry34"),
            ]
        }

    org = Resolver(FakeHttp({"api.ror.org": answer}))(aff)
    assert org.name == "Murdoch University" and org.match == "ror-name" and org.city == "Perth"


def test_each_affiliation_is_looked_up_once():
    http = FakeHttp({"api.ror.org": fixture_json("ror_flinders.json")})
    resolve = Resolver(http)
    resolve(FLINDERS)
    resolve(FLINDERS + ".")
    assert len(http.calls) == 1


def test_ror_being_down_does_not_stop_the_search():
    def down(url, params):
        raise RuntimeError("ROR is down")

    org = Resolver(FakeHttp({"api.ror.org": down}))(FLINDERS)
    assert org.match == "text" and org.country == "AU"
