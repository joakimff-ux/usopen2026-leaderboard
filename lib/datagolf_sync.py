"""DataGolf live scoring sync."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from supabase import Client

from lib.db import (
    event_name_matches,
    fetch_live_player_states,
    fetch_active_roster_changes,
    fetch_player_status_events,
    fetch_players,
    fetch_team_players,
    get_active_tournament,
    get_supabase_client_from_config,
    tournament_display_title,
)
from lib import live_feed, roster_changes

logger = logging.getLogger(__name__)

ABORTED_NO_WRITE_MSG = "Existing scores were not modified."


class DataGolfRateLimitError(RuntimeError):
    """Raised when DataGolf returns HTTP 429."""


BASE_URL = "https://feeds.datagolf.com"
IN_PLAY_ENDPOINT = f"{BASE_URL}/preds/in-play"
DEFAULT_TOUR = "pga"
ROUND_FIELD_NAMES = {
    1: ("R1", "r1", "round_1", "round1", "score_1", "score1"),
    2: ("R2", "r2", "round_2", "round2", "score_2", "score2"),
    3: ("R3", "r3", "round_3", "round3", "score_3", "score3"),
    4: ("R4", "r4", "round_4", "round4", "score_4", "score4"),
}
# DataGolf's in-play feed exposes completed rounds as absolute strokes in
# R1-R4, but the active round only as `today` relative to par. Keep the
# conversion fail-closed: only known event/course combinations may create a
# provisional absolute score.
COURSE_PAR_BY_CODE = {
    "RB": 72,  # Royal Birkdale, The Open Championship 2026
}
EVENT_PAR_BY_NAME = {
    "the open championship": 72,
}
NAME_TRANSLATION = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "æ": "ae",
        "Æ": "AE",
        "å": "a",
        "Å": "A",
        "œ": "oe",
        "Œ": "OE",
        "ł": "l",
        "Ł": "L",
    }
)
PLAYER_NAME_ALIASES = {
    "Michael Thorbjørnsen": "Michael Thorbjornsen",
    "Micheal Thorbjornsen": "Michael Thorbjornsen",
    "Cam Smith": "Cameron Smith",
    "Mike Kim": "Michael Kim",
    "Mav McNealy": "Maverick McNealy",
    "JT Poston": "J.T. Poston",
}
DATAGOLF_ID_FIELDS = ("dg_id", "datagolf_id", "data_golf_id")


@dataclass
class SyncResult:
    success: bool
    synced_at: datetime
    players_updated: int = 0
    scores_written: int = 0
    statuses_written: int = 0
    live_events_written: int = 0
    matched_players: list[str] = field(default_factory=list)
    unmatched_players: list[str] = field(default_factory=list)
    event_name: str | None = None
    expected_event_name: str | None = None
    error: str | None = None
    warning: str | None = None


@dataclass
class DataGolfDiagnosticResult:
    """Read-only DataGolf feed check. Never writes to Supabase."""

    checked_at: datetime
    tournament_id: str
    tournament_name: str
    display_title: str
    expected_event_name: str | None
    datagolf_event_name: str | None
    event_found: bool
    players_received: int
    players_with_scores: int
    db_players_count: int
    matched_count: int
    unmatched_count: int
    matched_players: list[str] = field(default_factory=list)
    unmatched_players: list[str] = field(default_factory=list)
    current_round: int | None = None
    error: str | None = None
    warning: str | None = None


def normalize_name(name: str) -> str:
    """Normalize local names and DataGolf's documented `Last, First` format."""
    cleaned = unicodedata.normalize("NFKD", name.translate(NAME_TRANSLATION)).casefold().strip()
    cleaned = "".join(character for character in cleaned if not unicodedata.combining(character))

    if "," in cleaned:
        family_name, given_name = cleaned.split(",", 1)
        if family_name.strip() and given_name.strip():
            cleaned = f"{given_name} {family_name}"

    cleaned = re.sub(r"[.\-'’]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


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


def log_raw_player_samples(records: list[dict[str, Any]], limit: int = 5) -> None:
    """Log complete DataGolf player objects without request credentials."""
    for index, record in enumerate(records[:limit], start=1):
        logger.info(
            "DataGolf raw player JSON %s/%s: %s",
            index,
            min(limit, len(records)),
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str),
        )


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


