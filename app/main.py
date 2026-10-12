import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import scheduler
from app.config import ROOT, get_settings
from app.web.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    # alembic.ini's logging config lowers the root level to WARNING: restore ours
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("alembic").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    if get_settings().scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title=get_settings().app_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    if not get_settings().allow_indexing:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
app.include_router(router)
