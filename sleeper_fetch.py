#!/usr/bin/env python3
# Locked to Luke's Sleeper league
# League: "The *ick Is In!" (we'll save using a safe folder name without special chars)
# League ID (Identifier): 1257451535101612032

import json
import pathlib
import re
import time
from datetime import datetime, timezone

import requests  # installed by requirements.txt

# --- Settings you can change later if needed ---
LEAGUE_ID = "1257451535101612032"
LEAGUE_NAME = "The *ick Is In!"

# Make a "slug" (safe folder/file name) from the league name: "The-ick-Is-In"
LEAGUE_SLUG = re.sub(r"[^A-Za-z0-9]+", "-", LEAGUE_NAME).strip("-")

# Sleeper base URL (Uniform Resource Locator)
BASE = "https://api.sleeper.app/v1"

# Output folder inside your repo
OUTDIR = pathlib.Path("data/sleeper") / LEAGUE_SLUG
OUTDIR.mkdir(parents=True, exist_ok=True)


def get(url: str):
    """GET a URL (Uniform Resource Locator) and return JSON (JavaScript Object Notation)."""
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    # 1) Current NFL "state" (season & week)
    #    Documented by Sleeper as /v1/state/nfl
    state = get(f"{BASE}/state/nfl")
    season = str(state.get("season"))
    week = int(state.get("week") or 1)

    # 2) Pull league info (handy metadata)
    league = get(f"{BASE}/league/{LEAGUE_ID}")

    # 3) Pull pieces we actually care about: users, rosters, and this week's matchups
    users = get(f"{BASE}/league/{LEAGUE_ID}/users")
    time.sleep(0.1)  # small pause to be polite
    rosters = get(f"{BASE}/league/{LEAGUE_ID}/rosters")
    time.sleep(0.1)
    matchups = get(f"{BASE}/league/{LEAGUE_ID}/matchups/{week}")

    # 4) Build the snapshot
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "week": week,
        "league": {
            "league_id": LEAGUE_ID,
            "name": LEAGUE_NAME,
            "sleeper_league_obj": league,
        },
        "users": users,
        "rosters": rosters,
        "matchups": matchups,
    }

    # 5) Save files: latest.json and a timestamped backup
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path_ts = OUTDIR / f"{season}-wk{week}-{ts}.json"
    path_latest = OUTDIR / "latest.json"

    with open(path_ts, "w") as f:
        json.dump(snapshot, f, indent=2)

    with open(path_latest, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Wrote {path_latest} and {path_ts}")


if __name__ == "__main__":
    main()
