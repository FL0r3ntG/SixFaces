"""Background jobs: discover (per source), enrich (page text), process (cluster + rank).

Made for a laptop, like appart_finder: late runs after sleep still run (misfire_grace_time=None), missed runs
collapse into one (coalesce), and a watchdog notices a suspend/resume and runs everything again soon.
"""

import logging
import socket
import threading
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app import cluster, ingest, rank
from app.config import get_settings
from app.sources import SOURCES

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler(
    timezone="UTC", job_defaults={"misfire_grace_time": None, "coalesce": True, "max_instances": 1}
)

RESUME_CHECK_S = 20
RESUME_THRESHOLD_S = 120  # wall clock jumped this much more than the monotonic clock -> we were asleep
STAGGER_S = 8

state: dict[str, datetime | None] = {"last_resume": None, "last_process": None}
_process_lock = threading.Lock()


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        log.exception("job %s%s crashed", fn.__name__, args)


def discover(key: str, kinds: tuple[str, ...]) -> None:
    _safe(ingest.run_source, key, kinds)


def enrich() -> None:
    _safe(ingest.enrich_pending, get_settings().enrich_batch_size)


def images() -> None:
    _safe(ingest.backfill_images, 30)


def process() -> None:
    with _process_lock:  # also triggered from the web page
        _safe(cluster.process)
        _safe(rank.rank_all)
        state["last_process"] = datetime.now()


def start() -> None:
    s = get_settings()
    now = datetime.now(scheduler.timezone)
    for i, src in enumerate(SOURCES):
        first = now + timedelta(seconds=10 + STAGGER_S * i)
        kinds = {f.kind for f in src.feeds}
        if kinds - {"gnews"}:
            scheduler.add_job(
                discover, "interval", minutes=s.discover_interval_minutes, jitter=60,
                args=[src.key, ("rss", "sitemap")], id=f"discover:{src.key}", next_run_time=first,
                replace_existing=True,
            )  # fmt: skip
        if "gnews" in kinds:
            scheduler.add_job(
                discover, "interval", minutes=s.gnews_interval_minutes, jitter=120,
                args=[src.key, ("gnews",)], id=f"gnews:{src.key}", next_run_time=first, replace_existing=True,
            )  # fmt: skip
    scheduler.add_job(
        enrich,
        "interval",
        minutes=3,
        id="enrich",
        next_run_time=now + timedelta(minutes=1),
        replace_existing=True,
    )
    scheduler.add_job(
        images,
        "interval",
        minutes=4,
        id="images",
        next_run_time=now + timedelta(minutes=3),
        replace_existing=True,
    )
    scheduler.add_job(
        process, "interval", minutes=s.process_interval_minutes, id="process",
        next_run_time=now + timedelta(minutes=2), replace_existing=True,
    )  # fmt: skip
    scheduler.start()
    threading.Thread(target=_resume_watchdog, name="resume-watchdog", daemon=True).start()
    log.info("scheduler started: %d jobs", len(scheduler.get_jobs()))


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def run_all_soon(reason: str) -> None:
    now = datetime.now(scheduler.timezone)
    jobs = [j for j in scheduler.get_jobs() if j.id.startswith(("discover:", "gnews:"))]
    for i, job in enumerate(jobs):
        job.modify(next_run_time=now + timedelta(seconds=5 + STAGGER_S * i))
    scheduler.modify_job("process", next_run_time=now + timedelta(seconds=30 + STAGGER_S * len(jobs)))
    log.info("running all sources soon (%s)", reason)


def seconds_asleep(prev: tuple[float, float], now: tuple[float, float]) -> float:
    """(wall, monotonic) pairs -> seconds the machine was suspended in between (monotonic stops in suspend)."""
    return (now[0] - prev[0]) - (now[1] - prev[1])


def _wait_for_network(timeout_s: int = 180) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("ici.radio-canada.ca", 443), timeout=5):
                return True
        except OSError:
            time.sleep(5)
    return False


def _resume_watchdog() -> None:
    prev = (time.time(), time.monotonic())
    while True:
        time.sleep(RESUME_CHECK_S)
        now = (time.time(), time.monotonic())
        slept, prev = seconds_asleep(prev, now), now
        if slept > RESUME_THRESHOLD_S and scheduler.running:
            log.info("woke up after ~%d min asleep; waiting for network", slept // 60)
            state["last_resume"] = datetime.now()
            online = _wait_for_network()
            run_all_soon("wake-up" + ("" if online else ", network still down"))


def next_runs() -> dict[str, datetime | None]:
    return {j.id: j.next_run_time for j in scheduler.get_jobs()} if scheduler.running else {}
