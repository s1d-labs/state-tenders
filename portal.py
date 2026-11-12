"""Shared parts of this family's crawlers: one HTTP session with the right certificates, polite pacing, and request metrics."""
import time

import requests
from scrape_hub_client import ca_bundle, count_request

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; s1d-labs public records crawl; +https://labs.s1d.me)"}


def session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = ca_bundle()      # certifi + public intermediates some portals fail to send (from scrape-hub-client). Verification stays on.
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
            count_request(self.hub, None)           # http_error (no metrics without a hub)
            raise
        self.last = time.time()
        count_request(self.hub, r.status_code, self.last - t)    # n_http, t_http_s, http_<code>, block on 403/429/503
        return r
