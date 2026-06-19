"""DataGolf live scoring sync for golf_konk Supabase schema."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from supabase import Client

logger = logging.getLogger(__name__)

ABORTED_NO_WRITE_MSG = "Existing scores were not modified."
RATE_LIMIT_BACKOFF_SECONDS = [30, 60, 120]
MAX_CONSECUTIVE_RATE_LIMITS = 3
SYNC_LOG_STATUSES = ("success", "error", "rate_limited")


class DataGolfRateLimitError(RuntimeError):
    """Raised when DataGolf returns HTTP 429."""

    def __init__(self, message: str, retry_count: int = 0) -> None:
        super().__init__(message)
        self.retry_count = retry_count


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
    warning: str | None = None
    rate_limited: bool = False
    last_successful_sync: datetime | None = None
    auto_sync_suspended: bool = False
    retry_count: int = 0


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


def fetch_live_tournament_data(
    api_key: str,
    tour: str = DEFAULT_TOUR,
    use_backoff: bool = True,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("DATA_GOLF_API_KEY is not configured.")

    sleeper = sleep_fn or time.sleep
    retry_count = 0
    max_attempts = len(RATE_LIMIT_BACKOFF_SECONDS) + 1 if use_backoff else 1

    for attempt in range(max_attempts):
        try:
            return _fetch_live_tournament_data_once(api_key=api_key, tour=tour)
        except DataGolfRateLimitError as exc:
            retry_count = attempt + 1
            if use_backoff and attempt < len(RATE_LIMIT_BACKOFF_SECONDS):
                logger.warning(
                    "DataGolf HTTP 429 on attempt %s, retrying in %ss",
                    retry_count,
                    RATE_LIMIT_BACKOFF_SECONDS[attempt],
                )
                sleeper(RATE_LIMIT_BACKOFF_SECONDS[attempt])
                continue
            raise DataGolfRateLimitError(
                f"DataGolf API rate limited (HTTP 429) after {retry_count} attempt(s). "
                f"{ABORTED_NO_WRITE_MSG}",
                retry_count=retry_count,
            ) from exc

    raise RuntimeError("DataGolf fetch failed unexpectedly.")


def _fetch_live_tournament_data_once(api_key: str, tour: str = DEFAULT_TOUR) -> dict[str, Any]:
    url = build_in_play_url(api_key, tour=tour)
    try:
        with urlopen(url, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        if exc.code == 429:
            raise DataGolfRateLimitError(
                f"DataGolf API rate limited (HTTP 429). {ABORTED_NO_WRITE_MSG}",
                retry_count=0,
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


def parse_sync_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def log_sync_event(
    client: Client | None,
    status: str,
    message: str,
    http_status: int | None = None,
    scores_written: int = 0,
    retry_count: int = 0,
) -> None:
    if client is None or status not in SYNC_LOG_STATUSES:
        return
    try:
        client.table("sync_log").insert(
            {
                "status": status,
                "http_status": http_status,
                "message": message,
                "scores_written": scores_written,
                "retry_count": retry_count,
            }
        ).execute()
    except Exception as exc:
        logger.warning("Could not write sync_log: %s", exc)


AUTO_SYNC_INTERVAL = timedelta(minutes=5)


def get_last_successful_sync(client: Client | None) -> datetime | None:
    if client is None:
        return None
    try:
        response = (
            client.table("sync_log")
            .select("created_at")
            .eq("status", "success")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return parse_sync_timestamp(response.data[0]["created_at"])
    except Exception as exc:
        logger.warning("Could not read last successful sync: %s", exc)
    return None


def get_last_sync_attempt(client: Client | None) -> datetime | None:
    if client is None:
        return None
    try:
        response = (
            client.table("sync_log")
            .select("created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return parse_sync_timestamp(response.data[0]["created_at"])
    except Exception as exc:
        logger.warning("Could not read last sync attempt: %s", exc)
    return None


def is_auto_sync_due(
    client: Client | None,
    last_attempt: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    reference = last_attempt if last_attempt is not None else get_last_sync_attempt(client)
    if reference is None:
        return True
    current = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return current - reference >= AUTO_SYNC_INTERVAL


def count_consecutive_rate_limits(client: Client | None) -> int:
    if client is None:
        return 0
    try:
        response = (
            client.table("sync_log")
            .select("status")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        count = 0
        for row in response.data or []:
            if row.get("status") == "rate_limited":
                count += 1
            else:
                break
        return count
    except Exception as exc:
        logger.warning("Could not read sync_log for rate limits: %s", exc)
        return 0


def is_auto_sync_suspended(client: Client | None) -> bool:
    return count_consecutive_rate_limits(client) >= MAX_CONSECUTIVE_RATE_LIMITS


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


def preview_sync_scores(
    api_key: str,
    tour: str = DEFAULT_TOUR,
    use_backoff: bool = False,
) -> dict[str, Any]:
    payload = fetch_live_tournament_data(api_key=api_key, tour=tour, use_backoff=use_backoff)
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
    use_backoff: bool = True,
) -> SyncResult:
    synced_at = datetime.now(timezone.utc)

    try:
        payload = fetch_live_tournament_data(
            api_key=api_key,
            tour=tour,
            use_backoff=use_backoff,
        )
        records = extract_player_records(payload)
        event_round = extract_current_round(payload)
        event_name = extract_event_name(payload)

        if not records:
            result = SyncResult(
                success=False,
                synced_at=synced_at,
                event_name=event_name,
                error=(
                    "DataGolf response did not contain any player records. "
                    f"{ABORTED_NO_WRITE_MSG}"
                ),
            )
            log_sync_event(client, "error", result.error or "No player records")
            return finalize_sync_result(client, result)

        db_players = fetch_players(client)
        player_lookup = build_player_lookup(db_players)
        score_rows, matched_players, unmatched_players, player_round_scores = build_score_updates(
            records,
            player_lookup,
            event_round,
        )

        if not score_rows:
            result = SyncResult(
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
            log_sync_event(client, "error", result.error or "No valid scores")
            return finalize_sync_result(client, result)

        client.table("scores").upsert(score_rows, on_conflict="player_id,round_no").execute()

        matched_player_ids = {row["player_id"] for row in score_rows}
        sample_writes = [
            {
                "player_name": player_name,
                "round_scores": player_round_scores[player_name],
            }
            for player_name in sorted(player_round_scores.keys())[:10]
        ]

        result = SyncResult(
            success=True,
            synced_at=synced_at,
            players_updated=len(matched_player_ids),
            scores_written=len(score_rows),
            matched_players=sorted(set(matched_players)),
            unmatched_players=sorted(set(unmatched_players)),
            sample_writes=sample_writes,
            event_name=event_name,
        )
        log_sync_event(
            client,
            "success",
            f"Synced {len(score_rows)} scores for {len(matched_player_ids)} players.",
            scores_written=len(score_rows),
        )
        result.last_successful_sync = synced_at
        return finalize_sync_result(client, result)
    except DataGolfRateLimitError as exc:
        logger.warning("DataGolf sync aborted due to rate limit")
        warning = (
            f"DataGolf API rate limited (HTTP 429). {ABORTED_NO_WRITE_MSG} "
            f"Prøvde {exc.retry_count} gang(er)"
            + (
                f" med backoff ({', '.join(str(s) for s in RATE_LIMIT_BACKOFF_SECONDS)} sek)."
                if use_backoff
                else "."
            )
        )
        result = SyncResult(
            success=False,
            synced_at=synced_at,
            warning=warning,
            rate_limited=True,
            retry_count=exc.retry_count,
        )
        log_sync_event(
            client,
            "rate_limited",
            warning,
            http_status=429,
            retry_count=exc.retry_count,
        )
        return finalize_sync_result(client, result)
    except Exception as exc:
        logger.exception("DataGolf sync failed")
        message = str(exc)
        if ABORTED_NO_WRITE_MSG not in message:
            message = f"{message} {ABORTED_NO_WRITE_MSG}"
        result = SyncResult(
            success=False,
            synced_at=synced_at,
            error=message,
        )
        log_sync_event(client, "error", message)
        return finalize_sync_result(client, result)


def finalize_sync_result(client: Client | None, result: SyncResult) -> SyncResult:
    if result.success:
        if result.last_successful_sync is None:
            result.last_successful_sync = result.synced_at
    else:
        result.last_successful_sync = get_last_successful_sync(client)
    result.auto_sync_suspended = is_auto_sync_suspended(client)
    return result


def execute_sync(
    client: Client,
    secrets: dict[str, Any],
    tour: str = DEFAULT_TOUR,
    use_backoff: bool = True,
) -> SyncResult:
    synced_at = datetime.now(timezone.utc)
    api_key = get_api_key_from_mapping(secrets)
    if not api_key:
        return finalize_sync_result(
            client,
            SyncResult(
                success=False,
                synced_at=synced_at,
                error="DATA_GOLF_API_KEY is not configured.",
            ),
        )
    if client is None:
        return finalize_sync_result(
            client,
            SyncResult(
                success=False,
                synced_at=synced_at,
                error="Supabase client is not configured.",
            ),
        )
    if use_backoff is False and is_auto_sync_suspended(client):
        return finalize_sync_result(
            client,
            SyncResult(
                success=False,
                synced_at=synced_at,
                warning=(
                    "Auto-sync er midlertidig deaktivert etter 3 påfølgende HTTP 429-svar fra DataGolf. "
                    f"{ABORTED_NO_WRITE_MSG}"
                ),
                rate_limited=True,
            ),
        )
    return sync_live_scores(client, api_key=api_key, tour=tour, use_backoff=use_backoff)


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


def run_rate_limit_test() -> dict[str, Any]:
    global _fetch_live_tournament_data_once

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def always_429(api_key: str, tour: str = DEFAULT_TOUR) -> dict[str, Any]:
        raise DataGolfRateLimitError("HTTP 429", retry_count=0)

    original_fetch = _fetch_live_tournament_data_once
    _fetch_live_tournament_data_once = always_429
    raised = False
    retry_count = 0
    try:
        try:
            fetch_live_tournament_data("test-key", use_backoff=True, sleep_fn=fake_sleep)
        except DataGolfRateLimitError as exc:
            raised = True
            retry_count = exc.retry_count
    finally:
        _fetch_live_tournament_data_once = original_fetch

    checks = [
        {
            "name": "Backoff sleeps 30, 60, 120",
            "expected": [30.0, 60.0, 120.0],
            "actual": sleeps,
            "passed": sleeps == [30.0, 60.0, 120.0],
        },
        {
            "name": "Raises after final 429",
            "expected": True,
            "actual": raised,
            "passed": raised,
        },
        {
            "name": "Retry count after 4 attempts",
            "expected": 4,
            "actual": retry_count,
            "passed": raised and retry_count == 4,
        },
        {
            "name": "Consecutive rate limit counter",
            "expected": 3,
            "actual": _count_consecutive_from_rows(
                [
                    {"status": "rate_limited"},
                    {"status": "rate_limited"},
                    {"status": "rate_limited"},
                    {"status": "success"},
                ]
            ),
            "passed": _count_consecutive_from_rows(
                [
                    {"status": "rate_limited"},
                    {"status": "rate_limited"},
                    {"status": "rate_limited"},
                    {"status": "success"},
                ]
            )
            == 3,
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def _count_consecutive_from_rows(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        if row.get("status") == "rate_limited":
            count += 1
        else:
            break
    return count


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


def run_auto_sync_interval_test() -> dict[str, Any]:
    now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
    recent = now - timedelta(minutes=2)
    due = now - timedelta(minutes=6)
    checks = [
        {
            "name": "Sync due when no prior attempt",
            "expected": True,
            "actual": is_auto_sync_due(None, last_attempt=None, now=now),
            "passed": is_auto_sync_due(None, last_attempt=None, now=now),
        },
        {
            "name": "Sync not due within 5 minutes",
            "expected": False,
            "actual": is_auto_sync_due(None, last_attempt=recent, now=now),
            "passed": not is_auto_sync_due(None, last_attempt=recent, now=now),
        },
        {
            "name": "Sync due after 5 minutes",
            "expected": True,
            "actual": is_auto_sync_due(None, last_attempt=due, now=now),
            "passed": is_auto_sync_due(None, last_attempt=due, now=now),
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }
