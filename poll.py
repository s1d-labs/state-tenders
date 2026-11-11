"""Queue today's poll for the portals that show only current tenders. Run by the poll workflow every day."""
from scrape_hub_client import seed_queue

from family import PROJECTS, TODAY

for p in PROJECTS:
    if p["task"] == "aptms":
        print(p["name"], seed_queue(p["name"], [{"key": f"poll-{TODAY}", "payload": {}}]))
