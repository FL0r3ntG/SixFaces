from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_name: str = "Six-Faces"  # shown in the masthead, top bar and page titles
    app_tagline: str = "La presse québécoise, sous toutes ses faces"
    database_url: str = f"sqlite:///{ROOT / 'data' / 'six_faces.db'}"
    model_cache_dir: Path = ROOT / "data" / "models"
    embedding_model: str = (
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"  # fast: filtering, copies
    )
    matching_model: str = "intfloat/multilingual-e5-large"  # stronger: same event / same story decisions

    scheduler_enabled: bool = True
    # Public site: read-only (no "Actualiser" action, no internal error details) and not indexed by search
    # engines. Collection keeps running on its own schedule.
    public_mode: bool = False
    allow_indexing: bool = False
    discover_interval_minutes: int = 15  # RSS + news sitemaps
    gnews_interval_minutes: int = 30  # Google News feeds (headline-only sources)
    process_interval_minutes: int = 5  # embed + cluster + rank
    enrich_batch_size: int = 40  # article pages fetched per enrich run
    host_delay_s: float = 2.0  # min gap between two requests to the same host

    user_agent: str = "Mozilla/5.0 (compatible; six-faces/0.1; usage personnel non commercial)"
    display_tz: str = "America/Toronto"  # heure du Québec


@lru_cache
def get_settings() -> Settings:
    return Settings()