def resolve_course_par(
    records: list[dict[str, Any]],
    event_name: str | None,
) -> int | None:
    for record in records:
        course_code = str(record.get("course") or "").strip().upper()
        if course_code in COURSE_PAR_BY_CODE:
            return COURSE_PAR_BY_CODE[course_code]

    normalized_event = re.sub(r"\s+", " ", str(event_name or "").strip().casefold())
    return EVENT_PAR_BY_NAME.get(normalized_event)


def extract_round_scores(
    record: dict[str, Any],
    current_round: int | None = None,
    course_par: int | None = None,
) -> dict[int, int]:
    scores: dict[int, int] = {}
    for round_num, field_names in ROUND_FIELD_NAMES.items():
        for field_name in field_names:
            if field_name not in record:
                continue
            parsed = parse_round_value(record.get(field_name))
            if parsed is not None:
                scores[round_num] = parsed
                break

    if current_round is not None and current_round not in scores and course_par is not None:
        hole, is_finished = live_feed.parse_hole(record.get("thru"))
        has_started = hole is not None or is_finished
        relative_score = live_feed.parse_relative_score(record.get("today"))
        if has_started and relative_score is not None:
            provisional_strokes = course_par + relative_score
            if 50 <= provisional_strokes <= 100:
                scores[current_round] = provisional_strokes

    return scores


def score_log_sample(record: dict[str, Any]) -> dict[str, Any]:
    """Return only score-related DataGolf fields; never credentials or odds."""
    fields = (
        "player_name",
        "round",
        "course",
        "R1",
        "R2",
        "R3",
        "R4",
        "today",
        "current_score",
        "round_score",
        "display_score",
        "total",
        "thru",
        "current_pos",
    )
    return {field_name: record.get(field_name) for field_name in fields if field_name in record}


def extract_player_name(record: dict[str, Any]) -> str | None:
    for field_name in ("player_name", "name", "player"):
        value = record.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_datagolf_player_id(record: dict[str, Any]) -> str | None:
    for field_name in DATAGOLF_ID_FIELDS:
        value = record.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def extract_player_status(record: dict[str, Any]) -> str | None:
    """Return only explicit terminal statuses; absence never implies a status."""
    for field_name in ("status", "current_pos", "position", "pos"):
        value = record.get(field_name)
        if not isinstance(value, str):
            continue
        normalized = value.strip().upper()
        if normalized in {"CUT", "WD", "DQ"}:
            return normalized
    return None


def extract_live_snapshot(
    record: dict[str, Any],
    db_player: dict[str, Any],
    current_round: int | None,
    source_updated_at: str | None,
) -> live_feed.LiveSnapshot | None:
    """Extract only documented in-play fields needed for transition detection."""
    round_value = record.get("round", current_round)
    try:
        round_num = int(round_value)
    except (TypeError, ValueError):
        round_num = current_round
    if round_num is None or not 1 <= round_num <= 4:
        return None

    hole, is_finished = live_feed.parse_hole(record.get("thru"))
    try:
        end_hole = int(record.get("end_hole"))
    except (TypeError, ValueError):
        end_hole = None
    if end_hole is not None and not 1 <= end_hole <= 18:
        end_hole = None

    return live_feed.LiveSnapshot(
        player_id=str(db_player["id"]),
        player_name=str(db_player["name"]),
        round=round_num,
        hole=hole,
        is_finished=is_finished,
        round_score=live_feed.parse_relative_score(record.get("today")),
        status=extract_player_status(record),
        end_hole=end_hole,
        source_updated_at=source_updated_at,
    )


def extract_source_updated_at(payload: dict[str, Any]) -> str | None:
    info = payload.get("info")
    if isinstance(info, dict):
        for field_name in ("last_update", "last_updated"):
            value = info.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for field_name in ("last_update", "last_updated"):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _row_to_live_snapshot(row: dict[str, Any], player_name: str = "") -> live_feed.LiveSnapshot:
    return live_feed.LiveSnapshot(
        player_id=str(row["player_id"]),
        player_name=player_name,
        round=int(row["round"]),
        hole=int(row["hole"]) if row.get("hole") is not None else None,
        is_finished=bool(row.get("is_finished")),
        round_score=int(row["round_score"]) if row.get("round_score") is not None else None,
        status=str(row.get("status") or "ACTIVE"),
        source_updated_at=row.get("source_updated_at"),
    )


