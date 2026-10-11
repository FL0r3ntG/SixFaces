from app.ingest import byline_section
from app.nlp.categories import CONF_KEYWORD, CONF_NONE, CONF_SECTION, categorize, section_from_url
from app.nlp.similarity import Idf, lexical
from app.nlp.text import clean_title, detect_opinion, detect_wire, entities, entity_tokens


def test_entities_drop_articles_and_sentence_starters():
    assert entities("Les Houthis renouvellent leurs menaces") == {"houthis"}
    assert "houthis" in entities(
        "Douze morts dans une attaque imputée aux Houthis contre l’aéroport de Riyad"
    )
    assert entities("Le Canada, une véritable passoire") == {"canada"}
    assert "pourquoi" not in entities("Pourquoi Québec Solidaire recule")
    assert {"max", "verstappen"} <= entity_tokens("Max Verstappen remporte le GP de Singapour")


def test_wire_from_byline_or_dateline():
    assert detect_wire("La Presse Canadienne", None) == "PC"
    assert detect_wire("Samy Magdy et Cara Anna, The Associated Press", None) == "AP"
    assert detect_wire("The Associated", None) == "AP"  # truncated byline seen in CN2i feeds
    assert detect_wire(None, "PARIS (AFP) — Le gouvernement…") == "AFP"
    assert detect_wire("Jeanne Corriveau", "Le métro de Montréal comporte quatre lignes") is None


def test_opinion():
    assert detect_opinion("https://www.lequotidien.com/opinions/2026/10/10/x/", None)
    assert detect_opinion("https://x/y", "Chroniques")
    assert not detect_opinion("https://www.ledevoir.com/politique/quebec/1/x", "Québec")


def test_clean_title():
    assert clean_title("Trump assure… - La Presse", ("La Presse",)) == "Trump assure…"
    assert clean_title("EN DIRECT | Séisme au Panama") == "Séisme au Panama"


def test_categorize_trusts_sections_over_keywords():
    assert categorize("https://www.lesoleil.com/sports/2026/10/11/x/", "Le ministre au match", None) == (
        "sports",
        CONF_SECTION,
    )
    # generic section ("actualites"): the headline decides, with low confidence
    assert categorize("https://x/actualites/2026/1/x", "Le SPVM enquête sur des coups de feu", None) == (
        "justice",
        CONF_KEYWORD,
    )
    assert categorize(
        "https://www.journaldemontreal.com/2026/10/11/x", "Pour l’amour de la petite chasse", None
    ) == (
        "societe",
        CONF_NONE,
    )
    assert (
        section_from_url("https://www.ledevoir.com/monde/moyen-orient/1016057/slug") == "monde moyen orient"
    )


def test_radio_canada_desk_byline_is_a_section():
    assert byline_section(None, "Zone International") == ("International", None)
    assert byline_section(None, "Zone Arts; Fanny Bourel") == ("Arts", "Fanny Bourel")
    assert byline_section("x", "Jeanne Corriveau") == ("x", "Jeanne Corriveau")


def test_lexical_overlap_favours_shared_rare_names():
    docs = ["Un homme poignardé à Pierrefonds-Roxboro", "Man stabbed in Pierrefonds-Roxboro early Sunday",
            "Le Canadien perd contre les Predators", "Québec annonce un budget", "Québec dévoile un plan"]  # fmt: skip
    idf = Idf(docs)
    v = [idf.vector(d) for d in docs]
    assert lexical(v[0], v[1]) > lexical(v[3], v[4]) * 0.5  # cross-language, held by the place name
    assert lexical(v[0], v[2]) == 0


def test_pair_probabilities_use_time_for_events_not_stories():
    from app.nlp.similarity import p_event, p_story

    # time apart lowers "same development" a lot; moderately similar pieces a day apart are a new development
    assert p_event(0.75, 0.45, 2) - p_event(0.75, 0.45, 30) > 0.25
    assert p_event(0.65, 0.30, 2) > 0.6 > p_event(0.65, 0.30, 30)
    assert p_story(0.75, 0.45) > 0.7  # ...but still the same story
    assert p_story(0.45, 0.0) < 0.2  # vaguely similar wording, no shared words: unrelated
