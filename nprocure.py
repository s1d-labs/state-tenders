"""Gujarat nProcure (tender.nprocure.com): road works tenders, each with its notice (estimated value, EMD, dates), its contract page and
every document. Lists: "Tenders In Progress" (all departments, road works kept by title) and the awarded tenders of the Roads and
Buildings department (client 14). No login, no captcha. The list call wraps its body the way the site's own page does (AES with the
key in the same request): this hides the body in transit, it does not restrict who may ask.

Queue items: "prog-<start>" and "awd-<client>-<start>" (list pages; a full page queues the next), "t-<tender id>" (one tender) and
"r-<start>" (the full history: tender ids start .. start+n-1, all departments, all years; the notice page of any tender id is public).
Ids with no notice do not exist and are skipped. A tender's documents stay on the site only while it is open, so the documents page
is read for tenders that closed less than DOCS_DAYS days ago. The contract page lists the bidders; each "View AOC" link gives the
final contract value and award date.
A record per tender, id "gj-<tender id>". Files: raw/<id>.html.gz (notice, documents list, contract page, AOC pages), docs/<id>/<file>.
Local test: python nprocure.py --local (one awarded page and its first tender, files under /tmp/bihar-test)."""
import base64
import datetime
import gzip
import html
import json
import os
import re
import secrets
import signal
import string
import sys
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from portal import Pace, session

BASE = "https://tender.nprocure.com"
PAGE = 100
DOCS_DAYS = 60
ROAD = re.compile(r"\b(road|roads|marg|highway|bridge|culvert|causeway|flyover|resurfac\w*|re-?carpet\w*|bituminous|pmgsy|mmgsy|footpath|pavement|cc road)\b", re.I)
stop = False


def on_signal(*_):
    global stop
    stop = True


def envelope(obj):
    """The site's own request wrapping (app.js): AES-128-CBC, key from PBKDF2-SHA1 x1000; the passphrase travels with the request."""
    phrase = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(5))
    salt, iv = os.urandom(16), os.urandom(16)
    key = PBKDF2HMAC(hashes.SHA1(), 16, salt, 1000).derive(phrase.encode())
    p = padding.PKCS7(128).padder()
    data = p.update(json.dumps(obj).encode()) + p.finalize()
    e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return {"jsonData": base64.b64encode(e.update(data) + e.finalize()).decode(), "iv": iv.hex(), "salt": salt.hex(),
            "key": base64.b64encode(phrase.encode()).decode()}


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


