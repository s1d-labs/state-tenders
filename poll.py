"""Queue today's poll for the portals that show only current tenders. Run by the poll workflow every day."""
from scrape_hub_client import seed_queue

from family import DIRECT, FAMILY, PROJECTS, TODAY

for p in PROJECTS + DIRECT:
    if p["task"] in ("aptms", "cg"):
        print(p["name"], seed_queue(p["name"], [{"key": f"poll-{TODAY}", "payload": {}}]))

# Bihar: the newest 300 rows of the state-wide past-tender list, so tenders that close after the full-history pages were read are kept
print(f"{FAMILY}-bihar", seed_queue(f"{FAMILY}-bihar", [{"key": f"plist-{TODAY}-{s}", "payload": {"start": s, "total": 300}} for s in (0, 100, 200)]))
