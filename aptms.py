"""Andhra Pradesh and Telangana e-procurement (the same "TMS" software): every tender since the portal began (AP: May 2016, about
850,000 procurement ids; TS: September 2017, about 681,000), each with its tender notice page, its documents page and documents.
The public list shows only current and upcoming tenders, but the notice and documents pages of any procurement id stay public (the
indent id is not checked), so "r-<start>" items read the ids in order. Award results sit behind a captcha and are not collected.
Env DOCS (portal.want_docs) says which tenders get their documents downloaded; the documents page is read for every works tender.

Env SITE: tender.apeprocurement.gov.in or tender.telangana.gov.in. Queue items: "poll-<date>" (list every current works tender and
queue the new ones), "t-<procurement id>-<indent id>" (one tender) and "r-<start>" (procurement ids start .. start+n-1; an id
with no notice page is skipped). A record per tender, id "<state>-<procurement id>".
Files: raw/<procurement id>.html.gz (notice page), docs/<procurement id>/<file>.
Local test: python aptms.py --local tender.telangana.gov.in 1260 (one list page and its first tender, files under /tmp/aptms-test)."""
import base64
import gzip
import html
import json
import os
import re
import signal
import sys
import time

from portal import Pace, session, want_docs

SITE = os.environ.get("SITE", "tender.telangana.gov.in")
STATE = "ap" if "apeprocurement" in SITE else "ts"
PH = {"hdnEncryptNames": "hdnEncryptNames", "hdnEncryptValues": "hdnEncryptValues"}     # the page's own placeholders; the server takes them
EMPTY = ("nTenderID nDepartmentID subDeptId ddlDistrict ddlMandal biddingType mECVValue1 mECVValue2 dtBidClosingselect dtBidClosing1 "
         "dtBidClosing2 dtTenderOpening1 dtTenderOpening2 hdnSearch4 hdnSearch hdncorrigendumsDetails hdncorrigendumsDetails1 hdnnoSearch "
         "hdncorrigendumsDetails2 hdnadvsearch hdnPreviousPage hdnIndentID hdnTenderCategory hdnProcurementID hdnFromStatus "
         "typeOfWorkFromConsolidation popUPRequestParameter selectedCircleDivison selectedDepartmentID selectedProcurementType selectedTypeofWork aid").split()
PAGE = 100
DOCS = os.environ.get("DOCS", "all")
stop = False


def on_signal(*_):
    global stop
    stop = True


