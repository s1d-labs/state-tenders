"""Chhattisgarh eProc (eproc.cgstate.gov.in, CHEPS, mjunction): the open tenders of every department (PWD, RES, PARD, CGRDC, urban
bodies ...), each with its full tender view and every attached document. The source is the home page's own "LOAD LIVE DATA" list
and the public tender view; both need no login and no captcha. The "Advanced Search" (closed and awarded tenders) asks for a captcha,
so it is not used: only open tenders are public, and the poll workflow queues "poll-<date>" every day to keep each tender while it
is open. The OWASP_CSRFTOKEN that every page carries is the site's form token for any visitor, not a login.

Queue items: "poll-<date>" (list every open tender and queue the new ones) and "t-<rfq id>[-c]" (one tender; "-c" once it has a
corrigendum, so a changed tender is read again). A record per tender, id "cg-<rfq id>". Files: raw/<rfq id>.html.gz (tender view),
docs/<rfq id>/<file>.
Local test: python cg.py --local (the live list and its first tender, files under /tmp/cg-test)."""
import gzip
import html
import json
import os
import re
import signal
import sys
import time

import requests

from portal import Pace, session

BASE = "https://eproc.cgstate.gov.in/CHEPS"
HOME = BASE + "/security/getSignInAction.do"
stop = False


def on_signal(*_):
    global stop
    stop = True


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


class Portal:
    def __init__(self, hub=None, gap=2.0):
        self.hub, self.gap = hub, gap
        self.fresh()

    def fresh(self):
        self.s = session()
        self.pace = Pace(self.hub, self.gap)
        self.token = None
        self.keep(self.get_home())

    def get_home(self):
        r = self.pace(self.s.get, HOME, timeout=(20, 180))
        r.raise_for_status()
        return r.text

    def keep(self, page):
        m = re.search(r"name=OWASP_CSRFTOKEN value=([A-Za-z0-9-]+)", page or "")
        if m:
            self.token = m.group(1)

    def post(self, url, data, referer=HOME, **k):
        r = self.pace(self.s.post, url, data={**data, "OWASP_CSRFTOKEN": self.token, "pkiEnabledOrg": "false"}, timeout=(20, 300),
                      headers={"Referer": referer}, **k)
        if r.status_code == 200 and "html" in r.headers.get("Content-Type", ""):
            self.keep(r.text)
        return r

    def live(self):
        """The home page's "LOAD LIVE DATA" list: every open tender, grouped by organisation."""
        r = self.post(HOME, {"loadAlldata": "Y"})
        r.raise_for_status()
        return r.text

    def view(self, rfq, part="1"):
        r = self.post(BASE + "/business/rfq.action", {"rfqId": rfq, "rfqPartNumber": part, "printFlag": "N", "methodName": "viewRfq",
                                                      "documentStatus": "AAS", "documentOwner": "", "openRfqFlag": "Y", "responseFlag": ""})
        r.raise_for_status()
        return r.text

    def download(self, rfq, name, org, tries=3):
        """The file, or None. Large files sometimes break off part way: try again, at most `tries` times."""
        for attempt in range(tries):
            try:
                r = self.post(BASE + "/business/doc.action", {"popUp": "Y", "methodName": "openAttachment", "openRfqFlag": "Y",
                                                              "entityId": rfq, "entityName": "rfq", "fileName": name, "entityOrgId": org},
                              referer=BASE + "/business/rfq.action")
            except requests.RequestException:
                if attempt == tries - 1:
                    return None
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code != 200 or not r.content or "html" in r.headers.get("Content-Type", ""):
                return None
            return r.content
        return None


def live_rows(page):
    """(organisation, row) for every tender in the live list. Row: rfq id, part, tender no, start, due, short and full description,
    probable amount of contract (PAC), corrigendum issued."""
    i = page.find('id="marqu"')
    seg = page[i:page.find("</marquee>", i)] if i >= 0 else ""
    out, org = [], ""
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", seg, re.S):
        ids = re.search(r"viewRfq\((\d+),\s*(\d+)\)", tr)
        if not ids:
            t = text(tr)
            if t:
                org = t
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        full = re.search(r'<span class="tooltiptext">(.*?)</span>', tr, re.S)
        c = [text(x) for x in tds]
        short = text(re.sub(r'<span class="tooltiptext">.*?</span>', " ", tds[4], flags=re.S)) if len(tds) > 4 else ""
        out.append({"rfq_id": ids.group(1), "part": ids.group(2), "org": org, "sr_no": c[0] if c else "", "tender_no": c[1] if len(c) > 1 else "",
                    "bid_start": c[2] if len(c) > 2 else "", "bid_due": c[3] if len(c) > 3 else "", "title_short": short,
                    "title": text(full.group(1)) if full else short, "pac": c[5] if len(c) > 5 else "",
                    "corrigendum": c[6] if len(c) > 6 else ""})
    return out


