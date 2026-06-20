"""CLI for DataGolf live score sync."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from supabase import create_client

from lib.datagolf_sync import (
    DataGolfRateLimitError,
    VERIFY_SAMPLE_PLAYERS,
    analyze_live_score_records,
    clear_all_scores,
    execute_sync,
    extract_current_round,
    extract_event_name,
    extract_player_records,
    fetch_live_tournament_data,
    fetch_player_scores_from_db,
    get_api_key_from_mapping,
    preview_sync_scores,
    run_auto_sync_interval_test,
    run_cumulative_delta_test,
    run_field_import_test,
    run_live_round_test,
    run_name_matching_test,
    run_rate_limit_test,
    verify_round_score_mapping,
)

SECRETS_PATH = Path(".streamlit/secrets.toml")


def load_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Secrets file not found: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return {key: str(value) for key, value in data.items()}


def get_supabase_key(secrets: dict[str, str]) -> str:
    for name in ("SUPABASE_ANON_KEY", "SUPABASE_KEY", "sb_publishable_key"):
        value = secrets.get(name, "").strip()
        if value:
            return value
    return ""


def fmt_round_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        cleaned = value.strip().upper()
        if not cleaned or cleaned == "-":
            return "-"
        if cleaned in {"E", "EVEN"}:
            return "E"
        return value
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric == 0:
        return "E"
    return f"{numeric:+d}" if numeric > 0 else str(numeric)


def print_live_sync_debug(analysis: dict[str, Any], event_name: str | None) -> None:
    print("\nLive sync debug:")
    print(f"  Event: {event_name}")
    print(f"  Records: {analysis['record_count']}")
    print(f"  With R3 field populated: {analysis['with_r3_field']}")
    print(f"  With live today/current score: {analysis['with_live_today']}")
    print(f"  Parsed round_no=3 scores: {analysis['with_round_no_3_parsed']}")
    print("\nSample players (10):")
    for row in analysis["sample_players"]:
        print(f"  {row['player_name']}:")
        print(
            f"    R1={fmt_round_value(row.get('R1'))} R2={fmt_round_value(row.get('R2'))} "
            f"R3={fmt_round_value(row.get('R3'))} R4={fmt_round_value(row.get('R4'))} "
            f"today={fmt_round_value(row.get('today'))} current={fmt_round_value(row.get('current_score'))} "
            f"thru={row.get('thru')} tee_time={row.get('tee_time')} round={row.get('round')}"
        )
        parsed = row.get("parsed_rounds", {})
        if parsed:
            written = ", ".join(
                f"round_no {round_no}={fmt_round_value(score)}"
                for round_no, score in sorted(parsed.items())
            )
            print(f"    Parsed writes: {written}")
        else:
            print("    Parsed writes: none")


def print_player_mapping(players: list[dict[str, Any]], title: str) -> None:
    print(title)
    for row in players:
        print(f"\n{row['target_name']}:")
        if not row.get("found"):
            print("  Not found in DataGolf response")
            continue
        print(f"  DataGolf name: {row['datagolf_name']}")
        raw = row.get("raw_rounds", {})
        print(
            "  DataGolf rounds: "
            f"R1={fmt_round_value(raw.get('R1'))}, "
            f"R2={fmt_round_value(raw.get('R2'))}, "
            f"R3={fmt_round_value(raw.get('R3'))}, "
            f"R4={fmt_round_value(raw.get('R4'))}"
        )
        writes = row.get("supabase_writes", {})
        if writes:
            written = ", ".join(
                f"round_no {round_no}={fmt_round_value(score)}"
                for round_no, score in sorted(writes.items())
            )
            print(f"  Supabase writes: {written}")
        else:
            print("  Supabase writes: none")


def run_test(secrets: dict[str, str]) -> int:
    print("DataGolf sync test")
    print("=" * 40)

    matching = run_name_matching_test()
    print("Name matching:")
    for check in matching["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(
            f"  [{status}] {check['datagolf_name']!r} -> "
            f"{check.get('matched_name', 'no match')!r}"
        )
    if not matching["passed"]:
        print("Name matching test failed.")
        return 1
    print("Name matching test passed.")

    cumulative = run_cumulative_delta_test()
    live_round = run_live_round_test()
    print("\nRound score mapping tests:")
    for check in cumulative["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        print(f"         expected={check['expected']} actual={check['actual']}")
    for check in live_round["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        print(f"         expected={check['expected']} actual={check['actual']}")
    if not cumulative["passed"] or not live_round["passed"]:
        print("Round score mapping tests failed.")
        return 1
    print("Round score mapping tests passed.")

    field_import = run_field_import_test()
    print("\nField import tests:")
    for check in field_import["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        print(f"         expected={check['expected']} actual={check['actual']}")
    if not field_import["passed"]:
        print("Field import tests failed.")
        return 1
    print("Field import tests passed.")

    rate_limit = run_rate_limit_test()
    print("\nRate limit / backoff tests:")
    for check in rate_limit["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        print(f"         expected={check['expected']} actual={check['actual']}")
    if not rate_limit["passed"]:
        print("Rate limit tests failed.")
        return 1
    print("Rate limit tests passed.")

    auto_sync_interval = run_auto_sync_interval_test()
    print("\nAuto-sync interval tests:")
    for check in auto_sync_interval["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        print(f"         expected={check['expected']} actual={check['actual']}")
    if not auto_sync_interval["passed"]:
        print("Auto-sync interval tests failed.")
        return 1
    print("Auto-sync interval tests passed.")

    api_key = get_api_key_from_mapping(secrets)
    if not api_key:
        print("DATA_GOLF_API_KEY is not configured. Skipping live preview.")
        return 0

    try:
        verification = verify_round_score_mapping(api_key=api_key, use_backoff=False)
    except DataGolfRateLimitError as exc:
        print("\nLive mapping verification skipped: DataGolf HTTP 429.")
        print(f"  {exc}")
        return 0

    print(f"\nLive mapping verification ({verification['event_name']}):")
    print_player_mapping(verification["players"], "Sample players:")

    try:
        preview = preview_sync_scores(api_key=api_key, use_backoff=False)
    except DataGolfRateLimitError as exc:
        print("\nLive score preview skipped: DataGolf HTTP 429.")
        print(f"  {exc}")
        return 0

    print("\nLive score preview (relative to par):")
    print(f"  Event: {preview['event_name']}")
    print(f"  Records found: {preview['records_found']}")
    print(f"  Parsed round scores: {preview['parsed_score_count']}")
    print("\nSample players (10):")
    for row in preview["sample_players"]:
        rounds = ", ".join(f"R{r}={v:+d}" if v > 0 else (f"R{r}={v}" if v < 0 else f"R{r}=E") for r, v in sorted(row["round_scores"].items()))
        print(f"  {row['datagolf_name']} -> {row['db_name'] or 'UNMATCHED'} | {rounds or 'no rounds'}")
    return 0


def run_sync(secrets: dict[str, str], clear_first: bool = False) -> int:
    url = secrets.get("SUPABASE_URL", "").strip()
    key = get_supabase_key(secrets)
    api_key = get_api_key_from_mapping(secrets)
    if not api_key:
        print("DATA_GOLF_API_KEY is not configured.")
        return 1
    if not url or not key:
        print("Supabase credentials are not configured.")
        return 1

    client = create_client(url, key)

    try:
        payload = fetch_live_tournament_data(api_key=api_key, use_backoff=True)
        records = extract_player_records(payload)
        event_name = extract_event_name(payload)
        event_round = extract_current_round(payload)
        analysis = analyze_live_score_records(records, event_round)
        print_live_sync_debug(analysis, event_name)

        verification = verify_round_score_mapping(api_key=api_key, use_backoff=False)
        print("\nMapping verification before sync:")
        print_player_mapping(verification["players"], "Sample players:")
    except DataGolfRateLimitError as exc:
        print(f"Warning: could not fetch live preview before sync: {exc}")

    if clear_first:
        removed = clear_all_scores(client)
        print(f"\nCleared {removed} existing score rows from Supabase.")

    result = execute_sync(client, secrets)

    print(f"\nSuccess: {result.success}")
    print(f"Synced at: {result.synced_at.isoformat()}")
    print(f"Event: {result.event_name}")
    print(f"Players updated: {result.players_updated}")
    print(f"Scores written: {result.scores_written}")
    round_3_written = sum(
        1
        for row in result.sample_writes
        for round_no in row.get("round_scores", {})
        if round_no == 3
    )
    if result.success:
        print(f"Round 3 scores in sample writes: {round_3_written}")
    print(f"Matched players: {len(result.matched_players)}")
    print(f"Unmatched players: {len(result.unmatched_players)}")
    if result.last_successful_sync:
        print(f"Last successful sync: {result.last_successful_sync.isoformat()}")
    if result.auto_sync_suspended:
        print("Auto-sync suspended: yes")

    if result.matched_players:
        print("\nMatched players:")
        for name in result.matched_players:
            print(f"  - {name}")

    if result.unmatched_players:
        print("\nUnmatched players:")
        for name in result.unmatched_players[:20]:
            print(f"  - {name}")
        if len(result.unmatched_players) > 20:
            print(f"  ... and {len(result.unmatched_players) - 20} more")

    print("\nSample scores written (10):")
    for row in result.sample_writes:
        rounds = ", ".join(
            f"R{r}={v:+d}" if v > 0 else (f"R{r}={v}" if v < 0 else f"R{r}=E")
            for r, v in sorted(row["round_scores"].items())
        )
        print(f"  {row['player_name']}: {rounds}")

    if result.warning:
        print(f"\nWarning: {result.warning}")
        return 1
    if result.error:
        print(f"\nError: {result.error}")
        return 1

    if result.success:
        db_scores = fetch_player_scores_from_db(client, VERIFY_SAMPLE_PLAYERS)
        print("\nSupabase scores after sync:")
        for player_name in VERIFY_SAMPLE_PLAYERS:
            scores = db_scores.get(player_name, {})
            if not scores:
                print(f"  {player_name}: no scores stored")
                continue
            written = ", ".join(
                f"round_no {round_no}={fmt_round_value(score)}"
                for round_no, score in sorted(scores.items())
            )
            print(f"  {player_name}: {written}")

        print("\nScores by round (SQL equivalent):")
        response = client.table("scores").select("round_no").execute()
        from collections import Counter

        counts = Counter(int(row["round_no"]) for row in response.data or [])
        for round_no in sorted(counts):
            print(f"  Round {round_no}: {counts[round_no]} scores")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DataGolf live scoring sync")
    parser.add_argument("--test", action="store_true", help="Run matching and score preview tests")
    parser.add_argument("--sync", action="store_true", help="Sync live scores into Supabase")
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Clear all existing scores before syncing",
    )
    args = parser.parse_args()

    if not args.test and not args.sync:
        parser.error("Specify --test or --sync")

    secrets = load_secrets(SECRETS_PATH)
    if args.test:
        return run_test(secrets)
    return run_sync(secrets, clear_first=args.clear_first)


if __name__ == "__main__":
    sys.exit(main())
