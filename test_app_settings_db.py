"""Live Supabase probe for app_settings (select + upsert)."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from supabase import create_client

from lib import app_settings


def load_client():
    secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        raise SystemExit(f"Missing secrets file: {secrets_path}")
    with secrets_path.open("rb") as handle:
        secrets = tomllib.load(handle)
    url = secrets.get("SUPABASE_URL", "").strip()
    key = secrets.get("SUPABASE_ANON_KEY", secrets.get("SUPABASE_KEY", "")).strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_ANON_KEY required in secrets.toml")
    return create_client(url, key)


def main() -> int:
    client = load_client()
    probe = app_settings.probe_app_settings(client)
    read_result = app_settings.get_auto_sync_setting(client)

    print("=== select * from app_settings ===")
    if probe.select_ok:
        print("OK:", probe.select_rows)
    else:
        print("ERROR:", probe.select_error)

    print("\n=== upsert auto_sync_enabled=true ===")
    if probe.upsert_ok:
        print("OK")
    else:
        print("ERROR:", probe.upsert_error)

    print("\n=== get_auto_sync_setting() ===")
    if read_result.error:
        print("ERROR:", read_result.error)
    else:
        print("value:", read_result.value)

    if probe.select_ok and probe.upsert_ok and not read_result.error:
        print("\nAll app_settings checks passed.")
        return 0

    print("\nOne or more app_settings checks failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
