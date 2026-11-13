"""Queue today's poll for the portals that show only current tenders. Run by the poll workflow every day."""
from scrape_hub_client import seed_queue

from family import DIRECT, PROJECTS, TODAY

for p in PROJECTS + DIRECT:
    if p["task"] in ("aptms", "cg"):
        print(p["name"], seed_queue(p["name"], [{"key": f"poll-{TODAY}", "payload": {}}]))
