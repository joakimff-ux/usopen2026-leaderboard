"""Persistent app settings stored in Supabase."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from supabase import Client

logger = logging.getLogger(__name__)

AUTO_SYNC_ENABLED_KEY = "auto_sync_enabled"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_setting(client: Client | None, key: str) -> str | None:
    if client is None:
        return None
    try:
        response = client.table("app_settings").select("value").eq("key", key).limit(1).execute()
        if response.data:
            return str(response.data[0]["value"])
    except Exception as exc:
        logger.warning("Could not read app setting %s: %s", key, exc)
    return None


def set_setting(client: Client | None, key: str, value: str) -> bool:
    if client is None:
        return False
    try:
        client.table("app_settings").upsert(
            {"key": key, "value": value, "updated_at": _now_iso()},
            on_conflict="key",
        ).execute()
        return True
    except Exception as exc:
        logger.warning("Could not write app setting %s: %s", key, exc)
        return False


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_auto_sync_enabled(client: Client | None) -> bool:
    return parse_bool(get_setting(client, AUTO_SYNC_ENABLED_KEY))


def set_auto_sync_enabled(client: Client | None, enabled: bool) -> bool:
    return set_setting(client, AUTO_SYNC_ENABLED_KEY, "true" if enabled else "false")
