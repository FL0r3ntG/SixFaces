"""Shared Quebec topic taxonomy. Each outlet's own sections (URL path, feed tags) are mapped onto it, with
keyword rules on the headline as a fallback. No LLM."""

import re

from app.nlp.text import normalize

CATEGORIES: dict[str, str] = {
    "politique": "Politique",
    "economie": "Économie",
    "sante": "Santé",
    "education": "Éducation",
    "justice": "Justice et faits divers",
    "environnement": "Environnement",
    "international": "International",
    "societe": "Société",
    "culture": "Culture",
    "sports": "Sports",
    "techno": "Science et techno",
}

# Section words found in URLs / feed tags -> category. Checked on normalized text, first match wins, so the
# more specific entries come first.
_SECTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "sports",
        (
            "sports",
            "sport",
            "hockey",
            "canadiens",
            "football",
            "soccer",
            "tennis",
            "baseball",
            "golf",
            "formule 1",
            "f1",
            "boxe",
            "nhl",
            "alouettes",
            "mma",
            "basketball",
            "cyclisme",
            "olympiques",
        ),
    ),
    (
        "culture",
        (
            "arts",
            "culture",
            "spectacles",
            "cinema",
            "musique",
            "television",
            "tele",
            "livres",
            "entertainment",
            "celebrites",
            "divertissement",
            "theatre",
            "humour",
            "gastronomie",
            "restaurants",
            "voyage",
            "mode",
            "art de vivre",
            "style de vie",
        ),
    ),
    (
        "techno",
        ("techno", "technologie", "science", "sciences", "tech", "espace", "intelligence artificielle"),
    ),
    ("sante", ("sante", "health", "covid")),
    ("environnement", ("environnement", "environment", "climat", "climate", "meteo", "weather", "energie")),
    ("education", ("education", "ecoles", "universites")),
    (
        "justice",
        (
            "justice",
            "faits divers",
            "faits-divers",
            "crime",
            "police",
            "tribunaux",
            "proces",
            "judiciaire",
            "policiers",
        ),
    ),
    (
        "politique",
        (
            "politique",
            "politics",
            "elections",
            "election",
            "quebec politique",
            "federal",
            "assemblee nationale",
            "ottawa",
        ),
    ),
    (
        "economie",
        (
            "economie",
            "affaires",
            "business",
            "finances personnelles",
            "consommation",
            "argent",
            "immobilier",
            "emploi",
            "techno affaires",
            "bourse",
        ),
    ),
    (
        "international",
        (
            "international",
            "monde",
            "world",
            "etats unis",
            "europe",
            "asie",
            "afrique",
            "moyen orient",
            "ameriques",
            "us news",
        ),
    ),
    (
        "societe",
        (
            "societe",
            "actualites",
            "local",
            "regional",
            "national",
            "canada",
            "montreal",
            "quebec",
            "news",
            "transports",
            "urbanisme",
            "logement",
            "immigration",
            "autochtones",
            "religion",
        ),
    ),
]