class Portal:
    def __init__(self, hub=None, gap=2.0):
        self.s = session()
        self.pace = Pace(hub, gap)
        self.pace(self.s.get, BASE + "/", timeout=60)
        self.h = {"X-Requested-With": "XMLHttpRequest", "Referer": BASE + "/"}

    def progress(self, start):
        ao = [{"name": "sEcho", "value": 1}, {"name": "iColumns", "value": 3}, {"name": "sColumns", "value": ",,"},
              {"name": "iDisplayStart", "value": start}, {"name": "iDisplayLength", "value": PAGE}]
        ao += [{"name": f"mDataProp_{i}", "value": str(i + 1)} for i in range(3)]
        r = self.pace(self.s.post, BASE + "/beforeLoginTenderTableList", json=envelope({"reqData": ao, "_csrf": "", "idList": "0", "id": "Tenders In Progress"}),
                      headers=self.h, timeout=(20, 120))
        d = r.json()
        return int(d.get("recordsTotal") or d.get("iTotalRecords") or 0), d.get("data") or []

    def awarded(self, client, start):
        # the exact form the site's own page sends; commas stay unencoded, as the page sends them
        body = (f"sEcho=2&iColumns=7&sColumns=,,,,,,&iDisplayStart={start}&iDisplayLength={PAGE}&mDataProp_0=2&mDataProp_1=1&mDataProp_2=3"
                f"&mDataProp_3=4&mDataProp_4=5&mDataProp_5=6&mDataProp_6=7&iSortCol_0=1&sSortDir_0=desc&iSortingCols=1&SEARCH=ADV&clientid={int(client)}")
        r = self.pace(self.s.post, BASE + "/getAwardedTenderData", data=body, timeout=(20, 120),
                      headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/x-www-form-urlencoded"})
        d = r.json()
        return int(d.get("recordsFiltered") or d.get("iTotalRecords") or 0), d.get("data") or []

    def page(self, path, tid, extra=None):
        r = self.pace(self.s.post, BASE + path, data={"tenderid": tid, **(extra or {})}, timeout=(20, 120))
        return r.text if r.status_code == 200 else ""

    def download(self, href):
        r = self.pace(self.s.get, BASE + href, timeout=(20, 300))
        return r.content if r.status_code == 200 and r.content else None


def progress_rows(rows):
    out = []
    for r in rows:
        cell = r.get("2") or ""
        tid = re.search(r"Tender Id\s*:?\s*</?[^>]*>?\s*(\d+)", cell) or re.search(r"tenderid[^0-9]{0,30}(\d{4,})", cell, re.I)
        work = re.search(r"Name Of Work\s*:?\s*(.*?)(?:Estimated Contract Value|$)", text(cell), re.I)
        t = text(cell)
        if tid and ROAD.search(t):
            out.append({"tender_id": tid.group(1), "notice_no": text(r.get("1")), "list_text": t[:1500], "title": (work.group(1) if work else t)[:600]})
    return out


def awarded_rows(rows):
    return [{"tender_id": text(r.get("1")), "notice_no": text(r.get("2")), "title": text(r.get("3"))[:600], "location": text(r.get("4")),
             "dept": text(r.get("5")), "sub_dept": text(r.get("6")), "awarded_list": True} for r in rows if text(r.get("1")).isdigit()]


def notice(page):
    out = {}
    for a, b in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>\s*<td[^>]*>(.*?)</td>", page or "", re.S):
        k, v = text(a).rstrip(" :"), text(b)
        if 2 < len(k) < 80 and v and k not in out:
            out[k] = v[:500]
    return out


def run_list(hub, P, item, seed_queue, project):
    k = item["key"]
    if k.startswith("prog-"):
        start = int(item["payload"]["start"])
        total, rows = P.progress(start)
        found = progress_rows(rows)
        nxt = f"prog-{start + PAGE}"
    else:
        client, start = item["payload"]["client"], int(item["payload"]["start"])
        total, rows = P.awarded(client, start)
        found = awarded_rows(rows)
        nxt = f"awd-{client}-{start + PAGE}"
    fresh = [{"key": f"t-{f['tender_id']}", "payload": f} for f in found]
    if rows and start + PAGE < total:
        fresh.append({"key": nxt, "payload": {**item["payload"], "start": start + PAGE}})
    if fresh:
        seed_queue(project, fresh)
    hub.complete([k], "done", fetched=len(rows))


def closing(n):
    """The bid submission closing date of a notice, or None."""
    for k, v in n.items():
        if "closing" in k.lower():
            m = re.search(r"(\d{2})-(\d{2})-(\d{4})", v)
            if m:
                return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def bidders(aoc):
    """Rows of the contract page's "Details of Bid Submitted" table: supplier and, where the department gave it, the AOC form."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", aoc or "", re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 2 or not text(cells[0]).isdigit():
            continue
        form = {n: html.unescape(v) for n, v in re.findall(r'name="([^"]+)"\s+value="([^"]*)"', row)}
        out.append({"sr": text(cells[0]), "supplier": text(cells[1]), "aoc_form": form if "before-aoc-details" in row else None})
    return out


def aoc_details(page):
    """Final contract value and award date from an AOC page (the last table: value, date, uploaded AOC)."""
    t = text(re.sub(r"(?is)<(script|style).*?</\1>", " ", page or ""))
    m = re.search(r"Final Contract Value\(INR\)\s+Contract Award Date\s+Upload AOC\s+([\d.,]+)\s+(\d{2}-\d{2}-\d{4}(?: \d{2}:\d{2})?)", t)
    return {"final_value": m.group(1) if m else None, "award_date": m.group(2) if m else None, "text": t[-1200:]}


def fetch(hub, P, tid, f, nit=None):
    """Read one tender and store it. Returns False when the id has no notice (no such tender)."""
    nit = nit if nit is not None else P.page("/view-nit-home", tid)
    n = notice(nit)
    if len(n) < 10:
        return False
    close = closing(n)
    docs = P.page("/view-nit-document", tid) if close is None or close >= datetime.date.today() - datetime.timedelta(days=DOCS_DAYS) else ""
    aoc = P.page("/viewBidSubmittedAOCDetails", tid, {"pageType": "4", "backPageType": "11"})
    bids, aocs = bidders(aoc), []
    for b in bids:
        if b["aoc_form"]:
            page = P.pace(P.s.post, BASE + "/before-aoc-details", data=b["aoc_form"], timeout=(20, 120)).text
            aocs.append(page)
            b["aoc"] = aoc_details(page)
        b.pop("aoc_form", None)
    files, seen = [], set()
    for href in re.findall(r"href='(/common/download\?uid=[^']+)'", docs):
        href = html.unescape(href)
        if href in seen:
            continue
        seen.add(href)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        name = (q.get("name") or ["file"])[0]
        body = P.download(urllib.parse.quote(href, safe="/?=&-"))
        if not body:
            hub.failure("no-file", f"{tid}/{name}", "empty answer")
            continue
        path = f"docs/{tid}/{(q.get('uid') or ['x'])[0][:8]}-{re.sub(r'[^A-Za-z0-9._-]', '_', name)[:140]}"
        hub.upload_many([(path, body, "application/pdf" if body[:5] == b"%PDF-" else "application/octet-stream")])
        files.append({"name": name, "file": path, "bytes": len(body)})
    hub.upload_many([(f"raw/{tid}.html.gz", gzip.compress("\n<!-- documents -->\n".join([nit, docs, aoc] + aocs).encode()), "application/gzip")])
    aoc_text = text(re.sub(r"(?is)<(script|style).*?</\1>", " ", aoc))
    hub.record(f"gj-{tid}", {"tender_id": str(tid), "title": n.get("Description of Material/Name of Work") or n.get("Tender title/Name Of Project") or f.get("title"), **f, "notice": n,
                             "bidders": bids, "contract_page": aoc_text[-1500:] if aoc else "", "files": files, "docs_read": bool(docs),
                             "raw": f"raw/{tid}.html.gz", "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return True


def run_tender(hub, P, item):
    f = item["payload"]
    fetch(hub, P, f["tender_id"], f)
    hub.complete([item["key"]], "done", fetched=1)


def run_range(hub, P, item):
    p = item["payload"]
    skip, n = set(p.get("skip") or []), 0
    for tid in range(int(p["start"]), int(p["start"]) + int(p["n"])):
        if stop:
            raise RuntimeError("stopped")
        if tid not in skip:
            n += fetch(hub, P, tid, {})
    hub.complete([item["key"]], "done", fetched=n)


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
                if item["key"].startswith(("prog-", "awd-")):
                    run_list(hub, P, item, seed_queue, project)
                elif item["key"].startswith("r-"):
                    run_range(hub, P, item)
                else:
                    run_tender(hub, P, item)
            except Exception as e:
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
        hub.close("finished" if not stop else "failed", "" if not stop else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--local":
        from bihar import LocalHub
        hub, P = LocalHub(), Portal(None, 2.0)
        seeded = []
        run_list(hub, P, {"key": "awd-14-0", "payload": {"client": 14, "start": 0}}, lambda p, items: seeded.extend(items), "local")
        print("awarded seeded", len(seeded), seeded[-1]["key"])
        run_tender(hub, P, seeded[0])
        s2 = []
        run_list(hub, P, {"key": "prog-0", "payload": {"start": 0}}, lambda p, items: s2.extend(items), "local")
        print("progress seeded", len(s2), [x["payload"].get("title", "")[:60] for x in s2[:3]], s2[-1]["key"] if s2 else "")
        sys.exit(0)
    sys.exit(main())
