"""DataGolf live scoring sync."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from supabase import Client

from lib.db import ensure_tournament, fetch_players, get_supabase_client_from_config

logger = logging.getLogger(__name__)

BASE_URL = "https://feeds.datagolf.com"
IN_PLAY_ENDPOINT = f"{BASE_URL}/preds/in-play"
DEFAULT_TOUR = "pga"
ROUND_FIELD_NAMES = {
    1: ("R1", "r1", "round_1", "round1", "score_1", "score1"),
    2: ("R2", "r2", "round_2", "round2", "score_2", "score2"),
    3: ("R3", "r3", "round_3", "round3", "score_3", "score3"),
    4: ("R4", "r4", "round_4", "round4", "score_4", "score4"),
}


@dataclass
class SyncResult:
    success: bool
    synced_at: datetime
    players_updated: int = 0
    scores_written: int = 0
    matched_players: list[str] = field(default_factory=list)
    unmatched_players: list[str] = field(default_factory=list)
    event_name: str | None = None
    error: str | None = None


def normalize_name(name: str) -> str:
    cleaned = name.strip().lower()
    cleaned = cleaned.replace(".", " ").replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def get_api_key_from_mapping(config: dict[str, Any]) -> str:
    return str(config.get("DATA_GOLF_API_KEY", "")).strip()


def build_in_play_url(api_key: str, tour: str = DEFAULT_TOUR) -> str:
    query = urlencode(
        {
            "tour": tour,
            "dead_heat": "no",
            "odds_format": "percent",
            "file_format": "json",
            "key": api_key,
        }
    )
    return f"{IN_PLAY_ENDPOINT}?{query}"


def fetch_live_tournament_data(api_key: str, tour: str = DEFAULT_TOUR) -> dict[str, Any]:
    if not api_key:
        raise ValueError("DATA_GOLF_API_KEY is not configured.")

    url = build_in_play_url(api_key, tour=tour)
    try:
        with urlopen(url, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"DataGolf API request failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"DataGolf API request failed: {exc.reason}") from exc

    import json

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DataGolf API returned invalid JSON.") from exc


def extract_player_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("data", "predictions", "players", "field"):
        records = payload.get(key)
        if isinstance(records, list) and records:
            return [record for record in records if isinstance(record, dict)]

    if isinstance(payload.get("event_name"), str):
        nested = payload.get("leaderboard")
        if isinstance(nested, list):
            return [record for record in nested if isinstance(record, dict)]

    return []


def extract_event_name(payload: dict[str, Any]) -> str | None:
    info = payload.get("info")
    if isinstance(info, dict):
        event_name = info.get("event_name")
        if isinstance(event_name, str) and event_name.strip():
            return event_name.strip()

    event_name = payload.get("event_name")
    if isinstance(event_name, str) and event_name.strip():
        return event_name.strip()

    return None


def parse_round_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.upper() in {"-", "E", "EVEN"}:
            return None
        if cleaned.startswith(("+", "E")):
            return None
    try:
        strokes = int(float(value))
    except (TypeError, ValueError):
        return None
    if strokes < 50 or strokes > 100:
        return None
    return strokes


def extract_current_round(payload: dict[str, Any]) -> int | None:
    info = payload.get("info")
    if isinstance(info, dict):
        current_round = info.get("current_round")
        if isinstance(current_round, int) and 1 <= current_round <= 4:
            return current_round
    return None


def extract_round_scores(record: dict[str, Any], current_round: int | None = None) -> dict[int, int]:
    scores: dict[int, int] = {}
    for round_num, field_names in ROUND_FIELD_NAMES.items():
        for field_name in field_names:
            if field_name not in record:
                continue
            parsed = parse_round_value(record.get(field_name))
            if parsed is not None:
                scores[round_num] = parsed
                break

    if current_round is not None:
        for field_name in ("today", "current_round_score", "round_score"):
            if field_name in record:
                parsed = parse_round_value(record.get(field_name))
                if parsed is not None:
                    scores[current_round] = parsed
                break

    return scores


def extract_player_name(record: dict[str, Any]) -> str | None:
    for field_name in ("player_name", "name", "player"):
        value = record.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def build_player_lookup(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for player in players:
        normalized = normalize_name(player["name"])
        lookup[normalized] = player
    return lookup


def match_database_player(
    datagolf_name: str,
    player_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return player_lookup.get(normalize_name(datagolf_name))


def execute_sync(secrets: dict[str, Any], tour: str = DEFAULT_TOUR) -> SyncResult:
    """Run the same sync routine used by datagolf_sync.py --sync."""
    synced_at = datetime.now(timezone.utc)
    api_key = get_api_key_from_mapping(secrets)
    supabase_url = str(secrets.get("SUPABASE_URL", "")).strip()
    supabase_key = str(secrets.get("SUPABASE_ANON_KEY", "")).strip()

    if not api_key:
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error="DATA_GOLF_API_KEY is not configured.",
        )
    if not supabase_url or not supabase_key:
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error="Supabase credentials are not configured.",
        )

    client = get_supabase_client_from_config(supabase_url, supabase_key)
    tournament = ensure_tournament(client)
    return sync_live_scores(client, tournament["id"], api_key=api_key, tour=tour)


def sync_live_scores(
    client: Client,
    tournament_id: str,
    api_key: str,
    tour: str = DEFAULT_TOUR,
) -> SyncResult:
    synced_at = datetime.now(timezone.utc)

    try:
        payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
        records = extract_player_records(payload)
        current_round = extract_current_round(payload)
        if not records:
            return SyncResult(
                success=False,
                synced_at=synced_at,
                error="DataGolf response did not contain any player records.",
            )

        db_players = fetch_players(client, tournament_id)
        player_lookup = build_player_lookup(db_players)
        matched_player_ids: set[str] = set()
        matched_players: list[str] = []
        unmatched_players: list[str] = []
        score_rows: list[dict[str, Any]] = []

        for record in records:
            datagolf_name = extract_player_name(record)
            if not datagolf_name:
                continue

            round_scores = extract_round_scores(record, current_round=current_round)
            if not round_scores:
                continue

            db_player = match_database_player(datagolf_name, player_lookup)
            if db_player is None:
                unmatched_players.append(datagolf_name)
                logger.warning("Unmatched DataGolf player: %s", datagolf_name)
                continue

            matched_player_ids.add(db_player["id"])
            matched_players.append(db_player["name"])
            for round_num, strokes in round_scores.items():
                score_rows.append(
                    {
                        "player_id": db_player["id"],
                        "round": round_num,
                        "strokes": strokes,
                    }
                )

        if score_rows:
            client.table("scores").upsert(score_rows, on_conflict="player_id,round").execute()
        else:
            return SyncResult(
                success=False,
                synced_at=synced_at,
                matched_players=sorted(set(matched_players)),
                unmatched_players=sorted(set(unmatched_players)),
                event_name=extract_event_name(payload),
                error="No round scores were available to sync from DataGolf.",
            )

        return SyncResult(
            success=True,
            synced_at=synced_at,
            players_updated=len(matched_player_ids),
            scores_written=len(score_rows),
            matched_players=sorted(set(matched_players)),
            unmatched_players=sorted(set(unmatched_players)),
            event_name=extract_event_name(payload),
        )
    except Exception as exc:
        logger.exception("DataGolf sync failed")
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error=str(exc),
        )


def run_name_matching_test() -> dict[str, Any]:
    sample_players = [
        {"id": "1", "name": "Scottie Scheffler", "tier": 1},
        {"id": "2", "name": "Si woo Kim", "tier": 3},
        {"id": "3", "name": "Adam scott", "tier": 6},
        {"id": "4", "name": "Justin Rose ", "tier": 4},
    ]
    lookup = build_player_lookup(sample_players)
    checks = [
        ("Scottie Scheffler", True),
        ("si woo kim", True),
        ("Adam Scott", True),
        ("Justin Rose", True),
        ("Jon Rahm", False),
    ]
    results = []
    for datagolf_name, should_match in checks:
        matched = match_database_player(datagolf_name, lookup) is not None
        results.append(
            {
                "datagolf_name": datagolf_name,
                "expected_match": should_match,
                "actual_match": matched,
                "passed": matched == should_match,
            }
        )
    return {
        "passed": all(item["passed"] for item in results),
        "checks": results,
    }


def run_api_test(api_key: str, tour: str = DEFAULT_TOUR) -> dict[str, Any]:
    payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
    records = extract_player_records(payload)
    sample = records[0] if records else {}
    players_with_scores = sum(
        1 for record in records if extract_round_scores(record, current_round=extract_current_round(payload))
    )
    return {
        "event_name": extract_event_name(payload),
        "records_found": len(records),
        "players_with_round_scores": players_with_scores,
        "sample_fields": sorted(sample.keys()) if sample else [],
        "sample_round_scores": extract_round_scores(sample, current_round=extract_current_round(payload))
        if sample
        else {},
    }
