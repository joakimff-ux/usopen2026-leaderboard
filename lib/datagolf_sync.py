"""DataGolf live scoring sync for golf_konk Supabase schema."""

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

logger = logging.getLogger(__name__)

ABORTED_NO_WRITE_MSG = "Existing scores were not modified."


class DataGolfRateLimitError(RuntimeError):
    """Raised when DataGolf returns HTTP 429."""


BASE_URL = "https://feeds.datagolf.com"
IN_PLAY_ENDPOINT = f"{BASE_URL}/preds/in-play"
DEFAULT_TOUR = "pga"
MIN_RELATIVE_SCORE = -30
MAX_RELATIVE_SCORE = 30

# DataGolf name (normalized) -> database player name (normalized)
NAME_ALIASES: dict[str, str] = {
    "maverick mcnealy": "mav mcnealy",
    "aaron rai": "rai rai",
    "si woo kim": "si woo kim",
    "ludvig aberg": "ludvig aberg",
}


@dataclass
class SyncResult:
    success: bool
    synced_at: datetime
    players_updated: int = 0
    scores_written: int = 0
    matched_players: list[str] = field(default_factory=list)
    unmatched_players: list[str] = field(default_factory=list)
    sample_writes: list[dict[str, Any]] = field(default_factory=list)
    event_name: str | None = None
    error: str | None = None


@dataclass
class FieldImportResult:
    success: bool
    existing_count: int = 0
    added_count: int = 0
    field_count: int = 0
    new_players: list[str] = field(default_factory=list)
    ambiguous_names: list[str] = field(default_factory=list)
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
        if exc.code == 429:
            raise DataGolfRateLimitError(
                f"DataGolf API rate limited (HTTP 429). {ABORTED_NO_WRITE_MSG}"
            ) from exc
        raise RuntimeError(
            f"DataGolf API request failed with HTTP {exc.code}. {ABORTED_NO_WRITE_MSG}"
        ) from exc
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


def extract_current_round(payload: dict[str, Any]) -> int | None:
    info = payload.get("info")
    if isinstance(info, dict):
        current_round = info.get("current_round")
        if isinstance(current_round, int) and 1 <= current_round <= 4:
            return current_round
    return None


def is_stroke_total(value: Any) -> bool:
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        return False
    return numeric > MAX_RELATIVE_SCORE or numeric < MIN_RELATIVE_SCORE


def parse_relative_to_par(value: Any) -> int | None:
    """Parse golf score relative to par. E -> 0, +4 -> 4, -3 -> -3."""
    if value is None:
        return None

    if isinstance(value, str):
        cleaned = value.strip().upper()
        if not cleaned or cleaned == "-":
            return None
        if cleaned in {"E", "EVEN"}:
            return 0
        if cleaned.startswith("+"):
            try:
                numeric = int(cleaned[1:])
            except ValueError:
                return None
        else:
            try:
                numeric = int(cleaned)
            except ValueError:
                return None
    else:
        try:
            numeric = int(float(value))
        except (TypeError, ValueError):
            return None

    if numeric > MAX_RELATIVE_SCORE or numeric < MIN_RELATIVE_SCORE:
        return None
    return numeric


def is_valid_relative_score(value: int) -> bool:
    return MIN_RELATIVE_SCORE <= value <= MAX_RELATIVE_SCORE


def parse_cumulative_relative(value: Any) -> int | None:
    """Parse a DataGolf R1-R4 cumulative value relative to par."""
    return parse_relative_to_par(value)


