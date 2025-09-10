#!/usr/bin/env python3
# Locked to Luke's Sleeper league
# League: "The *ick Is In!"
# League ID: 1257451535101612032

import json
import pathlib
import re
import time
from datetime import datetime, timezone

import requests

LEAGUE_ID = "1257451535101612032"
LEAGUE_NAME = "The *ick Is In!"
LEAGUE_SLUG = re.sub(r"[^A-Za-z0-9]+", "-", LEAGUE_NAME).strip("-")

BASE = "https://api.sleeper.app/v1"
OUTDIR = pathlib.Path("data/sleeper") / LEAGUE_SLUG
OUTDIR.mkdir(parents=True, exist_ok=True)

# cache for players so we don't download huge file every run
PLAYERS_DIR = pathlib.Path("data/sleeper/players")
PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
PLAYERS_CACHE = PLAYERS_DIR / "players-lite.json"


def get(url: str):
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def get_players_index(force_refresh: bool = False) -> dict:
    """Slim down Sleeper's full catalog to just id → {name,pos,team}."""
    if PLAYERS_CACHE.exists() and not force_refresh:
        with open(PLAYERS_CACHE, "r") as f:
            return json.load(f)

    print("[INFO] Downloading player catalog from Sleeper...")
    players_all = get(f"{BASE}/players/nfl")

    lite = {}
    for pid, pdata in players_all.items():
        lite[pid] = {
            "name": pdata.get("full_name") or pdata.get("first_name"),
            "pos": pdata.get("position"),
            "team": pdata.get("team"),
            "status": pdata.get("status"),
        }

    with open(PLAYERS_CACHE, "w") as f:
        json.dump(lite, f)

    return lite


def main():
    # 1) NFL state (season/week)
    state = get(f"{BASE}/state/nfl")
    season = str(state.get("season"))
    week = int(state.get("week") or 1)

    # 2) League meta
    league = get(f"{BASE}/league/{LEAGUE_ID}")

    # 3) Users, rosters, matchups
    users = get(f"{BASE}/league/{LEAGUE_ID}/users")
    time.sleep(0.2)
    rosters = get(f"{BASE}/league/{LEAGUE_ID}/rosters")
    time.sleep(0.2)
    matchups = get(f"{BASE}/league/{LEAGUE_ID}/matchups/{week}")

    # 4) Players index (adds readable names)
    players_index = get_players_index(force_refresh=False)

    # 5) Build snapshot
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
        "players_index": players_index,
    }

    # 6) Save
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path_ts = OUTDIR / f"{season}-wk{week}-{ts}.json"
    path_latest = OUTDIR / "latest.json"

    with open(path_ts, "w") as f:
        json.dump(snapshot, f, indent=2)
    with open(path_latest, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"[WRITE] {path_latest} and {path_ts}")


if __name__ == "__main__":
    main()