def fields(page):
    """Every label-value pair of the tender view (organisation, category, district, PWD circle and division, NIT type, estimate,
    fees, EMD, dates ...). A label seen again gets a number."""
    out = {}
    for a, b in re.findall(r'<td class="fieldLabel"[^>]*>(.*?)</td>\s*<td class="field"[^>]*>(.*?)</td>', page or "", re.S):
        k, v = text(re.sub(r"<!--.*?-->", " ", a, flags=re.S)).rstrip(" :"), text(b)
        if not k or len(k) > 120:
            continue
        n, key = 2, k
        while key in out:
            key, n = f"{k} ({n})", n + 1
        out[key] = v[:4000]
    return out


def attachments(page):
    """(file name, org id) for every attachment link of the tender view."""
    out, seen = [], set()
    for name, org in re.findall(r"viewOpenRfqAttachment\('/business/doc\.action','Y','openAttachment','Y','rfq',\d+,'([^']+)',(\d+)\)", page or ""):
        if name not in seen:
            seen.add(name)
            out.append((html.unescape(name), org))
    return out


def run_poll(hub, P, item, seed_queue, project):
    rows = live_rows(P.live())
    fresh = [{"key": f"t-{r['rfq_id']}" + ("-c" if r["corrigendum"].upper().startswith("Y") else ""), "payload": r} for r in rows]
    for i in range(0, len(fresh), 500):
        seed_queue(project, fresh[i:i + 500])
    hub.complete([item["key"]], "done", fetched=len(rows))


def run_tender(hub, P, item):
    f = item["payload"]
    rfq = f["rfq_id"]
    page = P.view(rfq, f.get("part") or "1")
    if "fieldLabel" not in page:
        hub.complete([item["key"]], "failed", error="no tender view")
        return
    files = []
    for name, org in attachments(page):
        body = P.download(rfq, name, org)
        if not body:
            hub.failure("no-file", f"{rfq}/{name}"[:200], "empty answer")
            continue
        path = f"docs/{rfq}/{re.sub(r'[^A-Za-z0-9._-]', '_', name)[:160]}"
        hub.upload_many([(path, body, "application/pdf" if body[:5] == b"%PDF-" else "application/zip" if body[:2] == b"PK" else "application/octet-stream")])
        files.append({"name": name, "file": path, "bytes": len(body)})
    hub.upload_many([(f"raw/{rfq}.html.gz", gzip.compress(page.encode()), "application/gzip")])
    v = fields(page)
    hub.record(f"cg-{rfq}", {**f, "view": v, "dept": v.get("Organization Name") or f.get("org"), "category": v.get("Procurement Category"),
                             "district": v.get("Division / District Name"), "estimate": v.get("Estimated Value") or f.get("pac"),
                             "detail": v.get("Detailed Description") or f.get("title"), "files": files, "raw": f"raw/{rfq}.html.gz",
                             "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=1)


def main():
    from scrape_hub_client import HubClient, seed_queue
    project = os.environ["SCRAPE_POOL_PROJECT"]
    deadline = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 300
    hub = HubClient(project, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", 0)), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", 1)))
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    P = Portal(hub, max(1.0, hub.settings.get("delay_ms", 2000) / 1000))
    try:
        while time.time() < deadline and not stop:
            if hub.settings.get("paused"):
                time.sleep(30)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break
            item = items[0]
            try:
                if item["key"].startswith("poll-"):
                    run_poll(hub, P, item, seed_queue, project)
                else:
                    run_tender(hub, P, item)
            except Exception as e:      # one bad tender must not stop the run; start a new session after an error
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
                time.sleep(10)
                P.fresh()
        hub.close("finished" if not stop else "failed", "" if not stop else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--local":
        from scrape_hub_client import LocalHub
        hub, P = LocalHub(save_dir="/tmp/cg-test"), Portal(None, 2.0)
        rows = live_rows(P.live())
        print("live", len(rows), json.dumps(rows[0], ensure_ascii=False)[:500] if rows else "")
        if rows:
            run_tender(hub, P, {"key": "t-x", "payload": rows[int(sys.argv[2]) if len(sys.argv) > 2 else 0]})
        sys.exit(0)
    sys.exit(main())