def build_cumulative_totals(
    record: dict[str, Any],
    event_current_round: int | None = None,
) -> dict[int, int]:
    """Collect cumulative relative-to-par totals from DataGolf R1-R4 fields."""
    cumulative: dict[int, int] = {}

    for round_num in range(1, 5):
        raw_value = record.get(f"R{round_num}")
        if raw_value is None:
            continue
        parsed = parse_cumulative_relative(raw_value)
        if parsed is not None:
            cumulative[round_num] = parsed

    if cumulative:
        return cumulative

    # Fallback when R fields hold stroke totals: derive from current_score and today.
    player_round = record.get("round")
    if not isinstance(player_round, int):
        player_round = event_current_round

    today = parse_relative_to_par(record.get("today"))
    current_total = parse_relative_to_par(record.get("current_score"))

    if not isinstance(player_round, int) or current_total is None:
        return cumulative

    cumulative[player_round] = current_total
    if player_round > 1 and today is not None:
        prior_total = current_total - today
        if is_valid_relative_score(prior_total):
            cumulative[player_round - 1] = prior_total

    return cumulative


def cumulative_to_round_deltas(cumulative: dict[int, int]) -> dict[int, int]:
    """
    Convert cumulative relative totals to per-round deltas.

    Round 1 = R1
    Round 2 = R2 - R1
    Round 3 = R3 - R2
    Round 4 = R4 - R3
    """
    deltas: dict[int, int] = {}

    for round_num in sorted(cumulative):
        if round_num == 1:
            if is_valid_relative_score(cumulative[1]):
                deltas[1] = cumulative[1]
            continue

        previous_round = round_num - 1
        if previous_round not in cumulative:
            continue

        delta = cumulative[round_num] - cumulative[previous_round]
        if is_valid_relative_score(delta):
            deltas[round_num] = delta

    return deltas


def extract_round_scores(
    record: dict[str, Any],
    event_current_round: int | None = None,
) -> dict[int, int]:
    """Build per-round scores relative to par from cumulative DataGolf values."""
    cumulative = build_cumulative_totals(record, event_current_round=event_current_round)
    return cumulative_to_round_deltas(cumulative)


def extract_player_name(record: dict[str, Any]) -> str | None:
    for field_name in ("player_name", "name", "player"):
        value = record.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def datagolf_name_to_standard(name: str) -> str:
    cleaned = name.strip()
    if "," in cleaned:
        last, first = [part.strip() for part in cleaned.split(",", 1)]
        if first and last:
            return f"{first} {last}"
    return cleaned


def fetch_players(client: Client) -> list[dict[str, Any]]:
    response = client.table("players").select("id,name").order("name").execute()
    return response.data or []