def persist_live_feed_transitions(
    client: Client,
    tournament_id: str,
    snapshots: list[live_feed.LiveSnapshot],
) -> int:
    """Persist baseline/state and new events; deterministic keys make retries safe."""
    if not snapshots:
        return 0

    previous_rows = fetch_live_player_states(client, tournament_id)
    previous_by_key = {
        (str(row["player_id"]), int(row["round"])): _row_to_live_snapshot(row)
        for row in previous_rows
    }
    event_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []

    for snapshot in snapshots:
        key = (snapshot.player_id, snapshot.round)
        previous = previous_by_key.get(key)
        if snapshot.status is None and previous is not None:
            snapshot = replace(snapshot, status=previous.status)
        event_rows.extend(live_feed.build_events(tournament_id, previous, snapshot))
        state_rows.append(live_feed.state_row(tournament_id, snapshot))

    if event_rows:
        client.table("live_feed_events").upsert(
            event_rows,
            on_conflict="dedupe_key",
            ignore_duplicates=True,
        ).execute()
    client.table("live_player_states").upsert(
        state_rows,
        on_conflict="tournament_id,player_id,round",
    ).execute()
    return len(event_rows)


def build_player_lookup(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for player in players:
        normalized = normalize_name(player["name"])
        lookup[normalized] = player
    return lookup


def build_exact_player_lookup(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(player.get("name") or "").strip(): player
        for player in players
        if str(player.get("name") or "").strip()
    }


def build_player_id_lookup(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for player in players:
        for field_name in DATAGOLF_ID_FIELDS:
            value = player.get(field_name)
            if value is not None and str(value).strip():
                lookup[str(value).strip()] = player
                break
    return lookup


def match_database_player(
    datagolf_name: str,
    player_lookup: dict[str, dict[str, Any]],
    *,
    datagolf_id: str | None = None,
    player_id_lookup: dict[str, dict[str, Any]] | None = None,
    exact_player_lookup: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if datagolf_id and player_id_lookup:
        id_match = player_id_lookup.get(str(datagolf_id).strip())
        if id_match is not None:
            return id_match

    stripped_datagolf_name = datagolf_name.strip()
    exact_match = (exact_player_lookup or {}).get(stripped_datagolf_name)
    if exact_player_lookup is None:
        exact_match = next(
            (
                player
                for player in player_lookup.values()
                if str(player.get("name") or "").strip() == stripped_datagolf_name
            ),
            None,
        )
    if exact_match is not None:
        return exact_match

    normalized_datagolf_name = normalize_name(datagolf_name)
    normalized_match = player_lookup.get(normalized_datagolf_name)
    if normalized_match is not None:
        return normalized_match

    for local_name, canonical_datagolf_name in PLAYER_NAME_ALIASES.items():
        if normalize_name(canonical_datagolf_name) != normalized_datagolf_name:
            continue
        alias_match = player_lookup.get(normalize_name(local_name))
        if alias_match is not None:
            logger.warning(
                "Matched alias: %s -> %s",
                alias_match.get("name", local_name),
                canonical_datagolf_name,
            )
            return alias_match
    return None


def validate_event_name(expected_event_name: str | None, event_name: str | None) -> str | None:
    """Return an error unless the configured and received DataGolf events match."""
    if not expected_event_name:
        return (
            "The active tournament has no datagolf_event_name configured. "
            "Cannot verify the DataGolf feed."
        )
    if not event_name:
        return (
            "DataGolf response did not include an event name. "
            "Cannot verify the live feed."
        )
    if not event_name_matches(expected_event_name, event_name):
        return (
            "DataGolf live feed does not match the active tournament. "
            f"Expected event name: '{expected_event_name}'. "
            f"Received event name: '{event_name}'."
        )
    return None


def run_datagolf_diagnostic(
    client: Client,
    tournament: dict[str, Any],
    api_key: str,
    tour: str = DEFAULT_TOUR,
) -> DataGolfDiagnosticResult:
    """Fetch DataGolf in-play feed and compare to DB. No writes."""
    checked_at = datetime.now(timezone.utc)
    tournament_id = str(tournament["id"])
    expected_event_name = tournament.get("datagolf_event_name")
    display_title = tournament_display_title(tournament)

    base = DataGolfDiagnosticResult(
        checked_at=checked_at,
        tournament_id=tournament_id,
        tournament_name=str(tournament.get("name") or ""),
        display_title=display_title,
        expected_event_name=expected_event_name,
        datagolf_event_name=None,
        event_found=False,
        players_received=0,
        players_with_scores=0,
        db_players_count=0,
        matched_count=0,
        unmatched_count=0,
    )

    if not api_key:
        base.error = "DATA_GOLF_API_KEY is not configured."
        return base

    try:
        payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
    except DataGolfRateLimitError as exc:
        base.error = str(exc)
        return base
    except Exception as exc:
        base.error = str(exc)
        return base

    records = extract_player_records(payload)
    current_round = extract_current_round(payload)
    event_name = extract_event_name(payload)
    course_par = resolve_course_par(records, event_name)

    base.datagolf_event_name = event_name
    base.players_received = len(records)
    base.current_round = current_round
    base.players_with_scores = sum(
        1
        for record in records
        if extract_round_scores(
            record,
            current_round=current_round,
            course_par=course_par,
        )
    )

    event_error = validate_event_name(expected_event_name, event_name)
    if event_error:
        base.error = event_error
        return base

    base.event_found = True

    if not records:
        base.warning = "Event name matches, but the feed contains no player records."
        return base

    db_players = fetch_players(client, tournament_id)
    base.db_players_count = len(db_players)
    player_lookup = build_player_lookup(db_players)
    exact_player_lookup = build_exact_player_lookup(db_players)
    player_id_lookup = build_player_id_lookup(db_players)

    matched: list[str] = []
    unmatched: list[str] = []
    for record in records:
        datagolf_name = extract_player_name(record)
        if not datagolf_name:
            continue
        db_player = match_database_player(
            datagolf_name,
            player_lookup,
            datagolf_id=extract_datagolf_player_id(record),
            player_id_lookup=player_id_lookup,
            exact_player_lookup=exact_player_lookup,
        )
        if db_player is None:
            unmatched.append(datagolf_name)
        else:
            matched.append(db_player["name"])

    base.matched_players = sorted(set(matched))
    base.unmatched_players = sorted(set(unmatched))
    base.matched_count = len(base.matched_players)
    base.unmatched_count = len(base.unmatched_players)

    if base.db_players_count == 0:
        base.warning = (
            "No players in the database for the active tournament yet. "
            "All DataGolf field players appear as unmatched until roster import."
        )

    return base


def execute_datagolf_diagnostic(secrets: dict[str, Any], tour: str = DEFAULT_TOUR) -> DataGolfDiagnosticResult:
    checked_at = datetime.now(timezone.utc)
    api_key = get_api_key_from_mapping(secrets)
    supabase_url = str(secrets.get("SUPABASE_URL", "")).strip()
    supabase_key = str(secrets.get("SUPABASE_ANON_KEY", "")).strip()

    if not api_key:
        return DataGolfDiagnosticResult(
            checked_at=checked_at,
            tournament_id="",
            tournament_name="",
            display_title="",
            expected_event_name=None,
            datagolf_event_name=None,
            event_found=False,
            players_received=0,
            players_with_scores=0,
            db_players_count=0,
            matched_count=0,
            unmatched_count=0,
            error="DATA_GOLF_API_KEY is not configured.",
        )

    if not supabase_url or not supabase_key:
        return DataGolfDiagnosticResult(
            checked_at=checked_at,
            tournament_id="",
            tournament_name="",
            display_title="",
            expected_event_name=None,
            datagolf_event_name=None,
            event_found=False,
            players_received=0,
            players_with_scores=0,
            db_players_count=0,
            matched_count=0,
            unmatched_count=0,
            error="SUPABASE_URL and SUPABASE_ANON_KEY are required for diagnostics.",
        )

    client = get_supabase_client_from_config(supabase_url, supabase_key)
    tournament = get_active_tournament(client)
    if tournament is None:
        return DataGolfDiagnosticResult(
            checked_at=checked_at,
            tournament_id="",
            tournament_name="",
            display_title="",
            expected_event_name=None,
            datagolf_event_name=None,
            event_found=False,
            players_received=0,
            players_with_scores=0,
            db_players_count=0,
            matched_count=0,
            unmatched_count=0,
            error="No active tournament found in tournaments table.",
        )

    return run_datagolf_diagnostic(client, tournament, api_key=api_key, tour=tour)


def execute_sync(secrets: dict[str, Any], tour: str = DEFAULT_TOUR) -> SyncResult:
    """Run the same sync routine used by datagolf_sync.py --sync."""
    synced_at = datetime.now(timezone.utc)
    api_key = get_api_key_from_mapping(secrets)
    supabase_url = str(secrets.get("SUPABASE_URL", "")).strip()
    supabase_key = str(secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()

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
            error="SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for score sync.",
        )

    client = get_supabase_client_from_config(supabase_url, supabase_key)
    tournament = get_active_tournament(client)
    if tournament is None:
        return SyncResult(
            success=False,
            synced_at=synced_at,
            error="No active tournament found in tournaments table.",
        )
    return sync_live_scores(
        client,
        tournament,
        api_key=api_key,
        tour=tour,
    )


def sync_live_scores(
    client: Client,
    tournament: dict[str, Any],
    api_key: str,
    tour: str = DEFAULT_TOUR,
) -> SyncResult:
    synced_at = datetime.now(timezone.utc)
    tournament_id = str(tournament["id"])
    expected_event_name = tournament.get("datagolf_event_name")

    try:
        payload = fetch_live_tournament_data(api_key=api_key, tour=tour)
        records = extract_player_records(payload)
        log_raw_player_samples(records)
        current_round = extract_current_round(payload)
        event_name = extract_event_name(payload)
        course_par = resolve_course_par(records, event_name)
        source_updated_at = extract_source_updated_at(payload)
        event_error = validate_event_name(expected_event_name, event_name)
        if event_error:
            logger.warning("DataGolf sync blocked: %s", event_error)
            return SyncResult(
                success=False,
                synced_at=synced_at,
                event_name=event_name,
                expected_event_name=expected_event_name,
                error=f"{event_error} {ABORTED_NO_WRITE_MSG}",
            )
        if not records:
            return SyncResult(
                success=False,
                synced_at=synced_at,
                error=(
                    "DataGolf response did not contain any player records. "
                    f"{ABORTED_NO_WRITE_MSG}"
                ),
            )

        db_players = fetch_players(client, tournament_id)
        team_player_rows = fetch_team_players(client, tournament_id)
        original_by_team: dict[str, list[str]] = {}
        for row in team_player_rows:
            original_by_team.setdefault(str(row["team_id"]), []).append(
                str(row["player_id"])
            )
        try:
            active_change_rows = fetch_active_roster_changes(client, tournament_id)
        except Exception:
            active_change_rows = []
        active_by_team = roster_changes.roster_for_scoring_round(
            original_by_team,
            active_change_rows,
            round_num=current_round or 1,
        )
        selected_player_ids = {
            player_id
            for player_ids in active_by_team.values()
            for player_id in player_ids
        }
        player_lookup = build_player_lookup(db_players)
        exact_player_lookup = build_exact_player_lookup(db_players)
        player_id_lookup = build_player_id_lookup(db_players)
        matched_player_ids: set[str] = set()
        matched_players: list[str] = []
        unmatched_players: list[str] = []
        score_rows: list[dict[str, Any]] = []
        status_candidates: list[dict[str, Any]] = []
        live_snapshots: list[live_feed.LiveSnapshot] = []
        logged_score_sample = False

        for record in records:
            datagolf_name = extract_player_name(record)
            if not datagolf_name:
                continue

            db_player = match_database_player(
                datagolf_name,
                player_lookup,
                datagolf_id=extract_datagolf_player_id(record),
                player_id_lookup=player_id_lookup,
                exact_player_lookup=exact_player_lookup,
            )
            if db_player is None:
                unmatched_players.append(datagolf_name)
                logger.warning("Unmatched DataGolf player: %s", datagolf_name)
                continue

            matched_player_ids.add(db_player["id"])
            matched_players.append(db_player["name"])
            if not logged_score_sample:
                logger.info(
                    "DataGolf matched score sample: %s",
                    score_log_sample(record),
                )
                logged_score_sample = True
            if str(db_player["id"]) in selected_player_ids:
                snapshot = extract_live_snapshot(
                    record,
                    db_player,
                    current_round=current_round,
                    source_updated_at=source_updated_at,
                )
                if snapshot is not None:
                    live_snapshots.append(snapshot)
            round_scores = extract_round_scores(
                record,
                current_round=current_round,
                course_par=course_par,
            )
            for round_num, strokes in round_scores.items():
                score_rows.append(
                    {
                        "player_id": db_player["id"],
                        "round": round_num,
                        "strokes": strokes,
                        "source": "DATAGOLF",
                        "is_official": True,
                        "updated_at": synced_at.isoformat(),
                    }
                )

            status = extract_player_status(record)
            effective_round = 3 if status == "CUT" else current_round
            if status and effective_round is not None:
                status_candidates.append(
                    {
                        "player_id": db_player["id"],
                        "effective_round": effective_round,
                        "status": status,
                        "source": "DATAGOLF",
                        "note": f"Explicit DataGolf status during verified event {event_name}",
                    }
                )

        if not score_rows and not status_candidates and not live_snapshots:
            return SyncResult(
                success=False,
                synced_at=synced_at,
                matched_players=sorted(set(matched_players)),
                unmatched_players=sorted(set(unmatched_players)),
                event_name=event_name,
                expected_event_name=expected_event_name,
                error=(
                    "No round scores were available to sync from DataGolf. "
                    f"{ABORTED_NO_WRITE_MSG}"
                ),
            )

        if score_rows:
            client.table("scores").upsert(score_rows, on_conflict="player_id,round").execute()

        status_rows: list[dict[str, Any]] = []
        if status_candidates:
            existing_events = fetch_player_status_events(client, tournament_id)
            latest_by_player: dict[str, tuple[str, int]] = {}
            for event in existing_events:
                latest_by_player[event["player_id"]] = (
                    str(event["status"]).upper(),
                    int(event["effective_round"]),
                )
            for candidate in status_candidates:
                signature = (candidate["status"], int(candidate["effective_round"]))
                if latest_by_player.get(candidate["player_id"]) != signature:
                    status_rows.append(candidate)
                    latest_by_player[candidate["player_id"]] = signature
            if status_rows:
                client.table("player_status_events").insert(status_rows).execute()

        live_events_written = 0
        live_feed_warning = None
        try:
            live_events_written = persist_live_feed_transitions(
                client,
                tournament_id,
                live_snapshots,
            )
        except Exception as exc:
            # Keep the established score sync operational while the additive
            # live-feed migration is waiting to be installed.
            logger.warning("Live feed persistence unavailable: %s", exc)
            live_feed_warning = (
                "Scores were synchronized, but the live-feed tables are not available yet. "
                "Run migrations/003_live_feed.sql in Supabase."
            )

        return SyncResult(
            success=True,
            synced_at=synced_at,
            players_updated=len(matched_player_ids),
            scores_written=len(score_rows),
            statuses_written=len(status_rows),
            live_events_written=live_events_written,
            matched_players=sorted(set(matched_players)),
            unmatched_players=sorted(set(unmatched_players)),
            event_name=event_name,
            expected_event_name=expected_event_name,
            warning=live_feed_warning,
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


def run_name_matching_test() -> dict[str, Any]:
    sample_players = [
        {"id": "1", "name": "Scottie Scheffler", "tier": 1},
        {"id": "2", "name": "Si woo Kim", "tier": 3},
        {"id": "3", "name": "Adam scott", "tier": 6},
        {"id": "4", "name": "Justin Rose ", "tier": 4},
        {"id": "5", "name": "Cam Smith", "tier": 2},
    ]
    lookup = build_player_lookup(sample_players)
    checks = [
        ("Scheffler, Scottie", True),
        ("Kim, Si-Woo", True),
        ("Scott, Adam", True),
        ("Rose, Justin", True),
        ("Cameron Smith", True),
        ("Rahm, Jon", False),
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
    event_name = extract_event_name(payload)
    current_round = extract_current_round(payload)
    course_par = resolve_course_par(records, event_name)
    sample = records[0] if records else {}
    players_with_scores = sum(
        1
        for record in records
        if extract_round_scores(
            record,
            current_round=current_round,
            course_par=course_par,
        )
    )
    return {
        "event_name": event_name,
        "records_found": len(records),
        "players_with_round_scores": players_with_scores,
        "sample_fields": sorted(sample.keys()) if sample else [],
        "sample_round_scores": extract_round_scores(
            sample,
            current_round=current_round,
            course_par=course_par,
        )
        if sample
        else {},
    }
