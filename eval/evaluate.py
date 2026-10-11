"""Score the clustering against the hand-labelled pairs in eval/pairs.json.

Re-clusters a *copy* of data/six_faces.db from scratch with the current code (the live database is not touched),
then reports pairwise precision/recall for "same event" and "same sujet", and the largest sujets (a sujet that
swallows unrelated developments shows up there, not in pair metrics).

    uv run python eval/evaluate.py            # current thresholds
    uv run python eval/evaluate.py P_SUJET=0.6 P_MERGE=0.8    # try other values of app.cluster constants
    EVAL_DB=/path/snapshot.db uv run python eval/evaluate.py  # start from another database (e.g. one whose
                                                              # embeddings are already computed: much faster)
"""

import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp()) / "eval.db"
src = sqlite3.connect(os.environ.get("EVAL_DB") or ROOT / "data" / "six_faces.db")
dst = sqlite3.connect(tmp)
src.backup(dst)
src.close()
dst.close()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"
os.environ["SCHEDULER_ENABLED"] = "false"
sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.WARNING)

from alembic import command
from alembic.config import Config
from sqlmodel import Session, select, text

import app.cluster as C
from app.db import engine
from app.models import Article, Event

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")  # the copy may predate the current schema
logging.getLogger().setLevel(logging.WARNING)

for kv in sys.argv[1:]:
    k, v = kv.split("=")
    setattr(C, k, timedelta(hours=float(v)) if k.endswith(("WINDOW", "SPAN")) else float(v))

with Session(engine) as s:
    s.exec(text("update article set event_id=null, processed=0, dup_of=null"))
    s.exec(text("delete from event"))
    s.exec(text("delete from sujet"))
    s.commit()
print(C.process())
with Session(engine) as s:
    rows = s.exec(select(Article.url, Article.id, Article.event_id, Article.dup_of)).all()
    sujet_of = dict(s.exec(select(Event.id, Event.sujet_id)).all())
by_url = {u: (i, e, d) for u, i, e, d in rows}
event_of = {i: e for _, i, e, _ in rows}


def ev(url):
    _id, e, d = by_url[url]
    return event_of[d] if d else e


pairs = [
    p
    for p in json.loads((ROOT / "eval" / "pairs.json").read_text())["pairs"]
    if p["a"]["url"] in by_url and p["b"]["url"] in by_url
]


def score(subset):
    out = []
    for truth, same in (
        ("E", lambda p: ev(p["a"]["url"]) == ev(p["b"]["url"])),
        ("ES", lambda p: sujet_of[ev(p["a"]["url"])] == sujet_of[ev(p["b"]["url"])]),
    ):
        tp = sum(1 for p in subset if p["label"] in truth and same(p))
        fp = sum(1 for p in subset if p["label"] not in truth and same(p))
        fn = sum(1 for p in subset if p["label"] in truth and not same(p))
        prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        out.append(f"P {prec:.2f} R {rec:.2f} F1 {2 * prec * rec / max(prec + rec, 1e-9):.2f}")
    return out


print(f"{'':10s} {'même événement':24s} même sujet")
for name, subset in (
    ("tout", pairs),
    ("spread", [p for p in pairs if p.get("set") == "spread"]),
    ("recall", [p for p in pairs if p.get("set") == "recall"]),
):
    e, st = score(subset)
    print(f"{name:10s} {e:24s} {st}   ({len(subset)} paires)")
sizes = Counter(sujet_of.values()).most_common(5)
print(
    f"{len(pairs)} paires · {len(sujet_of)} événements · plus gros sujets: {[n for _, n in sizes]} développements"
)
shutil.rmtree(tmp.parent, ignore_errors=True)
