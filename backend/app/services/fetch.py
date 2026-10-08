"""Polite HTTP fetching.

- Identifies itself with a clear User-Agent.
- Respects robots.txt for web pages and Workday/Amazon career endpoints.
- Uses only public, documented job-board APIs without robots checks (Greenhouse, Lever, Ashby,
  SmartRecruiters), and still rate-limits them.
- Never fetches sites whose terms prohibit automated access or that sit behind login walls
  (LinkedIn, Glassdoor, Indeed, Blind). Those are reached through search results only.
- Never retries around blocks: a 403/429 is logged and the step is skipped.
"""
from __future__ import annotations

import threading
import time
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from ..config import settings

DENY_HOSTS = ("linkedin.com", "glassdoor.com", "indeed.com", "teamblind.com", "fishbowlapp.com")
PUBLIC_API_HOSTS = ("boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com", "api.smartrecruiters.com")


class FetchBlocked(Exception):
    pass


class PoliteFetcher:
    def __init__(self, min_interval: float | None = None):
        self.client = httpx.Client(headers={"User-Agent": settings.http_user_agent, "Accept": "*/*"},
                                   timeout=settings.fetch_timeout_s, follow_redirects=True)
        self.min_interval = settings.fetch_min_interval_s if min_interval is None else min_interval
        self._last: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    def check(self, url: str) -> tuple[bool, str]:
        host = urlparse(url).netloc.lower()
        if any(host == h or host.endswith("." + h) for h in DENY_HOSTS):
            return False, f"{host} is not fetched automatically (terms of service or login wall)"
        if any(host == h for h in PUBLIC_API_HOSTS):
            return True, "public job-board API"
        rp = self._robots_for(url)
        if rp is not None and not rp.can_fetch(settings.http_user_agent, url):
            return False, f"robots.txt on {host} disallows this path"
        return True, "allowed"

    def _robots_for(self, url: str) -> robotparser.RobotFileParser | None:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base in self._robots:
            return self._robots[base]
        rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        try:
            r = self.client.get(base + "/robots.txt")
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            elif r.status_code in (401, 403):
                rp.disallow_all = True
            else:
                rp = None  # no robots file: allowed
        except httpx.HTTPError:
            rp = None
        self._robots[base] = rp
        return rp

    def _wait(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host, 0.0)
            delay = self.min_interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        ok, why = self.check(url)
        if not ok:
            raise FetchBlocked(why)
        self._wait(urlparse(url).netloc)
        r = self.client.request(method, url, **kw)
        if r.status_code in (403, 429, 503):
            raise FetchBlocked(f"{urlparse(url).netloc} returned {r.status_code}; skipping instead of retrying")
        return r

    def get_json(self, url: str, **kw):
        r = self.request("GET", url, **kw)
        r.raise_for_status()
        return r.json()

    def post_json(self, url: str, body: dict, **kw):
        r = self.request("POST", url, json=body, **kw)
        r.raise_for_status()
        return r.json()

    def get_text(self, url: str, max_bytes: int = 2_000_000) -> str:
        r = self.request("GET", url)
        r.raise_for_status()
        return r.text[:max_bytes]