# Headline keywords (normalized, matched as whole words). Used when the section is missing or generic.
_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "politique",
        (
            "caq",
            "pq",
            "pqp",
            "plq",
            "qs",
            "pcq",
            "quebec solidaire",
            "parti quebecois",
            "parti liberal",
            "conservateur",
            "assemblee nationale",
            "ministre",
            "premier ministre",
            "depute",
            "deputee",
            "gouvernement",
            "legault",
            "st pierre plamondon",
            "carney",
            "poilievre",
            "elections",
            "election",
            "scrutin",
            "cabinet",
            "conseil des ministres",
            "mairesse",
            "maire",
            "conseil municipal",
            "budget",
            "minister",
            "mna",
            "mp",
            "parliament",
            "parlement",
            "senat",
            "trump",
        ),
    ),
    (
        "justice",
        (
            "police",
            "spvm",
            "sq",
            "surete du quebec",
            "arrete",
            "arrestation",
            "accuse",
            "accusee",
            "proces",
            "tribunal",
            "juge",
            "meurtre",
            "homicide",
            "poignarde",
            "coups de feu",
            "enquete",
            "collision",
            "incendie",
            "accident",
            "suspect",
            "victime",
            "arrested",
            "charged",
            "court",
            "stabbed",
            "shooting",
            "fire",
            "crash",
            "sentenced",
            "condamne",
            "fraude",
        ),
    ),
    (
        "sante",
        (
            "hopital",
            "urgences",
            "sante",
            "medecin",
            "infirmieres",
            "chsld",
            "virus",
            "vaccin",
            "maladie",
            "hospital",
            "patients",
            "cancer",
            "sante quebec",
            "norovirus",
            "rougeole",
        ),
    ),
    (
        "education",
        (
            "ecole",
            "ecoles",
            "enseignants",
            "eleves",
            "cegep",
            "universite",
            "school",
            "teachers",
            "centre de services scolaire",
        ),
    ),
    (
        "economie",
        (
            "inflation",
            "taux",
            "banque du canada",
            "emplois",
            "mises a pied",
            "entreprise",
            "usine",
            "tarifs",
            "droits de douane",
            "bourse",
            "hydro quebec",
            "greve",
            "syndicat",
            "economy",
            "jobs",
            "tariffs",
            "layoffs",
            "logement",
            "loyers",
            "immobilier",
        ),
    ),
    (
        "environnement",
        (
            "climat",
            "climatique",
            "environnement",
            "pollution",
            "inondation",
            "feux de foret",
            "tempete",
            "neige",
            "verglas",
            "ouragan",
            "climate",
            "storm",
            "flood",
        ),
    ),
    (
        "international",
        (
            "ukraine",
            "russie",
            "israel",
            "gaza",
            "iran",
            "chine",
            "etats unis",
            "washington",
            "europe",
            "france",
            "houthis",
            "liban",
            "syrie",
            "pakistan",
            "inde",
            "mexique",
            "russia",
            "china",
            "united states",
        ),
    ),
    (
        "sports",
        (
            "canadien",
            "canadiens",
            "lnh",
            "nhl",
            "match",
            "victoire",
            "defaite",
            "championnat",
            "coupe",
            "grand prix",
            "alouettes",
            "cf montreal",
            "joueur",
            "entraineur",
            "tournoi",
        ),
    ),
    (
        "culture",
        (
            "film",
            "album",
            "spectacle",
            "festival",
            "artiste",
            "chanteur",
            "chanteuse",
            "serie",
            "roman",
            "exposition",
            "concert",
            "gala",
        ),
    ),
]


def _match(text: str, rules: list[tuple[str, tuple[str, ...]]]) -> str | None:
    padded = f" {text} "
    for cat, words in rules:
        if any(f" {w} " in padded for w in words):
            return cat
    return None


def section_from_url(url: str) -> str | None:
    """'/actualites/politique/2026/...' -> 'actualites politique'; ignores dates, ids and slugs."""
    path = re.sub(r"^https?://[^/]+", "", url).split("?")[0]
    parts = [p for p in path.split("/") if p]
    keep = []
    for p in parts[:-1]:  # last part is the slug
        if p.isdigit() or re.fullmatch(r"[\d.-]+", p) or len(p) > 40 or p in ("article", "nouvelles", "news"):
            continue
        keep.append(p.replace("-", " "))
    return " ".join(keep[:3]) or None


# How much an article's category can be trusted (votes in the event, seeds for the nearest-neighbour step)
CONF_SECTION, CONF_KEYWORD, CONF_NONE = 1.0, 0.4, 0.0


def categorize(url: str, title: str, section: str | None, tags: list[str] | None = None) -> tuple[str, float]:
    """(category, confidence). The outlet's own section is trusted; headline keywords are a weak guess."""
    sec = normalize(" ".join(filter(None, [section, *(tags or []), section_from_url(url) or ""])))
    by_section = _match(sec, _SECTION_RULES)
    # "actualites", "news", "canada" etc. say nothing about the topic: let the headline decide
    if by_section and by_section != "societe":
        return by_section, CONF_SECTION
    by_keyword = _match(normalize(title), _KEYWORD_RULES)
    if by_keyword:
        return by_keyword, CONF_KEYWORD
    if by_section:
        return by_section, CONF_KEYWORD
    return "societe", CONF_NONE
