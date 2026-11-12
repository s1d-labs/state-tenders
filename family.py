"""What this family scrapes: the tender portals of states that do not run GePNIC. One project per portal, on
GitHub runners through the pool's Mumbai proxies (proxy="IN"): the portals answer only from India. Public data only: no login, no captcha, no OTP is passed.

- Bihar eProc2 (eproc2.bihar.gov.in): past tenders of the road and city departments, the tender view, the contract (firm, PAN, value)
  and the documents. The queue starts with page 0 of each department's past-tender list and grows by itself.
- Gujarat nProcure (tender.nprocure.com): road works in progress (all departments, kept by title) and the awarded tenders of Roads and
  Buildings; notice, contract page, documents.
- Andhra Pradesh and Telangana (same TMS software): current works tenders, each notice page and its documents. Only current tenders are
  public, so the poll workflow queues "poll-<date>" every day, and each poll queues the tenders not seen before.
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
        "title": "Bihar eProc2: road and city tenders, contracts and documents",
        "task": "bihar",
        "target": "eproc2.bihar.gov.in",
        "env": {},
        "probe": None,        # no health check: the hub is outside India and the portal answers only Indian addresses
        "unit_label": "list page or tender", "record_label": "tender",
        "items": [{"key": f"list-{d}-0", "payload": {"dept": d, "start": 0}} for d in BIHAR_DEPTS],
        "workers": 2,
        "delay_ms": 2000,
    },
]

TMS = [("ap", "tender.apeprocurement.gov.in", "Andhra Pradesh e-procurement"), ("ts", "tender.telangana.gov.in", "Telangana e-procurement")]
TODAY = datetime.date.today().isoformat()
PROJECTS += [
    {
        "name": f"{FAMILY}-{slug}",
        "title": f"{title}: current works tenders, notices and documents",
        "task": "aptms",
        "target": host,
        "env": {"SITE": host},
        "probe": None,
        "unit_label": "poll or tender", "record_label": "tender",
        "items": [{"key": f"poll-{TODAY}", "payload": {}}],
        "workers": 2,
        "delay_ms": 2000,
    }
    for slug, host, title in TMS
]

PROJECTS.append({
    "name": f"{FAMILY}-gujarat",
    "title": "Gujarat nProcure: road works tenders in progress and awarded (Roads and Buildings), notices and documents",
    "task": "nprocure",
    "target": "tender.nprocure.com",
    "env": {},
    "probe": None,
    "unit_label": "list page or tender", "record_label": "tender",
    "items": [{"key": "prog-0", "payload": {"start": 0}}, {"key": "awd-14-0", "payload": {"client": 14, "start": 0}}],
    "workers": 2,
    "delay_ms": 2000,
})

PROBES = []             # the hub checks from outside India, and these portals answer only Indian addresses
