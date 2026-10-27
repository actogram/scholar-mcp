"""Small text helpers: names, e-mail removal, species and data signals, countries."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

EMAIL = re.compile(r"(?:electronic address:\s*)?[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
STOP = {
    "the",
    "and",
    "for",
    "of",
    "in",
    "on",
    "at",
    "to",
    "a",
    "an",
    "de",
    "del",
    "la",
    "le",
    "les",
    "des",
    "di",
    "da",
    "do",
    "und",
    "fur",
    "van",
    "von",
    "der",
    "y",
    "et",
    "e",
    "or",
    "not",
    "with",
    "from",
    "by",
}
QUERY_WORDS = {"and", "or", "not"}

# MeSH descriptors and words that say which species a study works with
SPECIES = [
    ("human", ("humans",), r"\b(participants?|volunteers?|adults?|children|adolescents?|older adults|men|women)\b"),
    ("mouse", ("mice", "mice, inbred c57bl", "mice, knockout", "mice, transgenic"), r"\b(mice|mouse|murine)\b"),
    ("rat", ("rats", "rats, sprague-dawley", "rats, wistar"), r"\b(rats?)\b"),
    ("fruit fly", ("drosophila", "drosophila melanogaster"), r"\bdrosophila\b"),
    ("zebrafish", ("zebrafish",), r"\bzebrafish\b"),
    ("non-human primate", ("macaca", "macaca mulatta", "primates"), r"\b(macaques?|monkeys?|primates?)\b"),
]

# what kind of data a study holds, from its title, abstract, keywords and MeSH
SIGNALS = [
    ("actigraphy", r"\bactigraph\w*"),
    ("accelerometry", r"\baccelerometr\w*|\baccelerometer\w*"),
    ("wearables", r"\bwearables?\b|\bsmart ?watch\w*|\bfitbit\b|\boura\b|\bapple watch\b|\bgarmin\b|\bwhoop\b"),
    ("step counts", r"\bstep counts?\b|\bdaily steps\b|\bpedometer\w*"),
    ("longitudinal", r"\blongitudinal\b|\bfollow-up\b|\brepeated measures?\b|\bprospective\b"),
    ("cohort", r"\bcohorts?\b|\bbiobank\b"),
    ("polysomnography", r"\bpolysomnograph\w*"),
    ("light exposure", r"\blight exposure\b|\blight sensor\w*"),
    ("shift work", r"\bshift ?work\w*|\bnight shifts?\b"),
    ("diaries", r"\bsleep diar(y|ies)\b|\becological momentary\b"),
]

COUNTRY_ALIASES = {
    "usa": "US",
    "u.s.a": "US",
    "u.s.a.": "US",
    "united states of america": "US",
    "united states": "US",
    "us": "US",
    "uk": "GB",
    "u.k.": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "south korea": "KR",
    "korea": "KR",
    "republic of korea": "KR",
    "russia": "RU",
    "the netherlands": "NL",
    "netherlands": "NL",
    "czech republic": "CZ",
    "iran": "IR",
    "taiwan": "TW",
    "vietnam": "VN",
    "turkey": "TR",
    "türkiye": "TR",
    "espagne": "ES",
    "españa": "ES",
    "deutschland": "DE",
    "allemagne": "DE",
    "italia": "IT",
    "brasil": "BR",
    "méxico": "MX",
    "p.r. china": "CN",
    "pr china": "CN",
    "people's republic of china": "CN",
}
US_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}


def fold(s: str) -> str:
    """Lower case without accents, for comparisons."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(s))


def significant(s: str) -> set[str]:
    return {w for w in words(s) if len(w) >= 3 and w not in STOP}


def name_key(last: str, fore: str = "", initials: str = "") -> str:
    """'Redline S' style key: last name plus the first initial, accents and case removed."""
    first = (initials or fore or "")[:1]
    return f"{'-'.join(words(last))} {fold(first)}".strip()


def clean_affiliation(s: str) -> str:
    """Affiliation text without e-mail addresses and without the spaces and dots left around them."""
    s = EMAIL.sub("", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"[\s,;.]+$", "", s)


def query_terms(query: str) -> list[str]:
    """The words of a search, without search operators, field tags and quotes."""
    q = re.sub(r"\[[^\]]*\]", " ", query or "")
    out = []
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]+", q):
        lw = fold(w)
        if lw in QUERY_WORDS or lw in STOP or len(lw) < 3 or lw in out:
            continue
        out.append(lw)
    return out


def species_of(mesh: list[str], text: str) -> list[str]:
    m = {fold(x) for x in mesh}
    t = fold(text)
    found = []
    for label, terms, pattern in SPECIES:
        if any(term in m for term in terms) or (label != "human" and re.search(pattern, t)):
            found.append(label)
    if "human" not in found and not found and re.search(SPECIES[0][2], t):
        found.append("human")
    return found


def signals_of(text: str) -> list[str]:
    t = fold(text)
    return [label for label, pattern in SIGNALS if re.search(pattern, t)]


@lru_cache(maxsize=1)
def _countries() -> dict[str, str]:
    import pycountry

    names: dict[str, str] = {}
    for c in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            v = getattr(c, attr, None)
            if v:
                names[fold(v)] = c.alpha_2
    names.update({fold(k): v for k, v in COUNTRY_ALIASES.items()})
    return names


def country_from_text(affiliation: str) -> str:
    """ISO code of the country named at the end of an affiliation, or '' when it is not clear."""
    parts = [p.strip(" .") for p in re.split(r"[,;]", affiliation or "") if p.strip(" .")]
    table = _countries()
    for part in reversed(parts[-3:]):
        code = table.get(fold(part))
        if code:
            return code
        tokens = part.split()
        if tokens and tokens[0] in US_STATES and (len(tokens) == 1 or tokens[1].isdigit()):
            return "US"
    return ""


def country_name(code: str) -> str:
    if not code:
        return ""
    import pycountry

    c = pycountry.countries.get(alpha_2=code)
    return getattr(c, "common_name", None) or getattr(c, "name", "") if c else code
