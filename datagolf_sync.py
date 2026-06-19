"""CLI for DataGolf live score sync."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from supabase import create_client

from lib.datagolf_sync import (
    execute_sync,
    get_api_key_from_mapping,
    preview_sync_scores,
    run_cumulative_delta_test,
    run_field_import_test,
    run_name_matching_test,
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
    print("\nCumulative-to-delta tests:")
    for check in cumulative["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {check['name']}")
        print(f"         expected={check['expected']} actual={check['actual']}")
    if not cumulative["passed"]:
        print("Cumulative-to-delta tests failed.")
        return 1
    print("Cumulative-to-delta tests passed.")

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

    api_key = get_api_key_from_mapping(secrets)
    if not api_key:
        print("DATA_GOLF_API_KEY is not configured. Skipping live preview.")
        return 0

    preview = preview_sync_scores(api_key=api_key)
    print("\nLive score preview (relative to par):")
    print(f"  Event: {preview['event_name']}")
    print(f"  Records found: {preview['records_found']}")
    print(f"  Parsed round scores: {preview['parsed_score_count']}")
    print("\nSample players (10):")
    for row in preview["sample_players"]:
        rounds = ", ".join(f"R{r}={v:+d}" if v > 0 else (f"R{r}={v}" if v < 0 else f"R{r}=E") for r, v in sorted(row["round_scores"].items()))
        print(f"  {row['datagolf_name']} -> {row['db_name'] or 'UNMATCHED'} | {rounds or 'no rounds'}")
    return 0


def run_sync(secrets: dict[str, str]) -> int:
    url = secrets.get("SUPABASE_URL", "").strip()
    key = get_supabase_key(secrets)
    if not get_api_key_from_mapping(secrets):
        print("DATA_GOLF_API_KEY is not configured.")
        return 1
    if not url or not key:
        print("Supabase credentials are not configured.")
        return 1

    client = create_client(url, key)
    result = execute_sync(client, secrets)

    print(f"Success: {result.success}")
    print(f"Synced at: {result.synced_at.isoformat()}")
    print(f"Event: {result.event_name}")
    print(f"Players updated: {result.players_updated}")
    print(f"Scores written: {result.scores_written}")
    print(f"Matched players: {len(result.matched_players)}")
    print(f"Unmatched players: {len(result.unmatched_players)}")

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

    if result.error:
        print(f"\nError: {result.error}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DataGolf live scoring sync")
    parser.add_argument("--test", action="store_true", help="Run matching and score preview tests")
    parser.add_argument("--sync", action="store_true", help="Sync live scores into Supabase")
    args = parser.parse_args()

    if not args.test and not args.sync:
        parser.error("Specify --test or --sync")

    secrets = load_secrets(SECRETS_PATH)
    if args.test:
        return run_test(secrets)
    return run_sync(secrets)


if __name__ == "__main__":
    sys.exit(main())
