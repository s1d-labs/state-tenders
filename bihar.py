"""Bihar eProc2 (eproc2.bihar.gov.in, mjunction): past tenders of all departments since the portal began (July 2020, about 102,600); the poll workflow also queues the newest 300 rows every day,
each with its full tender view, its contract (purchase order: firm, PAN, value, date) and its attached documents. All of it is public
with the guest token that the listing page gives to any visitor; no login, no captcha.

Queue items: "plist-<start>" (one page of the past-tender list of the whole state; every page is queued at setup, so one bad page does
not stop the others), "list-<dept>-<start>" (the older per-department pages; a full page queues the next page) and "t-<tenderid>"
(one tender). Env DOCS (portal.want_docs): which tenders get their documents downloaded; "works" = procurement category Works.
A record per tender, id "bihar-<tenderid>". Files: raw/<tenderid>.json.gz (tender view + contract), docs/<tenderid>/<file>.
Local test: python bihar.py --local 945 (one list page and its first tender, files saved under /tmp/bihar-test)."""
import gzip
import json
import os
import re
import signal
import sys
import time

from portal import Pace, session, want_docs

BASE = "https://eproc2.bihar.gov.in/EPSV2Web"
ORG = 538
ROWS = 100
WORKS = 1557                                        # procurement category "Works" (proccatid)
DOCS = os.environ.get("DOCS", "all")
FILEREF = re.compile(r"^\d+/[^|]+\|\d+\|.+$")      # stored attachment value: "<group>/<stamp>_<name>|<bytes>|<name>"
stop = False


def on_signal(*_):
    global stop
    stop = True


class Portal:
    def __init__(self, hub=None, gap=2.0):
        self.s = session()
        self.pace = Pace(hub, gap)
        self.token = None

    def login(self):
        html = self.pace(self.s.post, BASE + "/openarea/tenderListingPage.action", timeout=60).text
        self.token = re.search(r'id="Authorization" value="([^"]+)"', html).group(1)

    def post(self, path, body=None, form=None, stream=False):
        for attempt in range(2):
            if not self.token:
                self.login()
            h = {"Authorization": self.token, "Accept": "application/json, text/plain, */*", "Referer": BASE + "/openarea/tenderListingPage.action"}
            if form is None:
                h["Content-Type"] = "application/json;charset=utf-8"
            r = self.pace(self.s.post, BASE + path, headers=h, data=form if form is not None else (json.dumps(body) if body is not None else None),
                          timeout=(20, 180), stream=stream)
            if r.status_code == 401 and attempt == 0:
                self.token = None          # the guest token expired: get a new one
                continue
            return r
        return r

    def past(self, dept, start, rows=ROWS):
        """One page of past tenders; dept None = the whole state. Raises when the answer is not a list (the caller retries later)."""
        body = {"orgId": ORG} if dept is None else {"orgId": ORG, "deptId": int(dept)}
        for attempt in range(2):
            r = self.post(f"/rest/openarea/getPastTenders?startpoint={start}&maxRow={rows}", body)
            try:
                d = (r.json() if r.content.strip() else []) if r.status_code == 200 else None     # past the end: an empty answer
            except ValueError:
                d = None
            if isinstance(d, list) and (d or attempt):
                return d
            self.token = None                       # an empty answer can also mean a stale token: ask once more with a new one
        raise RuntimeError(f"past-tender list: HTTP {r.status_code}, {len(r.content)} bytes")

    def tender(self, tid):
        """The tender view. An empty or non-JSON answer (seen when the guest token ends without a 401) gets one more try with a new token."""
        for attempt in range(2):
            r = self.post(f"/rest/quotation/previewTenderByTenderId?tenderId={tid}")
            try:
                if r.status_code == 200 and r.content.strip():
                    return r.json()
            except ValueError:
                pass
            self.token = None
        return None

    def contract(self, tid):
        r = self.post(f"/rest/openarea/getPoDetailsForPastTender?tenderId={tid}")
        try:
            return r.json() if r.status_code == 200 and r.content.strip() else None
        except ValueError:
            return None

    def download(self, tid, group, ref):
        r = self.post("/rest/openarea/downloadattachment.action",
                      form={"Authorization": self.token, "tempGrpId": str(group), "tenderId": str(tid), "orgId": str(ORG), "fileName": ref})
        return r.content if r.status_code == 200 and r.content else None


def attachments(view):
    """(template group id, stored file value) for every file field in a tender view."""
    out, seen = [], set()

    def walk(x, group):
        if isinstance(x, dict):
            g = x.get("templategroupId", group)
            for v in x.values():
                walk(v, g)
        elif isinstance(x, list):
            for v in x:
                walk(v, group)
        elif isinstance(x, str) and FILEREF.match(x) and x not in seen:
            seen.add(x)
            out.append((group, x))
    walk(view, None)
    return out