def build_player_lookup(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for player in players:
        lookup[normalize_name(player["name"])] = player
    return lookup


def find_ambiguous_normalized_names(players: list[dict[str, Any]]) -> set[str]:
    """Return normalized names that map to multiple database players."""
    seen: dict[str, str] = {}
    ambiguous: set[str] = set()
    for player in players:
        key = normalize_name(player["name"])
        if key in seen and seen[key] != player["name"]:
            ambiguous.add(key)
        seen[key] = player["name"]
    return ambiguous


def extract_field_player_names(records: list[dict[str, Any]]) -> list[str]:
    """Collect unique DataGolf field names using standard First Last formatting."""
    names: list[str] = []
    seen: set[str] = set()
    for record in records:
        datagolf_name = extract_player_name(record)
        if not datagolf_name:
            continue
        standard_name = datagolf_name_to_standard(datagolf_name).strip()
        normalized = normalize_name(standard_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        names.append(standard_name)
    return sorted(names)


def classify_field_players(
    field_names: list[str],
    player_lookup: dict[str, dict[str, Any]],
    ambiguous_keys: set[str],
) -> tuple[int, list[str], list[str]]:
    """
    Split DataGolf field names into existing matches, new inserts, and ambiguous rows.
    """
    existing_count = 0
    to_add: list[str] = []
    ambiguous_names: list[str] = []

    for standard_name in field_names:
        datagolf_name = standard_name
        normalized = normalize_name(standard_name)
        if normalized in ambiguous_keys:
            ambiguous_names.append(standard_name)
            continue

        if match_database_player(datagolf_name, player_lookup) is not None:
            existing_count += 1
            continue

        to_add.append(standard_name)

    return existing_count, to_add, sorted(set(ambiguous_names))


def import_missing_field_players(
    client: Client,
    api_key: str,
    tour: str = DEFAULT_TOUR,
    extra_tier_label: str = "Ekstra",
) -> FieldImportResult:
    """Import DataGolf field players that are not already in the players table."""
    if not api_key:
        return FieldImportResult(success=False, error="DATA_GOLF_API_KEY is not configured.")
    if client is None:
        return FieldImportResult(success=False, error="Supabase client is not configured.")

    try:
        payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
        records = extract_player_records(payload)
        event_name = extract_event_name(payload)
        if not records:
            return FieldImportResult(
                success=False,
                event_name=event_name,
                error="DataGolf response did not contain any player records.",
            )

        field_names = extract_field_player_names(records)
        db_players = fetch_players(client)
        player_lookup = build_player_lookup(db_players)
        ambiguous_keys = find_ambiguous_normalized_names(db_players)
        existing_count, to_add, ambiguous_names = classify_field_players(
            field_names,
            player_lookup,
            ambiguous_keys,
        )

        new_players: list[str] = []
        for name in to_add:
            try:
                client.table("players").insert(
                    {"name": name, "tier": extra_tier_label or None}
                ).execute()
                new_players.append(name)
                player_lookup[normalize_name(name)] = {"name": name}
            except Exception as exc:
                logger.warning("Could not insert field player %s: %s", name, exc)
                ambiguous_names.append(name)

        return FieldImportResult(
            success=True,
            existing_count=existing_count,
            added_count=len(new_players),
            field_count=len(field_names),
            new_players=sorted(new_players),
            ambiguous_names=sorted(set(ambiguous_names)),
            event_name=event_name,
        )
    except DataGolfRateLimitError as exc:
        return FieldImportResult(success=False, error=str(exc))
    except Exception as exc:
        logger.exception("DataGolf field import failed")
        return FieldImportResult(success=False, error=str(exc))


def match_database_player(
    datagolf_name: str,
    player_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [datagolf_name, datagolf_name_to_standard(datagolf_name)]
    for candidate in candidates:
        normalized = normalize_name(candidate)
        if normalized in player_lookup:
            return player_lookup[normalized]
        alias_target = NAME_ALIASES.get(normalized)
        if alias_target and alias_target in player_lookup:
            return player_lookup[alias_target]
    return None


def count_scores(client: Client) -> int:
    response = client.table("scores").select("id", count="exact").execute()
    return int(response.count or 0)


def build_score_updates(
    records: list[dict[str, Any]],
    player_lookup: dict[str, dict[str, Any]],
    event_round: int | None,
) -> tuple[list[dict[str, Any]], list[str], list[str], dict[str, dict[int, int]]]:
    """Match players and build upsert rows without touching the database."""
    matched_players: list[str] = []
    unmatched_players: list[str] = []
    score_rows: list[dict[str, Any]] = []
    player_round_scores: dict[str, dict[int, int]] = {}

    for record in records:
        datagolf_name = extract_player_name(record)
        if not datagolf_name:
            continue

        round_scores = extract_round_scores(record, event_current_round=event_round)
        if not round_scores:
            continue

        db_player = match_database_player(datagolf_name, player_lookup)
        if db_player is None:
            unmatched_players.append(datagolf_name)
            logger.warning("Unmatched DataGolf player: %s", datagolf_name)
            continue

        player_name = db_player["name"]
        matched_players.append(player_name)
        player_round_scores[player_name] = round_scores

        for round_num, relative_score in round_scores.items():
            if not is_valid_relative_score(relative_score):
                logger.warning(
                    "Skipped invalid relative score for %s R%s: %s",
                    player_name,
                    round_num,
                    relative_score,
                )
                continue
            score_rows.append(
                {
                    "player_id": int(db_player["id"]),
                    "round_no": round_num,
                    "score": relative_score,
                }
            )

    return score_rows, matched_players, unmatched_players, player_round_scores


def preview_sync_scores(api_key: str, tour: str = DEFAULT_TOUR) -> dict[str, Any]:
    payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
    records = extract_player_records(payload)
    event_round = extract_current_round(payload)
    sample_players = []

    for record in records:
        datagolf_name = extract_player_name(record)
        if not datagolf_name:
            continue
        round_scores = extract_round_scores(record, event_current_round=event_round)
        if not round_scores:
            continue
        sample_players.append(
            {
                "datagolf_name": datagolf_name,
                "db_name": datagolf_name_to_standard(datagolf_name),
                "round_scores": round_scores,
            }
        )
        if len(sample_players) >= 10:
            break

    parsed_count = sum(
        1 for record in records if extract_round_scores(record, event_current_round=event_round)
    )
    return {
        "event_name": extract_event_name(payload),
        "records_found": len(records),
        "parsed_score_count": parsed_count,
        "sample_players": sample_players,
    }


def sync_live_scores(
    client: Client,
    api_key: str,
    tour: str = DEFAULT_TOUR,
) -> SyncResult:
    synced_at = datetime.now(timezone.utc)

    try:
        payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
        records = extract_player_records(payload)
        event_round = extract_current_round(payload)
        event_name = extract_event_name(payload)

        if not records:
            return SyncResult(
                success=False,
                synced_at=synced_at,
                event_name=event_name,
                error=(
                    "DataGolf response did not contain any player records. "
                    f"{ABORTED_NO_WRITE_MSG}"
                ),
            )

        db_players = fetch_players(client)
        player_lookup = build_player_lookup(db_players)
        score_rows, matched_players, unmatched_players, player_round_scores = build_score_updates(
            records,
            player_lookup,
            event_round,
        )

        if not score_rows:
            return SyncResult(
                success=False,
                synced_at=synced_at,
                matched_players=sorted(set(matched_players)),
                unmatched_players=sorted(set(unmatched_players)),
                event_name=event_name,
                error=(
                    "No valid relative-to-par round scores were available to sync from DataGolf. "
                    f"{ABORTED_NO_WRITE_MSG}"
                ),
            )

        client.table("scores").upsert(score_rows, on_conflict="player_id,round_no").execute()

        matched_player_ids = {row["player_id"] for row in score_rows}
        sample_writes = [
            {
                "player_name": player_name,
                "round_scores": player_round_scores[player_name],
            }
            for player_name in sorted(player_round_scores.keys())[:10]
        ]

        return SyncResult(
            success=True,
            synced_at=synced_at,
            players_updated=len(matched_player_ids),
            scores_written=len(score_rows),
            matched_players=sorted(set(matched_players)),
            unmatched_players=sorted(set(unmatched_players)),
            sample_writes=sample_writes,
            event_name=event_name,
        )
    except DataGolfRateLimitError as exc:
        logger.warning("DataGolf sync aborted due to rate limit")
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("DataGolf sync failed")
        message = str(exc)
        if ABORTED_NO_WRITE_MSG not in message:
            message = f"{message} {ABORTED_NO_WRITE_MSG}"
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error=message,
        )


def execute_sync(client: Client, secrets: dict[str, Any], tour: str = DEFAULT_TOUR) -> SyncResult:
    synced_at = datetime.now(timezone.utc)
    api_key = get_api_key_from_mapping(secrets)
    if not api_key:
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error="DATA_GOLF_API_KEY is not configured.",
        )
    if client is None:
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error="Supabase client is not configured.",
        )
    return sync_live_scores(client, api_key=api_key, tour=tour)


