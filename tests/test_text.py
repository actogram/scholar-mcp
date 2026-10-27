from actogram_scholar.text import (
    clean_affiliation,
    country_from_text,
    name_key,
    query_terms,
    signals_of,
    species_of,
)


def test_clean_affiliation_removes_email_addresses():
    raw = "Duke University School of Medicine (A Author), Durham, NC. Electronic address: someone@example.edu."
    assert clean_affiliation(raw) == "Duke University School of Medicine (A Author), Durham, NC"
    assert "@" not in clean_affiliation("Caen, France. person@example.org")


def test_name_key_ignores_accents_case_and_middle_names():
    assert name_key("Poisnel", "Géraldine") == "poisnel g"
    assert name_key("D'Agata", "Michele N", "MN") == "d-agata m"
    assert name_key("Redline", "", "SS") == name_key("REDLINE", "Susan")


def test_query_terms_drop_operators_and_field_tags():
    assert query_terms('actigraphy AND "sleep regularity"[tiab] OR older adults') == [
        "actigraphy",
        "sleep",
        "regularity",
        "older",
        "adults",
    ]


def test_species_from_mesh_and_text():
    assert species_of(["Humans", "Mice"], "") == ["human", "mouse"]
    assert species_of([], "We studied zebrafish larvae") == ["zebrafish"]
    assert species_of([], "Participants wore a watch") == ["human"]


def test_data_signals():
    found = signals_of("Wrist actigraphy and Fitbit step counts in a prospective cohort with sleep diaries")
    assert {"actigraphy", "wearables", "step counts", "longitudinal", "cohort", "diaries"} <= set(found)


def test_country_from_text():
    assert country_from_text("Flinders University, Adelaide, South Australia, Australia") == "AU"
    assert country_from_text("Duke University School of Medicine, Durham, NC") == "US"
    assert country_from_text("Universitat Oberta de Catalunya, Barcelona, 08018, Espagne") == "ES"
    assert country_from_text("Department of Medicine") == ""
