"""Same piece on several sites of one owner = one article everywhere."""

from datetime import UTC, datetime, timedelta

import numpy as np

from app.cluster import _Pool
from app.models import Article
from app.nlp.embed import to_bytes
from app.nlp.similarity import Idf
from app.web.views import outlet

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=UTC)
_ids = iter(range(1, 1000))


def art(source, group, title, vec, hours_ago=1.0, event_id=1):
    v = np.zeros(8, dtype=np.float32)
    v[vec[0]] = 1.0
    if len(vec) > 1:
        v[vec[1]] = 0.2
    v /= np.linalg.norm(v)
    i = next(_ids)
    return Article(
        id=i, source_key=source, group=group, url=f"https://x/{i}", title=title, title_norm=title.lower(),
        published_at=NOW - timedelta(hours=hours_ago), embedding=to_bytes(v), event_id=event_id,
    )  # fmt: skip


def test_same_title_same_owner_is_a_copy():
    jdm = art("jdm", "quebecor", "Le Canada, une passoire", (0,))
    pool = _Pool([jdm], Idf([jdm.title]))
    assert pool.copy_of(art("jdq", "quebecor", "Le Canada, une passoire", (3,))) is jdm
    # another owner with the same headline is agency copy, not a same-owner duplicate
    assert pool.copy_of(art("devoir", "devoir", "Le Canada, une passoire", (0,))) is None
    # too far apart in time: a different piece
    assert pool.copy_of(art("tva", "quebecor", "Le Canada, une passoire", (0,), hours_ago=80)) is None


def test_near_identical_text_same_owner_is_a_copy():
    soleil = art("soleil", "cn2i", "Attaque à Riyad: 12 morts", (1,))
    pool = _Pool([soleil], Idf([soleil.title]))
    assert pool.copy_of(art("droit", "cn2i", "Attaque à Riyad : 12 morts", (1,))) is soleil
    assert pool.copy_of(art("droit", "cn2i", "Autre chose", (5,))) is None


def test_outlet_label():
    assert outlet("jdm", "quebecor", ["jdq", "tva"])["name"] == "Québecor"
    assert outlet("jdm", "quebecor", ["jdq", "tva"])["sites"] == [
        "Le Journal de Montréal", "Le Journal de Québec", "TVA Nouvelles",
    ]  # fmt: skip
    assert outlet("jdm", "quebecor", [])["name"] == "Le Journal de Montréal"


def test_same_headline_across_mastheads():
    from app.nlp.text import same_headline

    # agency copy under two mastheads: identical, rubric prefix, punctuation, one letter
    assert same_headline("Le Panama déclare l’état d’urgence", "Le Panama déclare l'état d'urgence")
    assert same_headline("Fête nationale | Taïwan ne renoncera pas à sa liberté, affirme son président",
                         "Taïwan ne renoncera pas à sa liberté, affirme son président")  # fmt: skip
    assert same_headline("Le projet d’alliance Canada-UE doit être défini et vite",
                         "Le projet d’alliance Canada-EU doit être défini et vite")  # fmt: skip
    # same story, each outlet's own article: NOT the same piece
    assert not same_headline("Trump affirme qu'«il est temps pour l'Ukraine d'avoir un nouveau président»",
                             "Donald Trump estime que l'Ukraine devrait avoir un nouveau président")  # fmt: skip
    assert not same_headline("Expulsé de la CAQ, Mathieu Lacombe s'excuse d'avoir été au party du PQ",
                             "Exclu de la CAQ, Mathieu Lacombe s’excuse de s’être rendu à la soirée")  # fmt: skip


def test_same_piece_from_another_owner():
    noovo = art("noovo", "bell", "Séismes: le Panama déclare l’état d’urgence", (2,))
    pool = _Pool([noovo], Idf([noovo.title]))
    assert (
        pool.same_piece(art("lactualite", "mishmash", "Séismes: le Panama déclare l'état d'urgence", (2,)))
        is noovo
    )
    assert pool.same_piece(art("rc", "cbcrc", "Le Panama sous le choc après deux séismes", (2,))) is None
    assert (
        pool.same_piece(art("jdm", "bell", "Séismes: le Panama déclare l’état d’urgence", (2,))) is None
    )  # same owner
