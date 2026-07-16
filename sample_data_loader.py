"""Load roster data from an Excel workbook into Supabase."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from lib.excel_import import import_workbook, parse_workbook

SECRETS_PATH = Path(".streamlit/secrets.toml")
DEFAULT_EXCEL_PATH = Path("data/The Open 2026 - Resultater.xlsx")


def load_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Secrets file not found: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return {
        "SUPABASE_URL": data.get("SUPABASE_URL", ""),
        "SUPABASE_SERVICE_ROLE_KEY": data.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    }


def default_excel_for_active_tournament(client) -> Path | None:
    from lib.db import get_active_tournament

    tournament = get_active_tournament(client)
    if tournament is None:
        return None
    return Path("data") / f"{tournament['name']} - Resultater.xlsx"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import fantasy golf roster data for the active tournament.")
    parser.add_argument(
        "excel_path",
        nargs="?",
        default=None,
        help="Path to the Excel workbook (defaults to data/<active tournament name> - Resultater.xlsx)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the workbook without writing to Supabase",
    )
    args = parser.parse_args()

    if args.dry_run:
        excel_path = Path(args.excel_path) if args.excel_path else DEFAULT_EXCEL_PATH
        if not excel_path.exists():
            print(f"Excel file not found: {excel_path}")
            return 1
        parsed = parse_workbook(excel_path)
        print(f"Workbook: {excel_path}")
        print(f"Teams: {len(parsed.teams)}")
        print(f"Players: {len(parsed.players)}")
        print("Roster counts:")
        for team_name, count in parsed.team_roster_counts.items():
            print(f"  {team_name}: {count}")
        print("Dry run complete. No Supabase connection was made.")
        return 0

    secrets = load_secrets(SECRETS_PATH)
    if not secrets["SUPABASE_URL"] or not secrets["SUPABASE_SERVICE_ROLE_KEY"]:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .streamlit/secrets.toml")
        return 1

    from lib.db import get_active_tournament, get_supabase_client_from_config, tournament_display_title

    client = get_supabase_client_from_config(
        secrets["SUPABASE_URL"],
        secrets["SUPABASE_SERVICE_ROLE_KEY"],
    )
    tournament = get_active_tournament(client)
    if tournament is None:
        print("No active tournament found in tournaments table.")
        return 1

    excel_path = Path(args.excel_path) if args.excel_path else default_excel_for_active_tournament(client)
    if excel_path is None or not excel_path.exists():
        print(f"Excel file not found: {excel_path}")
        return 1

    print(f"Active tournament: {tournament_display_title(tournament)}")
    parsed = parse_workbook(excel_path)
    print(f"Teams: {len(parsed.teams)}")
    print(f"Players: {len(parsed.players)}")
    print("Roster counts:")
    for team_name, count in parsed.team_roster_counts.items():
        print(f"  {team_name}: {count}")

    result = import_workbook(client, excel_path)
    print("Import complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
