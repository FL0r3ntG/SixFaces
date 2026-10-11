import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app import scheduler
from app.db import engine
from app.models import utcnow
from app.nlp.categories import CATEGORIES
from app.sources import BY_KEY
from app.web import fmt, views

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
fmt.register(templates.env)
templates.env.globals.update(legend=views.legend, source_name=lambda key: BY_KEY[key].name)

router = APIRouter()


def db():
    with Session(engine) as session:
        yield session


DB = Annotated[Session, Depends(db)]


def page(request: Request, name: str, session: Session, **ctx):
    ctx.setdefault("stats", views.stats(session))
    ctx.setdefault("nav", name.removesuffix(".html"))
    ctx["last_process"] = scheduler.state.get("last_process")
    return templates.TemplateResponse(request, name, ctx)


@router.get("/")
def front(
    request: Request, session: DB, periode: str = "24h", cat: str | None = None, vue: str | None = None
):
    if periode not in views.PERIODS:
        periode = "24h"
    if cat not in CATEGORIES:
        cat = None
    if not cat and periode == "24h" and vue != "liste":
        now = utcnow()
        return page(
            request, "home.html", session, today=now, greeting=fmt.greeting(now), **views.home(session)
        )
    return page(
        request,
        "front.html",
        session,
        cards=views.front_page(session, periode, cat),
        counts=views.category_counts(session, periode),
        periode=periode,
        cat=cat,
        nav="liste",
    )


@router.get("/sujet/{sujet_id}")
def sujet(request: Request, sujet_id: int, session: DB):
    detail = views.sujet_detail(session, sujet_id)
    if detail is None:
        raise HTTPException(404, "Sujet introuvable (il a peut-être été fusionné)")
    return page(request, "sujet.html", session, nav="front", **detail)


@router.get("/couverture")
def couverture(request: Request, session: DB, periode: str = "7j"):
    if periode not in views.PERIODS:
        periode = "7j"
    return page(
        request, "couverture.html", session, periode=periode, **views.coverage_report(session, periode)
    )


@router.get("/sources")
def sources(request: Request, session: DB):
    return page(
        request, "sources.html", session, rows=views.sources_status(session), next_runs=scheduler.next_runs()
    )


@router.get("/recherche")
def recherche(request: Request, session: DB, q: str = ""):
    q = q.strip()
    results = views.search(session, q) if len(q) >= 2 else []
    return page(request, "recherche.html", session, q=q, results=results)


@router.post("/actions/actualiser")
def actualiser():
    """'Actualiser' button: collect every source now, then cluster."""
    if scheduler.scheduler.running:
        scheduler.run_all_soon("bouton Actualiser")
    else:
        threading.Thread(target=scheduler.process, daemon=True).start()
    return RedirectResponse("/sources", status_code=303)
