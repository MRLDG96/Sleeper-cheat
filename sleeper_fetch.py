#!/usr/bin/env python3
# League locked: "The *ick Is In!"  |  League ID: 1257451535101612032
# Produces one consolidated JSON snapshot that includes:
# - NFL state
# - League (meta), Users, Rosters
# - Matchups for weeks 1..current
# - Transactions for weeks 1..current
# - Drafts for this league + picks + traded picks
# - League-level traded picks
# - Players index (ID -> {name,pos,team,status})  [slimmed in snapshot by default]
# - Named helpers for rosters (readable) and current-week matchups
#
# Output files:
#   data/sleeper/The-ick-Is-In/latest.json
#   data/sleeper/The-ick-Is-In/<season>-wk<week>-<timestamp>.json

import json
import pathlib
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Iterable

import requests

# ----------------------------
# Config — change if needed
# ----------------------------
LEAGUE_ID = "1257451535101612032"
LEAGUE_NAME = "The *ick Is In!"
USER_AGENT = "sleeper-cheat-fetch/2.1 (+GitHub Actions)"
SLEEP = 0.10                 # polite pause between HTTP calls (seconds)
MAX_RETRIES = 3              # retries per request
RETRY_BACKOFF = 0.8          # seconds, exponential

# If True, also build "named" (human-readable) expansions for ALL weeks' matchups.
# This can make the JSON very large for big leagues. Default: only name current week.
NAME_ALL_WEEKS = False

# If True, include only the player IDs used by your league in the snapshot's players_index
# (the full catalog is still cached on disk). Greatly reduces latest.json size.
SLIM_PLAYERS_INDEX_IN_SNAPSHOT = True

# ----------------------------
# Paths
# ----------------------------
LEAGUE_SLUG = re.sub(r"[^A-Za-z0-9]+", "-", LEAGUE_NAME).strip("-")
BASE = "https://api.sleeper.app/v1"

OUTDIR = pathlib.Path("data/sleeper") / LEAGUE_SLUG
OUTDIR.mkdir(parents=True, exist_ok=True)

PLAYERS_DIR = pathlib.Path("data/sleeper/players")
PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
PLAYERS_CACHE = PLAYERS_DIR / "players-lite.json"

# Reusable HTTP session
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


# ----------------------------
# HTTP helpers
# ----------------------------
def get(url: str, pause: float = SLEEP) -> Any:
    """GET with simple retries/backoff for 429/5xx."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = SESSION.get(url, timeout=60)
            # Retry on common transient statuses
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} {r.reason}")
            r.raise_for_status()
            if pause:
                time.sleep(pause)
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * (2 ** (attempt - 1)))
            else:
                raise
    raise last_err  # pragma: no cover


# ----------------------------
# Data builders
# ----------------------------
def get_players_index(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Build a slim {player_id: {name,pos,team,status}} index from Sleeper's /players/nfl.
    Cached to data/sleeper/players/players-lite.json so we don't redownload every run.
    """
    if PLAYERS_CACHE.exists() and not force_refresh:
        with open(PLAYERS_CACHE, "r") as f:
            return json.load(f)

    print("[INFO] Downloading players catalog…")
    players_all = get(f"{BASE}/players/nfl")

    lite: Dict[str, Dict[str, Any]] = {}
    for pid, pdata in players_all.items():
        lite[pid] = {
            "name": pdata.get("full_name") or pdata.get("first_name"),
            "pos": pdata.get("position"),
            "team": pdata.get("team"),
            "status": pdata.get("status"),
        }

    with open(PLAYERS_CACHE, "w") as f:
        json.dump(lite, f)  # keep cache compact (no indent)

    print(f"[INFO] Cached players index with {len(lite):,} entries")
    return lite


