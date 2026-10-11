"""Rebuild every event and sujet from scratch with the current code.

Needed after a change to similarity, clustering, copy detection or category rules: already-clustered
articles are never revisited otherwise. Articles, page text and embeddings are kept; only the grouping is
redone (about 30 s for a few thousand articles).

    systemctl --user stop six-faces      # only one process may write the database
    uv run python -m scripts.recluster
    systemctl --user start six-faces
"""

import logging
import socket
import sys

from sqlmodel import Session, text

from app import cluster, rank
from app.db import engine
from app.main import migrate


def service_running(port: int = 8010) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if service_running() and "--force" not in sys.argv:
        sys.exit(
            "The app is running on :8010 — stop it first (systemctl --user stop six-faces), or pass --force."
        )
    migrate()
    with Session(engine) as session:
        session.exec(text("update article set event_id = null, processed = 0, dup_of = null"))
        session.exec(text("delete from event"))
        session.exec(text("delete from sujet"))
        session.commit()
    print(cluster.process())
    print("ranked", rank.rank_all(), "events")


if __name__ == "__main__":
    main()
