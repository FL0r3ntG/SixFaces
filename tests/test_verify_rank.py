from datetime import UTC, datetime, timedelta

from app.cluster import _vote_category
from app.models import Article
from app.rank import event_score
from app.verify import CONFIRMED, CORROBORATED, SINGLE, WIRE_ONLY, figures, verify_event

NOW = datetime(2026, 10, 11, 18, 0, tzinfo=UTC)
_id = iter(range(1, 10000))


def art(group, title="Titre", hours_ago=1.0, wire=None, source=None, **kw):
    return Article(
        id=next(_id), source_key=source or group, group=group, url=f"https://x/{next(_id)}", title=title,
        title_norm=title.lower(), published_at=NOW - timedelta(hours=hours_ago), wire=wire, **kw,
    )  # fmt: skip


def test_figures():
    assert figures("Au moins 12 morts et plus de 40 blessés; douze personnes tuées") == {
        "morts": 12,
        "blessés": 40,
    }
    assert figures("Four people were killed and 1,200 evacuated") == {"morts": 4, "évacués": 1200}
    assert figures("Le Canadien gagne 4 à 1") == {}


def test_status_counts_groups_not_sites_and_ignores_wire():
    # six CN2i sites reprinting AP + one Québecor piece = single independent source
    arts = [art("cn2i", f"t{i}", wire="AP", source=f"cn2i{i}") for i in range(6)] + [art("quebecor", "own")]
    v = verify_event(arts)
    assert v["status"] == SINGLE and v["independent"] == ["quebecor"] and v["wire_only_groups"] == ["cn2i"]
    assert verify_event([art("cn2i", wire="PC")])["status"] == WIRE_ONLY
    assert verify_event([art("devoir", "a"), art("cbcrc", "b")])["status"] == CORROBORATED
    assert verify_event([art("devoir", "a"), art("cbcrc", "b"), art("lapresse", "c")])["status"] == CONFIRMED


def test_identical_headlines_across_groups_are_copy():
    arts = [art("devoir", "Même titre de la PC"), art("cn2i", "Même titre de la PC"), art("cbcrc", "Autre")]
    v = verify_event(arts)
    assert v["independent"] == ["cbcrc"] and v["status"] == SINGLE


def test_divergent_figures_are_reported():
    arts = [
        art("devoir", "Attaque: 21 morts"),
        art("cn2i", "Attaque: 20 morts"),
        art("cbcrc", "Attaque meurtrière"),
    ]
    [f] = verify_event(arts)["figures"]
    assert f["unit"] == "morts" and f["values"] == [20, 21] and f["divergent"]


def test_score_breadth_beats_volume_and_decays():
    syndicated = [art("quebecor", source=s) for s in ("jdm", "jdq", "tva")] * 3
    broad = [art(g) for g in ("quebecor", "lapresse", "devoir")]
    assert event_score(broad, NOW) > event_score(syndicated, NOW)
    assert (
        event_score([art("devoir", hours_ago=36)], NOW) < event_score([art("devoir", hours_ago=1)], NOW) / 3
    )
    assert event_score([art("devoir", featured=True)], NOW) > event_score([art("devoir")], NOW)


def test_category_vote_one_vote_per_group():
    arts = [art("cn2i", category="economie", category_conf=1.0, wire="AP", source=f"c{i}") for i in range(6)]
    arts += [art("devoir", category="international", category_conf=1.0)]
    arts += [art("quebecor", category="economie", category_conf=0.0, source=s) for s in ("jdm", "jdq", "tva")]
    assert _vote_category(arts) == "international"