def resolve_ids(ids: Iterable[Any], idx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn a list of IDs (or DEF codes like 'SF') into readable dicts."""
    out: List[Dict[str, Any]] = []
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


def name_matchups(matchups: List[Dict[str, Any]], idx: Dict[str, Any]) -> List[Dict[str, Any]]:
    named: List[Dict[str, Any]] = []
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


def fetch_matchups_by_week(league_id: str, week_to: int) -> Dict[str, Any]:
    """Returns {"by_week": { "1": [...], "2": [...], ... }}"""
    try:
        week_to = int(week_to or 1)
    except Exception:
        week_to = 1
    by_week: Dict[str, Any] = {}
    for w in range(1, max(week_to, 1) + 1):
        url = f"{BASE}/league/{league_id}/matchups/{w}"
        try:
            by_week[str(w)] = get(url)
        except Exception as e:
            print(f"[WARN] Matchups week {w} failed: {e}")
            by_week[str(w)] = []
    return {"by_week": by_week}


def fetch_transactions_by_week(league_id: str, week_to: int) -> Dict[str, Any]:
    """Returns {"by_week": { "1": [...], "2": [...], ... }}"""
    try:
        week_to = int(week_to or 1)
    except Exception:
        week_to = 1
    by_week: Dict[str, Any] = {}
    for w in range(1, max(week_to, 1) + 1):
        url = f"{BASE}/league/{league_id}/transactions/{w}"
        try:
            by_week[str(w)] = get(url)
        except Exception as e:
            print(f"[WARN] Transactions week {w} failed: {e}")
            by_week[str(w)] = []
    return {"by_week": by_week}


def fetch_drafts_package(league_id: str) -> Dict[str, Any]:
    """
    Returns {
      "drafts": [...],
      "picks_by_draft": { draft_id: [...] },
      "traded_picks_by_draft": { draft_id: [...] }
    }
    """
    drafts = get(f"{BASE}/league/{league_id}/drafts")
    picks_by_draft: Dict[str, Any] = {}
    traded_picks_by_draft: Dict[str, Any] = {}

    for d in drafts or []:
        draft_id = d.get("draft_id")
        if not draft_id:
            continue
        try:
            picks_by_draft[draft_id] = get(f"{BASE}/draft/{draft_id}/picks")
        except Exception as e:
            print(f"[WARN] Draft picks for {draft_id} failed: {e}")
            picks_by_draft[draft_id] = []
        try:
            traded_picks_by_draft[draft_id] = get(f"{BASE}/draft/{draft_id}/traded_picks")
        except Exception as e:
            print(f"[WARN] Draft traded picks for {draft_id} failed: {e}")
            traded_picks_by_draft[draft_id] = []

    return {
        "drafts": drafts,
        "picks_by_draft": picks_by_draft,
        "traded_picks_by_draft": traded_picks_by_draft,
    }


def collect_used_player_ids(rosters: List[Dict[str, Any]], matchups_by_week: Dict[str, Any]) -> set:
    """Collect all player IDs that appear in rosters and matchups (for slimming index)."""
    used: set = set()
    # From rosters (players / starters / reserve)
    for r in rosters or []:
        for key in ("players", "starters", "reserve"):
            for pid in (r.get(key) or []):
                if isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3:
                    continue  # DEF code, not a player id
                used.add(str(pid))
    # From matchups (players / starters)
    by_week = (matchups_by_week or {}).get("by_week", {})
    for wk, arr in by_week.items():
        for m in arr or []:
            for key in ("players", "starters"):
                for pid in (m.get(key) or []):
                    if isinstance(pid, str) and pid.isalpha() and 2 <= len(pid) <= 3:
                        continue
                    used.add(str(pid))
    return used


# ----------------------------
# Summary printer (handy in Action logs)
# ----------------------------
def print_week1_summary(snapshot: dict, team_name_exact: str = "Taylor Park Boys"):
    """Print Week 1 player-by-player points for your team to stdout (for Actions logs)."""
    try:
        # Find owner_id by users[].metadata.team_name
        owner_id = None
        for u in snapshot.get("users", []):
            tn = ((u.get("metadata") or {}).get("team_name") or "").strip().lower()
            if tn == team_name_exact.lower():
                owner_id = u.get("user_id")
                break

        # Roster id
        roster_id = None
        if owner_id:
            for r in snapshot.get("rosters", []):
                if r.get("owner_id") == owner_id:
                    roster_id = r.get("roster_id")
                    break
        if roster_id is None:
            roster_id = 10  # fallback seen earlier

        wk1_list = snapshot.get("matchups_all_weeks_named", {}).get("by_week", {}).get("1") \
                   or snapshot.get("matchups_all_weeks", {}).get("by_week", {}).get("1")
        if not wk1_list:
            print(f"[SUMMARY] No Week 1 data found")
            return

        # wk1_list is a list of matchup entries; pick your roster
        m = next((x for x in wk1_list if x.get("roster_id") == roster_id), None)
        if not m:
            print(f"[SUMMARY] No Week 1 entry for roster {roster_id}")
            return

        starters = m.get("starters") or m.get("players") or []
        pidx = snapshot.get("players_index", {})
        # items are dicts if named, otherwise raw ids
        ids = [(p.get("id") if isinstance(p, dict) else p) for p in starters]
        pp = m.get("players_points", {})

        rows = []
        total = 0.0
        for pid in ids:
            pts = float(pp.get(str(pid), 0.0))
            # if named, find name in starters list; else resolve from index / DEF code
            nm = None
            for P in starters:
                if isinstance(P, dict) and P.get("id") == pid:
                    nm = P.get("name"); break
            if not nm:
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


# ----------------------------
# Main
# ----------------------------
def main():
    # NFL state
    state = get(f"{BASE}/state/nfl", pause=0.0)
    # Guard week in case Sleeper ever reports 0/None between weeks
    try:
        week = int(state.get("week") or 1)
        if week <= 0:
            week = 1
    except Exception:
        week = 1
    season = str(state.get("season") or "")

    print(f"[STATE] season={season} week={week}")

    # League, users, rosters
    league = get(f"{BASE}/league/{LEAGUE_ID}")
    users = get(f"{BASE}/league/{LEAGUE_ID}/users")
    rosters = get(f"{BASE}/league/{LEAGUE_ID}/rosters")

    # Matchups (all weeks up to current)
    matchups_all_weeks = fetch_matchups_by_week(LEAGUE_ID, week)

    # Transactions (all weeks up to current)
    transactions_all_weeks = fetch_transactions_by_week(LEAGUE_ID, week)

    # Drafts package (drafts + picks + traded picks)
    drafts_pkg = fetch_drafts_package(LEAGUE_ID)

    # League traded picks (non-draft-specific endpoint)
    try:
        league_traded_picks = get(f"{BASE}/league/{LEAGUE_ID}/traded_picks")
    except Exception as e:
        print(f"[WARN] league_traded_picks failed: {e}")
        league_traded_picks = []

    # Players index (cached)
    players_index_full = get_players_index(force_refresh=False)

    # Optionally slim players_index to only used IDs in THIS league (for the snapshot)
    if SLIM_PLAYERS_INDEX_IN_SNAPSHOT:
        used_ids = collect_used_player_ids(rosters, matchups_all_weeks)
        players_index = {pid: players_index_full.get(pid, {}) for pid in used_ids}
        print(f"[INFO] Slim players_index for snapshot: {len(players_index):,} of {len(players_index_full):,}")
    else:
        players_index = players_index_full

    # Readable helpers
    owners = {u["user_id"]: (u.get("display_name") or u.get("username") or "Unknown") for u in users}
    rosters_named = []
    for r in rosters or []:
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

    # Named matchups: current week always; optionally all weeks
    current_week_arr = (matchups_all_weeks.get("by_week") or {}).get(str(week), []) or []
    matchups_named_current = name_matchups(current_week_arr, players_index)

    matchups_all_weeks_named = None
    if NAME_ALL_WEEKS:
        by_week_named = {}
        for wk, arr in (matchups_all_weeks.get("by_week") or {}).items():
            by_week_named[wk] = name_matchups(arr or [], players_index)
        matchups_all_weeks_named = {"by_week": by_week_named}

    # Build snapshot
    snapshot = {
        "snapshot_version": 3,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "week": week,

        "endpoints": {  # for traceability
            "state": f"{BASE}/state/nfl",
            "league": f"{BASE}/league/{LEAGUE_ID}",
            "users": f"{BASE}/league/{LEAGUE_ID}/users",
            "rosters": f"{BASE}/league/{LEAGUE_ID}/rosters",
            "matchups_by_week": f"{BASE}/league/{LEAGUE_ID}/matchups/<WEEK>",
            "transactions_by_week": f"{BASE}/league/{LEAGUE_ID}/transactions/<WEEK>",
            "league_traded_picks": f"{BASE}/league/{LEAGUE_ID}/traded_picks",
            "league_drafts": f"{BASE}/league/{LEAGUE_ID}/drafts",
            "draft_picks": f"{BASE}/draft/<DRAFT_ID>/picks",
            "draft_traded_picks": f"{BASE}/draft/<DRAFT_ID>/traded_picks",
            "players_index_source": f"{BASE}/players/nfl",
        },

        "state": state,
        "league": {"league_id": LEAGUE_ID, "name": LEAGUE_NAME, "sleeper_league_obj": league},
        "users": users,
        "rosters": rosters,
        "rosters_named": rosters_named,

        "matchups_all_weeks": matchups_all_weeks,           # raw by week 1..current
        "matchups_named_current": matchups_named_current,   # readable, current week only (compact)

        "transactions_all_weeks": transactions_all_weeks,   # raw by week 1..current
        "league_traded_picks": league_traded_picks,

        "drafts_pkg": fetch_drafts_package(LEAGUE_ID),      # drafts + picks + traded picks by draft

        "players_index": players_index,                     # slimmed (or full if flag is False)
    }

    if matchups_all_weeks_named is not None:
        snapshot["matchups_all_weeks_named"] = matchups_all_weeks_named  # optional large section

    # Save
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path_ts = OUTDIR / f"{season}-wk{week}-{ts}.json"
    path_latest = OUTDIR / "latest.json"
    with open(path_ts, "w") as f:
        json.dump(snapshot, f, indent=2)
    with open(path_latest, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"[WRITE] {path_latest} and {path_ts}")

    # Helpful log summary (non-fatal if anything missing)
    print_week1_summary(snapshot, team_name_exact="Taylor Park Boys")


if __name__ == "__main__":
    main()
