"""CLI for DataGolf live score sync."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from lib.datagolf_sync import (
    execute_sync,
    get_api_key_from_mapping,
    run_api_test,
    run_name_matching_test,
)

SECRETS_PATH = Path(".streamlit/secrets.toml")


def load_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Secrets file not found: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return {key: str(value) for key, value in data.items()}


def run_test(secrets: dict[str, str]) -> int:
    print("DataGolf sync test")
    print("=" * 40)

    matching = run_name_matching_test()
    print("Name matching:")
    for check in matching["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(
            f"  [{status}] {check['datagolf_name']!r} "
            f"(expected={check['expected_match']}, actual={check['actual_match']})"
        )
    if not matching["passed"]:
        print("Name matching test failed.")
        return 1
    print("Name matching test passed.")

    api_key = get_api_key_from_mapping(secrets)
    if not api_key:
        print("DATA_GOLF_API_KEY is not configured. Skipping live API test.")
        return 0

    try:
        api_result = run_api_test(api_key=api_key)
    except Exception as exc:
        print(f"Live API test failed: {exc}")
        return 1

    print("Live API test:")
    print(f"  Event: {api_result['event_name']}")
    print(f"  Records found: {api_result['records_found']}")
    print(f"  Players with round scores: {api_result['players_with_round_scores']}")
    print(f"  Sample fields: {', '.join(api_result['sample_fields'][:12])}")
    print(f"  Sample round scores: {api_result['sample_round_scores']}")
    return 0


def run_sync(secrets: dict[str, str]) -> int:
    result = execute_sync(secrets)

    print(f"Success: {result.success}")
    print(f"Synced at: {result.synced_at.isoformat()}")
    print(f"Event: {result.event_name}")
    print(f"Players updated: {result.players_updated}")
    print(f"Scores written: {result.scores_written}")
    print(f"Unmatched players: {len(result.unmatched_players)}")
    if result.unmatched_players:
        for name in result.unmatched_players[:10]:
            print(f"  - {name}")
    if result.error:
        print(f"Error: {result.error}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DataGolf live scoring sync")
    parser.add_argument("--test", action="store_true", help="Run connectivity and matching tests")
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
