"""One shared HTTP client: identifies itself, keeps a minimum gap per host, and checks robots.txt for pages."""

import logging
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


class Blocked(Exception):
    """The site answered with a bot wall (403/405/429, captcha, Access Denied)."""


class Polite:
    def __init__(self) -> None:
        s = get_settings()
        self.delay = s.host_delay_s
        self.client = httpx.Client(
            headers={
                "User-Agent": s.user_agent,
                "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.7,en;q=0.5",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
        )
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def _wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            ready = self._last.get(host, 0.0) + self.delay
            self._last[host] = max(now, ready)
        if ready > now:
            time.sleep(ready - now)

    def get(self, url: str) -> httpx.Response:
        host = urlsplit(url).netloc
        self._wait(host)
        r = self.client.get(url)
        if r.status_code in (401, 403, 405, 429) or "Human Verification" in r.text[:2000]:
            raise Blocked(f"{r.status_code} {url}")
        r.raise_for_status()
        return r

    def allowed(self, url: str) -> bool:
        """robots.txt check for the site's generic rules. Unreachable robots.txt -> allowed."""
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                self._wait(parts.netloc)
                r = self.client.get(base + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[base] = rp
            except httpx.HTTPError:
                self._robots[base] = None
        rp = self._robots[base]
        return rp is None or rp.can_fetch(get_settings().user_agent, url)


_client: Polite | None = None


def client() -> Polite:
    global _client
    if _client is None:
        _client = Polite()
    return _client
