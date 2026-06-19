"""Load roster data from the Excel workbook into Supabase."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from lib.db import get_supabase_client_from_config
from lib.excel_import import import_workbook, parse_workbook

DEFAULT_EXCEL = Path("data/US Open 2026 - Resultater.xlsx")
SECRETS_PATH = Path(".streamlit/secrets.toml")


def load_secrets(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Secrets file not found: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return {
        "SUPABASE_URL": data.get("SUPABASE_URL", ""),
        "SUPABASE_ANON_KEY": data.get("SUPABASE_ANON_KEY", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import US Open 2026 fantasy golf data.")
    parser.add_argument(
        "excel_path",
        nargs="?",
        default=str(DEFAULT_EXCEL),
        help="Path to the Excel workbook",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the workbook without writing to Supabase",
    )
    args = parser.parse_args()

    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(f"Excel file not found: {excel_path}")
        return 1

    parsed = parse_workbook(excel_path)
    print(f"Teams: {len(parsed.teams)}")
    print(f"Players: {len(parsed.players)}")
    print("Roster counts:")
    for team_name, count in parsed.team_roster_counts.items():
        print(f"  {team_name}: {count}")

    if args.dry_run:
        print("Dry run complete.")
        return 0

    secrets = load_secrets(SECRETS_PATH)
    if not secrets["SUPABASE_URL"] or not secrets["SUPABASE_ANON_KEY"]:
        print("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .streamlit/secrets.toml")
        return 1

    client = get_supabase_client_from_config(
        secrets["SUPABASE_URL"],
        secrets["SUPABASE_ANON_KEY"],
    )
    result = import_workbook(client, excel_path)
    print("Import complete:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