def run_cumulative_delta_test() -> dict[str, Any]:
    hovland_record = {"R1": 4, "R2": 5, "R3": None, "R4": None}
    hovland_scores = extract_round_scores(hovland_record)
    hovland_passed = hovland_scores == {1: 4, 2: 1}

    three_round_record = {"R1": -2, "R2": 1, "R3": 3, "R4": None}
    three_round_scores = extract_round_scores(three_round_record)
    three_round_passed = three_round_scores == {1: -2, 2: 3, 3: 2}

    missing_prior_record = {"R1": None, "R2": 2, "R3": None, "R4": None}
    missing_prior_scores = extract_round_scores(missing_prior_record)
    missing_prior_passed = missing_prior_scores == {}

    return {
        "passed": hovland_passed and three_round_passed and missing_prior_passed,
        "checks": [
            {
                "name": "Viktor Hovland R1=+4 R2=+5",
                "expected": {1: 4, 2: 1},
                "actual": hovland_scores,
                "passed": hovland_passed,
            },
            {
                "name": "Three cumulative rounds",
                "expected": {1: -2, 2: 3, 3: 2},
                "actual": three_round_scores,
                "passed": three_round_passed,
            },
            {
                "name": "Missing R1 should not write R2",
                "expected": {},
                "actual": missing_prior_scores,
                "passed": missing_prior_passed,
            },
        ],
    }