def summary(row, view, po):
    """The fields the ledger uses, in plain names. Everything else stays in the raw file."""
    v = view or {}
    s = {"tender_id": row.get("currenttenderid"), "ref_no": row.get("currenttenderrefno") or v.get("tenderrefno"), "dept_id": row.get("currentdeptid"),
         "title": (row.get("currentdescription") or v.get("description") or "")[:2000], "estimate": v.get("pacamt"),
         "published": v.get("publishdate") or row.get("currentTenderPublishDate"), "bid_end": row.get("currentbidEndDate"),
         "bid_open": row.get("currentbidOpenDate"), "status": row.get("currentstatus"), "tender_call_no": v.get("tendercallno"),
         "ranking": v.get("rankingsequence"), "dept_path": v.get("queryString")}
    if po:
        p = po[0] if isinstance(po, list) and po else po
        if isinstance(p, dict):
            flat = {}         # templateMap: {section: [template with templateFieldList: [{shortName, value}]]}
            for templates in (p.get("templateMap") or {}).values():
                for t in templates or []:
                    for f in t.get("templateFieldList") or []:
                        v = f.get("value")
                        if f.get("shortName") and v not in (None, "None", "") and "attach" not in f["shortName"] and "file" not in f["shortName"]:
                            flat.setdefault(f["shortName"], v)
            s["contract"] = {"po_value": p.get("poValue"), "po_date": p.get("poCreationDate"), "vendor_id": p.get("vendorId"),
                             **{k: flat[k] for k in list(flat)[:60]}}
    return s


def run_tender(hub, P, item):
    tid = item["payload"]["id"]
    row = item["payload"].get("row") or {}
    view = P.tender(tid)
    if view is None:
        hub.complete([item["key"]], "failed", error="no tender view")
        return
    po = P.contract(tid)
    files, listed = [], []
    get = want_docs(DOCS, view.get("proccatid") == WORKS or row.get("currentproccatid") == WORKS, view.get("description"))
    for group, ref in attachments(view):
        name = ref.split("|")[-1][:150]
        listed.append({"name": name, "group": group, "ref": ref})
        if not get:
            continue
        body = P.download(tid, group, ref)
        if not body:
            hub.failure("no-file", f"{tid}/{name}", "empty answer")
            continue
        path = f"docs/{tid}/{re.sub(r'[^A-Za-z0-9._-]', '_', name)}"
        hub.upload_many([(path, body, "application/pdf" if body[:5] == b"%PDF-" else "application/octet-stream")])
        files.append({"name": name, "file": path, "bytes": len(body)})
    raw = gzip.compress(json.dumps({"row": row, "view": view, "contract": po}, ensure_ascii=False).encode())
    hub.upload_many([(f"raw/{tid}.json.gz", raw, "application/gzip")])
    hub.record(f"bihar-{tid}", {**summary(row, view, po), "files": files, "documents": listed, "raw": f"raw/{tid}.json.gz", "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    hub.complete([item["key"]], "done", fetched=1)


def run_list(hub, P, item, seed_queue, project):
    dept, start = item["payload"].get("dept"), int(item["payload"]["start"])
    # whole-state pages read 2 x ROWS rows: the list is newest first and grows while the crawl runs, so the overlap keeps a tender
    # that moved down by up to ROWS places from falling between two pages ("t-" keys that exist are not queued twice)
    rows = P.past(dept, start, ROWS if dept is not None else 2 * ROWS)
    if not rows and item["payload"].get("total", 0) > start:
        raise RuntimeError("empty page inside the list")
    fresh = [{"key": f"t-{r['currenttenderid']}", "payload": {"id": r["currenttenderid"], "row": r}} for r in rows if r.get("currenttenderid")]
    if len(rows) >= ROWS and dept is not None:
        fresh.append({"key": f"list-{dept}-{start + ROWS}", "payload": {"dept": dept, "start": start + ROWS}})
    if fresh:
        seed_queue(project, fresh)
    hub.complete([item["key"]], "done", fetched=len(rows))


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
                if item["key"].startswith(("list-", "plist-")):
                    run_list(hub, P, item, seed_queue, project)
                else:
                    run_tender(hub, P, item)
            except Exception as e:      # one bad tender must not stop the run
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
        hub.close("finished" if not stop else "failed", "" if not stop else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


class LocalHub:
    """Stands in for the hub in a local test: files go to /tmp/bihar-test, records and metrics are printed."""
    settings = {}

    def __init__(self):
        os.makedirs("/tmp/bihar-test", exist_ok=True)

    def metric(self, *a):
        pass

    def error(self):
        pass

    def block(self):
        print("blocked")

    def failure(self, *a):
        print("failure", a)

    def complete(self, keys, status, **k):
        print("complete", keys, status, k)

    def upload_many(self, files):
        for p, body, _ in files:
            t = "/tmp/bihar-test/" + p.replace("/", "__")
            open(t, "wb").write(body)
            print("file", p, len(body))

    def record(self, rid, data):
        print("record", rid, json.dumps(data, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--local":
        hub, P = LocalHub(), Portal(None, 2.0)
        seeded = []
        run_list(hub, P, {"key": "list-x", "payload": {"dept": sys.argv[2], "start": int(sys.argv[3]) if len(sys.argv) > 3 else 0}},
                 lambda project, items: seeded.extend(items), "local")
        print("seeded", len(seeded), [s["key"] for s in seeded[:3]], seeded[-1]["key"] if seeded else "")
        t = [s for s in seeded if s["key"].startswith("t-")]
        if t:
            run_tender(hub, P, t[0])
        sys.exit(0)
    sys.exit(main())
