"""Every page renders, on an empty database and with one clustered sujet (no network, no embedding model)."""

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.models import Article, Event, Sujet, utcnow
from app.verify import verify_event

PAGES = ["/", "/?periode=7j", "/?cat=politique", "/couverture", "/sources", "/recherche?q=Legault"]


def test_pages_render_empty():
    with TestClient(app) as client:
        for path in PAGES:
            r = client.get(path)
            assert r.status_code == 200, path
        assert client.get("/sujet/12345").status_code == 404


def test_sujet_page_with_timeline():
    now = utcnow()
    with TestClient(app) as client, Session(engine) as session:
        sujet = Sujet(first_at=now, last_at=now, title="Séisme au Panama", category="international", n_events=1,
                      n_articles=2, n_sources=2, n_groups=2, groups=json.dumps({"cbcrc": 1, "quebecor": 1}))  # fmt: skip
        session.add(sujet)
        session.flush()
        ev = Event(first_at=now - timedelta(hours=2), last_at=now, title="Séisme au Panama", sujet_id=sujet.id,
                   n_articles=2, n_groups=2, category="international")  # fmt: skip
        session.add(ev)
        session.flush()
        arts = [
            Article(source_key="rc", group="cbcrc", url="https://ici.radio-canada.ca/1", title="Séisme: 3 morts",
                    title_norm="a", published_at=now - timedelta(hours=2), event_id=ev.id, processed=True),
            Article(source_key="jdm", group="quebecor", url="https://www.journaldemontreal.com/1",
                    title="Séisme: 4 morts au Panama", title_norm="b", published_at=now, event_id=ev.id,
                    headline_only=True, processed=True),
        ]  # fmt: skip
        session.add_all(arts)
        session.flush()
        ev.verification = json.dumps(verify_event(arts), default=str)
        session.add(ev)
        session.commit()

        r = client.get(f"/sujet/{sujet.id}")
        assert r.status_code == 200
        assert "Chronologie" in r.text and "Séisme: 4 morts au Panama" in r.text
        assert "Chiffres différents" in r.text  # 3 vs 4 dead
        assert "Séisme au Panama" in client.get("/").text
        assert "Séisme" in client.get("/recherche?q=Séisme").text
