"""Shared parts of this family's crawlers: one HTTP session with the right certificates, polite pacing, and request metrics."""
import re
import tempfile
import time
from pathlib import Path

import certifi
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}


def trust():
    """certifi plus the public intermediates in certs/ that some portals fail to send. Verification stays on."""
    extra = sorted(Path(__file__).parent.glob("certs/*.pem"))
    if not extra:
        return True
    with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as f:
        for p in [Path(certifi.where())] + extra:
            f.write(p.read_bytes() + b"\n")
    return f.name


def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = trust()
    return s


class Pace:
    """At most one request per `gap` seconds from this process, and request metrics for the hub's speed control."""

    def __init__(self, hub, gap):
        self.hub, self.gap, self.last = hub, gap, 0.0

    def __call__(self, fn, *a, **k):
        wait = self.last + self.gap - time.time()
        if wait > 0:
            time.sleep(wait)
        t = time.time()
        try:
            r = fn(*a, **k)
        except requests.RequestException:
            self.last = time.time()
            if self.hub:
                self.hub.metric("http_error")
                self.hub.error()
            raise
        self.last = time.time()
        if self.hub:
            self.hub.metric("n_http")
            self.hub.metric("t_http_s", self.last - t)
            if r.status_code != 200:
                self.hub.metric(f"http_{r.status_code}")
                if r.status_code in (403, 429, 503):
                    self.hub.block()
        return r


# Road works, by the name of the work (English and the common Hindi/Telugu transliterations used in titles)
ROAD = re.compile(r"\b(road|roads|rd|marg|highway|bridge|culvert|causeway|flyover|rob|rub|resurfac\w*|re-?carpet\w*|bituminous|bt|wbm|"
                  r"pmgsy|mmgsy|footpath|pavement|cc road|sadak|path|pul|setu)\b", re.I)


def want_docs(policy, works, title):
    """Which tenders get their documents downloaded. DOCS env of the project: all, works (works tenders only), road (works tenders
    whose name of work is about a road or bridge), none. The list of documents is always kept in the record and the raw page."""
    policy = (policy or "all").lower()
    if policy == "all":
        return True
    if policy == "none":
        return False
    if policy == "works":
        return bool(works)
    return bool(works) and bool(ROAD.search(title or ""))