class Portal:
    def __init__(self, hub=None, gap=2.0):
        self.base = f"https://{SITE}"
        self.hub, self.gap = hub, gap
        self.fresh()

    def fresh(self):
        """A new session: the portal ends a session after any request it does not like (302 to SessionTimeOut)."""
        self.s = session()
        self.pace = Pace(self.hub, self.gap)
        self.csrf = None
        self.keep(self.pace(self.s.get, self.base + "/login.html", timeout=60).text)
        self.keep(self.post("/TenderDetailsHome.html", {"hdnType": "current"}).text)

    def keep(self, text):
        m = re.search(r'name="CSRFToken" value="([^"]+)"', text or "")
        if m:
            self.csrf = m.group(1)

    def post(self, path, data, **k):
        r = self.pace(self.s.post, self.base + path, data={"CSRFToken": self.csrf, **PH, **data}, timeout=(20, 180), allow_redirects=False, **k)
        if r.status_code in (301, 302):
            raise RuntimeError(f"redirect to {r.headers.get('Location', '')[:80]}")
        if "html" in r.headers.get("Content-Type", ""):
            self.keep(r.text)
        return r

    def page(self, start, dept=""):
        f = {k: "" for k in EMPTY}
        f.update(nDepartmentID=dept, sProcurementType="101", hdnType="current", hdnPreviousPge="TenderDetailsHome.html", **PH, sEcho=1, iColumns=9,
                 sColumns="", iDisplayStart=start, iDisplayLength=PAGE, iSortCol_0=5, sSortDir_0="desc", iSortingCols=1)
        r = self.pace(self.s.get, self.base + "/TenderDetailsHomeJson.html", params=f, timeout=(20, 180),
                      headers={"X-Requested-With": "XMLHttpRequest", "Referer": self.base + "/TenderDetailsHome.html"})
        r.raise_for_status()
        b = r.text.strip()
        d = json.loads(b) if b.startswith("{") else json.loads(base64.b64decode(b))      # Andhra Pradesh sends base64
        return int(d["iTotalDisplayRecords"]), d["aaData"]

    def tender_page(self, proc, ind, cat="101"):
        return self.post("/ViewTender.html", {"hdnProcurementID": proc, "hdnIndentID": ind, "hdnTenderCategory": cat}).text

    def docs_page(self, proc, ind):
        return self.post("/ViewTenderDocuments.html", {"hdnProcurementID": proc, "hdnIndentID": ind, "hdnFromStatus": "moretenders",
                                                       "popUPRequestParameter": "popUPRequestParameter", "hdnPreviousPage": "TenderDetailsHome.html"}).text

    def download(self, doc_id, name, spath, form=None):
        """The documents page's own form, with this file's fields set, as the page's downloadFun does."""
        data = dict(form or {})
        data.pop("CSRFToken", None)
        if STATE == "ap":
            data.update(hdndocIds=doc_id)
            r = self.post("/DownLoadFile1.html", data)
        else:
            data.update(hdndocIds=doc_id, hdndocName=name, hdnsPath=spath)
            r = self.post("/DownLoadFile.html", data)
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)', cd)
        return (r.content, html.unescape(m.group(1)).replace("+", " ") if m else name) if r.status_code == 200 and r.content else (None, name)


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def row_fields(row):
    """List row: department, tender id, notice no, category, name of work, value, [published], start, close, actions."""
    ids = re.search(r"viewBtn\((\d+),\s*(\d+),\s*(\d+)\)", row[-1] or "")
    cells = [text(c) for c in row[:-1]]
    return {"dept": cells[0], "tender_id": cells[1], "notice_no": cells[2], "category": cells[3], "title": cells[4], "value": cells[5],
            "dates": cells[6:], "indent_id": ids.group(1) if ids else "", "category_id": ids.group(2) if ids else "",
            "procurement_id": ids.group(3) if ids else ""}


def form_fields(page, name):
    """Hidden and text inputs of the named form on a page."""
    m = re.search(r'<form[^>]*name="' + re.escape(name) + r'"[^>]*>(.*?)</form>', page or "", re.S | re.I)
    out = {}
    for tag in re.findall(r"<input[^>]*>", m.group(1) if m else ""):
        n = re.search(r'name="([^"]+)"', tag)
        if n and not re.search(r'type="(button|submit|checkbox|radio)"', tag, re.I):
            v = re.search(r'value="([^"]*)"', tag)
            out[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return out


def notice(page):
    """Label-value pairs from the notice page's tables (type of work, period, bid security, officer, district ...)."""
    out = {}
    for a, b in re.findall(r"<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>", page or "", re.S):
        k, v = text(a).rstrip(" :"), text(b)
        if 2 < len(k) < 80 and v and k not in out:
            out[k] = v[:500]
    return out


def run_poll(hub, P, item, seed_queue, project):
    start, fresh, n = 0, [], 0
    while True:
        total, rows = P.page(start)
        for r in rows:
            f = row_fields(r)
            if f["procurement_id"]:
                fresh.append({"key": f"t-{f['procurement_id']}-{f['indent_id']}", "payload": f})
        n += len(rows)
        start += PAGE
        if not rows or start >= total or stop:
            break
    for i in range(0, len(fresh), 500):
        seed_queue(project, fresh[i:i + 500])
    hub.complete([item["key"]], "done", fetched=n)


def fields(n):
    """The list-row fields, from a notice page (for tenders read by id, not from the list)."""
    g = lambda *ks: next((n[k] for k in ks if n.get(k)), "")
    return {"dept": g("Department Name"), "tender_id": g("Tender ID"), "notice_no": g("Enquiry/IFB/Tender Notice Number", "Tender Notice Number",
            "IFB No / Tender Notice Number"), "category": g("Tender Category"), "title": g("Name of Work", "Name of Project"),
            "value": g("Estimated Contract Value"), "closing": g("Bid Submission Closing Date", "Submission Closing Date", "Closing Date & Time")}


def fetch(hub, P, proc, ind, f, cat="101"):
    """Read one tender and store it. Returns False when the id has no notice page (no such tender)."""
    page = P.tender_page(proc, ind, cat)
    n = notice(page)
    if len(n) < 10:
        return False
    f = {**fields(n), **{k: v for k, v in f.items() if v}, "procurement_id": str(proc)}
    works = "work" in (f.get("category") or "").lower()
    docs = P.docs_page(proc, ind) if works or f.get("indent_id") else ""
    form = form_fields(docs, "viewTenderDocBean")
    files, listed = [], []
    get = want_docs(DOCS, works, f.get("title"))
    for args in re.findall(r"downloadFun\(([^)]*)\)", docs):
        parts = re.findall(r"'([^']*)'", args) or [x.strip().strip("'\"") for x in args.split(",")]   # names may hold commas
        if not parts or not parts[0].isdigit():
            continue
        listed.append({"doc_id": parts[0], "name": parts[1] if len(parts) > 1 else ""})
        if not get:
            continue
        body, name = P.download(parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "TenderDocuments", form)
        if not body or body.lstrip()[:200].lower().startswith((b"<html", b"<!doctype")):
            hub.failure("no-file", f"{proc}/{parts[0]}", "empty answer" if not body else "the portal answered with a web page")
            continue
        path = f"docs/{proc}/{parts[0]}-{re.sub(r'[^A-Za-z0-9._-]', '_', name)[:140]}"
        hub.upload_many([(path, body, "application/zip" if body[:2] == b"PK" else "application/pdf" if body[:5] == b"%PDF-" else "application/octet-stream")])
        files.append({"doc_id": parts[0], "name": name, "file": path, "bytes": len(body)})
    hub.upload_many([(f"raw/{proc}.html.gz", gzip.compress((page + "\n<!-- documents -->\n" + docs).encode()), "application/gzip")])
    hub.record(f"{STATE}-{proc}", {**f, "notice": n, "files": files, "documents": listed, "raw": f"raw/{proc}.html.gz",
                                   "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return True


def again(P, fn, *a):
    """The portal sometimes ends a session (302 to SessionTimeOut): start a new one and try once more."""
    try:
        return fn(*a)
    except RuntimeError as e:
        if "redirect" not in str(e):
            raise
        P.fresh()
        return fn(*a)


def run_tender(hub, P, item):
    f = item["payload"]
    again(P, fetch, hub, P, f["procurement_id"], f["indent_id"], f, f.get("category_id") or "101")
    hub.complete([item["key"]], "done", fetched=1)


def run_range(hub, P, item):
    p = item["payload"]
    skip, n = set(p.get("skip") or []), 0
    for proc in range(int(p["start"]), int(p["start"]) + int(p["n"])):
        if stop:
            raise RuntimeError("stopped")
        if proc not in skip:
            n += again(P, fetch, hub, P, str(proc), "", {})
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
                if item["key"].startswith("poll-"):
                    run_poll(hub, P, item, seed_queue, project)
                elif item["key"].startswith("r-"):
                    run_range(hub, P, item)
                else:
                    run_tender(hub, P, item)
            except Exception as e:      # one bad tender must not stop the run; the portal may have ended the session, so start a new one
                hub.failure("bad-item", item["key"], f"{type(e).__name__}: {e}"[:200])
                hub.complete([item["key"]], "failed", error=type(e).__name__)
                P.fresh()
        hub.close("finished" if not stop else "failed", "" if not stop else "stopped by signal")
    except Exception as e:
        hub.close("failed", str(e)[:200])
        raise


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--local":
        SITE = sys.argv[2]
        STATE = "ap" if "apeprocurement" in SITE else "ts"
        from bihar import LocalHub
        hub = LocalHub()
        P = Portal(None, 2.0)
        total, rows = P.page(0, sys.argv[3] if len(sys.argv) > 3 else "")
        f = row_fields(rows[0])
        print("total", total, json.dumps(f, ensure_ascii=False)[:400])
        run_tender(hub, P, {"key": "t-x", "payload": f})
        run_range(hub, P, {"key": "r-x", "payload": {"start": 600000, "n": 3}})
        sys.exit(0)
    sys.exit(main())
