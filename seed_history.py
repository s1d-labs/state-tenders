"""Queue the full histories of family.HISTORY once (existing keys are kept, so running it again adds nothing).
Run from GitHub Actions or from a server with a hub token. Options:
  --skip FILE      JSON {"<project>": [id, ...]}: ids that are already stored, left out of the "r-" items
  --only PROJECT   queue one project only
  --dry            print the counts, queue nothing"""
import argparse
import json

from family import HISTORY


def items(kind, first, last, step, skip=()):
    skip = set(skip)
    if kind == "plist":
        return [{"key": f"plist-{a}", "payload": {"start": a, "total": last}} for a in range(first, last, step)]
    out = []
    for a in range(first, last + 1, step):
        p = {"start": a, "n": step}
        s = sorted(i for i in range(a, a + step) if i in skip)
        if s:
            p["skip"] = s
        out.append({"key": f"r-{a}", "payload": p})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip")
    ap.add_argument("--only")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    skip = json.load(open(a.skip)) if a.skip else {}
    for project, (kind, first, last, step) in HISTORY.items():
        if a.only and project != a.only:
            continue
        it = items(kind, first, last, step, skip.get(project, ()))
        print(project, len(it), "items", sum(len(i["payload"].get("skip", [])) for i in it), "ids skipped")
        if not a.dry:
            from scrape_hub_client import seed_queue
            print(" ", seed_queue(project, it))
