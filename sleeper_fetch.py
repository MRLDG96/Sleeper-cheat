#!/usr/bin/env python3
# League locked: "The *ick Is In!"  |  League ID: 1257451535101612032

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

# Cache for the big players catalog -> slim index
PLAYERS_DIR = pathlib.Path("data/sleeper/players")
PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
PLAYERS_CACHE = PLAYERS_DIR / "players-lite.json"


def get(url: str, pause: float = 0.15):
    r = requests.get(url, timeout=60, headers={"User-Agent": "mrldg96-sleeper-fetch/1.0"})
    r.raise_for_status()
    if pause:
        time.sleep(pause)
    return r.json()


def get_players_index(force_refresh: bool = False) -> dict:
    """
    Build a slim {player_id: {name,pos,team,status}} index from Sleeper's /players/nfl.
    Cached to data/sleeper/players/players-lite.json so we don't redownload every run.
    """
    if PLAYERS_CACHE.exists() and not force_refresh:
        with open(PLAYERS_CACHE, "r") as f:
            return json.load(f)

    print("[INFO] Downloading players catalog…")
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


def resolve_ids(ids, idx):
    """Turn a list of IDs (or DEF codes like 'SF') into readable dicts."""
    out = []
    if not ids:
        return out
    for pid in ids:
        # Team DEFs are 2–3 letter codes like "SF", "PHI", etc.
        if isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3:
            out.append({"id": pid, "name": f"{pid} D/ST", "pos": "DEF", "team": pid})
            continue
        info = idx.get(str(pid)) or {}
        out.append({
            "id": str(pid),
            "name": info.get("name") or str(pid),
            "pos": info.get("pos"),
            "team": info.get("team"),
            "status": info.get("status"),
        })
    return out


def name_matchups(matchups, idx):
    named = []
    for m in matchups or []:
        named.append({
            "matchup_id": m.get("matchup_id"),
            "roster_id": m.get("roster_id"),
            "points": m.get("points", 0.0),
            "starters": resolve_ids(m.get("starters"), idx),
            "players": resolve_ids(m.get("players"), idx),
            "players_points": m.get("players_points", {}),
        })
    return named


def print_week1_summary(snapshot: dict, team_name_exact: str = "Taylor Park Boys"):
    """
    Print Week 1 player-by-player points for the given team name to stdout.
    This shows up in GitHub Actions logs.
    """
    try:
        # Find your owner_id by matching users[].metadata.team_name
        owner_id = None
        for u in snapshot.get("users", []):
            tn = ((u.get("metadata") or {}).get("team_name") or "").strip().lower()
            if tn == team_name_exact.lower():
                owner_id = u.get("user_id")
                break

        # Look up your roster_id from rosters[]
        roster_id = None
        if owner_id:
            for r in snapshot.get("rosters", []):
                if r.get("owner_id") == owner_id:
                    roster_id = r.get("roster_id")
                    break
        if roster_id is None:
            roster_id = 10  # fallback from earlier snapshot

        # Prefer named week 1; fall back to raw
        wk1_list = snapshot.get("matchups_week1_named") or snapshot.get("matchups_week1", [])
        m = next((x for x in wk1_list if x.get("roster_id") == roster_id), None)
        if not m:
            print(f"[SUMMARY] No Week 1 data found for roster_id {roster_id}")
            return

        starters = m.get("starters") or m.get("players") or []
        named = bool(starters) and isinstance(starters[0], dict)
        pidx = snapshot.get("players_index", {})
        ids = [(p.get("id") if isinstance(p, dict) else p) for p in starters]
        pp = m.get("players_points", {})

        rows = []
        total = 0.0
        for pid in ids:
            pts = float(pp.get(str(pid), 0.0))
            nm = None
            if named:
                for P in starters:
                    if isinstance(P, dict) and P.get("id") == pid:
                        nm = P.get("name")
                        break
            if not nm:
                # DEF codes like "SF" → "SF D/ST"
                if isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3:
                    nm = f"{pid} D/ST"
                else:
                    nm = (pidx.get(str(pid), {}) or {}).get("name") or str(pid)
            rows.append((nm, pts))
            total += pts

        rows.sort(key=lambda x: x[1], reverse=True)
        print("=== Week 1 — Taylor Park Boys ===")
        for nm, pts in rows:
            print(f"{nm:28s} {pts:6.2f}")
        print("------------------------------------")
        print(f"Team total (Week 1):      {total:.2f}")
    except Exception as e:
        print("[SUMMARY] Error while printing Week 1 summary:", e)


def main():
    # NFL state
    state = get(f"{BASE}/state/nfl", pause=0.0)
    season = str(state.get("season"))
    week = int(state.get("week") or 1)

    # League + users/rosters
    league = get(f"{BASE}/league/{LEAGUE_ID}")
    users = get(f"{BASE}/league/{LEAGUE_ID}/users")
    rosters = get(f"{BASE}/league/{LEAGUE_ID}/rosters")

    # Matchups: current week AND Week 1
    matchups_current = get(f"{BASE}/league/{LEAGUE_ID}/matchups/{week}")
    matchups_week1 = get(f"{BASE}/league/{LEAGUE_ID}/matchups/1")

    # Players index and named variants
    players_index = get_players_index(force_refresh=False)
    rosters_named = []
    owners = {u["user_id"]: (u.get("display_name") or u.get("username") or "Unknown") for u in users}
    for r in rosters:
        rosters_named.append({
            "roster_id": r.get("roster_id"),
            "owner_id": r.get("owner_id"),
            "owner_name": owners.get(r.get("owner_id"), "Unknown"),
            "record": r.get("metadata", {}).get("record"),
            "streak": r.get("metadata", {}).get("streak"),
            "waiver_position": r.get("settings", {}).get("waiver_position"),
            "fpts": (r.get("settings", {}).get("fpts") or 0) + (r.get("settings", {}).get("fpts_decimal") or 0)/100,
            "fpts_against": (r.get("settings", {}).get("fpts_against") or 0) + (r.get("settings", {}).get("fpts_against_decimal") or 0)/100,
            "players": resolve_ids(r.get("players"), players_index),
            "starters": resolve_ids(r.get("starters"), players_index),
            "reserve": resolve_ids(r.get("reserve"), players_index),
        })

    matchups_named = name_matchups(matchups_current, players_index)
    matchups_week1_named = name_matchups(matchups_week1, players_index)

    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "week": week,
        "league": {"league_id": LEAGUE_ID, "name": LEAGUE_NAME, "sleeper_league_obj": league},
        "users": users,
        "rosters": rosters,
        "rosters_named": rosters_named,
        "matchups": matchups_current,
        "matchups_named": matchups_named,
        "matchups_week1": matchups_week1,
        "matchups_week1_named": matchups_week1_named,
        "players_index": players_index,
    }

    # Save
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path_ts = OUTDIR / f"{season}-wk{week}-{ts}.json"
    path_latest = OUTDIR / "latest.json"
    with open(path_ts, "w") as f:
        json.dump(snapshot, f, indent=2)
    with open(path_latest, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"[WRITE] {path_latest} and {path_ts}")

    # Print Week 1 summary to the logs (no YAML gymnastics)
    print_week1_summary(snapshot, team_name_exact="Taylor Park Boys")


if __name__ == "__main__":
    main()