def run_name_matching_test() -> dict[str, Any]:
    sample_players = [
        {"id": 1, "name": "Scottie Scheffler"},
        {"id": 2, "name": "Si woo Kim"},
        {"id": 3, "name": "Adam scott"},
        {"id": 4, "name": "Mav McNealy"},
        {"id": 5, "name": "Rai Rai"},
    ]
    lookup = build_player_lookup(sample_players)
    checks = [
        ("Scheffler, Scottie", "Scottie Scheffler", True),
        ("Kim, Si Woo", "Si woo Kim", True),
        ("Scott, Adam", "Adam scott", True),
        ("McNealy, Maverick", "Mav McNealy", True),
        ("Rai, Aaron", "Rai Rai", True),
        ("Rahm, Jon", None, False),
    ]
    results = []
    for datagolf_name, expected_name, should_match in checks:
        matched = match_database_player(datagolf_name, lookup)
        matched_name = matched["name"] if matched else None
        passed = (matched is not None) == should_match
        if should_match and matched_name != expected_name:
            passed = False
        results.append(
            {
                "datagolf_name": datagolf_name,
                "expected_match": should_match,
                "matched_name": matched_name,
                "passed": passed,
            }
        )
    return {
        "passed": all(item["passed"] for item in results),
        "checks": results,
    }


def run_field_import_test() -> dict[str, Any]:
    sample_players = [
        {"id": 1, "name": "Scottie Scheffler"},
        {"id": 2, "name": "Mav McNealy"},
        {"id": 3, "name": "Rai Rai"},
    ]
    lookup = build_player_lookup(sample_players)
    ambiguous_keys = find_ambiguous_normalized_names(sample_players)
    field_names = extract_field_player_names(
        [
            {"player_name": "Scheffler, Scottie"},
            {"player_name": "McNealy, Maverick"},
            {"player_name": "Rai, Aaron"},
            {"player_name": "Rahm, Jon"},
            {"player_name": "Rahm, Jon"},
            {"player_name": ""},
        ]
    )
    existing_count, to_add, ambiguous_names = classify_field_players(
        field_names,
        lookup,
        ambiguous_keys,
    )
    checks = [
        {
            "name": "Unique field names extracted",
            "expected": ["Aaron Rai", "Jon Rahm", "Maverick McNealy", "Scottie Scheffler"],
            "actual": field_names,
            "passed": field_names
            == ["Aaron Rai", "Jon Rahm", "Maverick McNealy", "Scottie Scheffler"],
        },
        {
            "name": "Existing players counted",
            "expected": 3,
            "actual": existing_count,
            "passed": existing_count == 3,
        },
        {
            "name": "Only missing players queued",
            "expected": ["Jon Rahm"],
            "actual": to_add,
            "passed": to_add == ["Jon Rahm"],
        },
        {
            "name": "No ambiguous names in clean sample",
            "expected": [],
            "actual": ambiguous_names,
            "passed": ambiguous_names == [],
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }
