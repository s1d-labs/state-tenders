"""What this family scrapes: the tender portals of states that do not run GePNIC. One project per portal, on the pool's India servers
(geo="IN"), or GitHub runners through the pool's Mumbai proxies (proxy="IN"): the portals answer only from India. Public data only: no login, no captcha, no OTP is passed.

- Bihar eProc2 (eproc2.bihar.gov.in): every past tender of every department since July 2020 (about 102,600): the tender view, the
  contract (firm, PAN, value) and the documents. Every page of the state-wide past-tender list is queued ("plist-<start>").
- Gujarat nProcure (tender.nprocure.com): every tender id since the portal began (2023, about 367,000 ids): notice, bidders, AOC (final
  value, award date), and the documents of tenders that are still open (the site removes them at closing). Also road works in
  progress and the awarded tenders of Roads and Buildings, from the lists.
- Andhra Pradesh and Telangana (same TMS software): every procurement id since the portal began (AP May 2016, about 852,000; TS
  September 2017, about 682,000): notice page, documents page and documents. The poll workflow also queues "poll-<date>" every day for
  the current tenders. Award results sit behind a captcha and are not collected.
- Documents (env DOCS, portal.want_docs): "road" = works tenders whose name of work is about a road or bridge. The bucket has room for
  about that much (2026-11-13: 1,398 of 2,000 GB used); every record still lists all its documents, so the rest can be fetched later.
- Chhattisgarh eProc (eproc.cgstate.gov.in): open tenders of all departments from the home page's live list, the tender view and the
  documents, kept by the same daily poll. It refuses the Mumbai proxies, so it is not in the pool (DIRECT): workers on dev-vps-3 run it.
"""
import datetime
import json
from pathlib import Path

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]

# eProc2 department ids: roads and city works (from /rest/organization/loadAllDeptWithParent?orgId=538)
BIHAR_DEPTS = {945: "Road Construction Department", 2899: "Rural Works Department", 1519: "Bihar State Road Development Corporation",
               800: "Urban Development and Housing Department", 1869: "Bihar Urban Infrastructure Development Corporation",
               1517: "Patna Municipal Corporation"}

PROJECTS = [
    {
        "name": f"{FAMILY}-bihar",
        "title": "Bihar eProc2: all past tenders since 2020, contracts (firm, PAN, value) and documents",
        "task": "bihar",
        "target": "eproc2.bihar.gov.in",
        "env": {"DOCS": "road"},
        "probe": None,        # no health check: the hub is outside India and the portal answers only Indian addresses
        "unit_label": "list page or tender", "record_label": "tender",
        "items": [{"key": f"list-{d}-0", "payload": {"dept": d, "start": 0}} for d in BIHAR_DEPTS],
        "workers": 6,
        "delay_ms": 600,
    },
]

TMS = [("ap", "tender.apeprocurement.gov.in", "Andhra Pradesh e-procurement"), ("ts", "tender.telangana.gov.in", "Telangana e-procurement")]
TODAY = datetime.date.today().isoformat()
PROJECTS += [
    {
        "name": f"{FAMILY}-{slug}",
        "title": f"{title}: all tenders since the portal began, notices and documents",
        "task": "aptms",
        "target": host,
        "env": {"SITE": host, "DOCS": "road"},
        "probe": None,
        "unit_label": "poll, id range or tender", "record_label": "tender",
        "items": [{"key": f"poll-{TODAY}", "payload": {}}],
        "workers": 6,
        "delay_ms": 600,
    }
    for slug, host, title in TMS
]

# nProcure client ids whose awarded-tender lists are read (14 = Roads and Buildings; the others were added by lane S on 2026-11-13:
# municipal corporations, urban development authorities, GWSSB, Narmada water resources, police housing, district offices and more)
GUJARAT_AWARD_CLIENTS = [14, 6, 7, 18, 22, 24, 25, 30, 34, 41, 44, 50, 51, 52, 57, 68, 69, 79, 87, 92, 95, 108, 125, 128, 131, 132, 135, 138,
                         139, 141, 143, 155, 156, 157, 158, 159, 160, 162, 163, 165, 166]

PROJECTS.append({
    "name": f"{FAMILY}-gujarat",
    "title": "Gujarat nProcure: all tenders since 2023, bidders, awards (AOC), notices and documents",
    "task": "nprocure",
    "target": "tender.nprocure.com",
    "env": {},
    "probe": None,
    "unit_label": "list page, id range or tender", "record_label": "tender",
    "items": [{"key": "prog-0", "payload": {"start": 0}}] + [{"key": f"awd-{c}-0", "payload": {"client": c, "start": 0}} for c in GUJARAT_AWARD_CLIENTS],
    "workers": 6,
    "delay_ms": 600,
})

# Chhattisgarh eProc refuses the hub's Mumbai proxies (CONNECT 502 on all three IP ranges, 2026-11-12), so GitHub runners cannot
# reach it. Its project stays out of the pool (pool=False: no GitHub workers) and runs on workers on dev-vps-3 (OVH Mumbai) with that
# server's hub token. Only open tenders are public (the closed and awarded search asks for a captcha), so the poll queues it daily.
DIRECT = [{
    "name": f"{FAMILY}-cg",
    "title": "Chhattisgarh eProc: open tenders of all departments, tender view and documents",
    "task": "cg",
    "target": "eproc.cgstate.gov.in",
    "env": {},
    "probe": None,
    "unit_label": "poll or tender", "record_label": "tender",
    "items": [{"key": f"poll-{TODAY}", "payload": {}}],
    "workers": 2,
    "delay_ms": 2000,
}]

# Full histories (seed_history.py queues them once): "plist-<start>" pages for Bihar, "r-<start>" id ranges for the others.
HISTORY = {f"{FAMILY}-bihar": ("plist", 0, 102700, 100), f"{FAMILY}-gujarat": ("r", 1, 367000, 25),
           f"{FAMILY}-ap": ("r", 1, 852000, 25), f"{FAMILY}-ts": ("r", 1, 682000, 25)}

PROBES = []             # the hub checks from outside India, and these portals answer only Indian addresses
