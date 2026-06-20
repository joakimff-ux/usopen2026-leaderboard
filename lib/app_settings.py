"""Persistent app settings stored in Supabase."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from supabase import Client

logger = logging.getLogger(__name__)

AUTO_SYNC_ENABLED_KEY = "auto_sync_enabled"


@dataclass
class SettingReadResult:
    value: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class SettingWriteResult:
    ok: bool = False
    error: str | None = None


@dataclass
class AppSettingsProbeResult:
    select_ok: bool = False
    select_rows: list[dict[str, Any]] | None = None
    select_error: str | None = None
    upsert_ok: bool = False
    upsert_error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_supabase_error(exc: Exception) -> str:
    message = str(exc)
    code = None
    details = None
    hint = None

    if hasattr(exc, "message") and getattr(exc, "message", None):
        message = str(exc.message)
    if hasattr(exc, "code") and exc.code:
        code = exc.code
    if hasattr(exc, "details") and exc.details:
        details = exc.details
    if hasattr(exc, "hint") and exc.hint:
        hint = exc.hint

    if not code:
        args = getattr(exc, "args", ())
        if args and isinstance(args[0], dict):
            payload = args[0]
            code = payload.get("code")
            message = payload.get("message") or message
            details = payload.get("details") or details
            hint = payload.get("hint") or hint
        elif args and isinstance(args[0], str):
            message = args[0]

    parts = [message]
    if code:
        parts.append(f"code={code}")
    if details:
        parts.append(f"details={details}")
    if hint:
        parts.append(f"hint={hint}")
    return " | ".join(parts)


def get_setting(client: Client | None, key: str) -> SettingReadResult:
    if client is None:
        error = "Supabase client is None (missing SUPABASE_URL or SUPABASE_ANON_KEY)"
        logger.error("get_setting(%s) failed: %s", key, error)
        return SettingReadResult(error=error)

    logger.info("get_setting(%s): select from app_settings", key)
    try:
        response = client.table("app_settings").select("key,value,updated_at").eq("key", key).limit(1).execute()
        rows = response.data or []
        if not rows:
            logger.info("get_setting(%s): no row found", key)
            return SettingReadResult(value=None)
        value = str(rows[0]["value"])
        logger.info("get_setting(%s): ok value=%r updated_at=%s", key, value, rows[0].get("updated_at"))
        return SettingReadResult(value=value)
    except Exception as exc:
        error = format_supabase_error(exc)
        logger.error("get_setting(%s) failed: %s", key, error, exc_info=True)
        return SettingReadResult(error=error)


def set_setting(client: Client | None, key: str, value: str) -> SettingWriteResult:
    if client is None:
        error = "Supabase client is None (missing SUPABASE_URL or SUPABASE_ANON_KEY)"
        logger.error("set_setting(%s=%r) failed: %s", key, value, error)
        return SettingWriteResult(ok=False, error=error)

    payload = {"key": key, "value": value, "updated_at": _now_iso()}
    logger.info("set_setting(%s=%r): upsert into app_settings", key, value)
    try:
        response = client.table("app_settings").upsert(payload, on_conflict="key").execute()
        logger.info("set_setting(%s=%r): ok rows=%s", key, value, response.data)
        return SettingWriteResult(ok=True)
    except Exception as exc:
        error = format_supabase_error(exc)
        logger.error("set_setting(%s=%r) failed: %s", key, value, error, exc_info=True)
        return SettingWriteResult(ok=False, error=error)


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_auto_sync_setting(client: Client | None) -> SettingReadResult:
    logger.info("get_auto_sync_setting(): reading %s", AUTO_SYNC_ENABLED_KEY)
    result = get_setting(client, AUTO_SYNC_ENABLED_KEY)
    if result.error:
        logger.error("get_auto_sync_setting() failed: %s", result.error)
    else:
        logger.info(
            "get_auto_sync_setting(): raw=%r parsed=%s",
            result.value,
            parse_bool(result.value),
        )
    return result


def save_auto_sync_setting(client: Client | None, enabled: bool) -> SettingWriteResult:
    value = "true" if enabled else "false"
    logger.info("save_auto_sync_setting(enabled=%s): writing value=%r", enabled, value)
    result = set_setting(client, AUTO_SYNC_ENABLED_KEY, value)
    if result.ok:
        logger.info("save_auto_sync_setting(enabled=%s): ok", enabled)
    else:
        logger.error("save_auto_sync_setting(enabled=%s) failed: %s", enabled, result.error)
    return result


def get_auto_sync_enabled(client: Client | None) -> bool:
    result = get_auto_sync_setting(client)
    if result.error:
        return False
    return parse_bool(result.value)


def set_auto_sync_enabled(client: Client | None, enabled: bool) -> bool:
    return save_auto_sync_setting(client, enabled).ok


def probe_app_settings(client: Client | None) -> AppSettingsProbeResult:
    probe = AppSettingsProbeResult()
    if client is None:
        probe.select_error = "Supabase client is None"
        probe.upsert_error = probe.select_error
        return probe

    logger.info("probe_app_settings(): select * from app_settings")
    try:
        response = client.table("app_settings").select("*").execute()
        probe.select_ok = True
        probe.select_rows = response.data or []
        logger.info("probe_app_settings(): select ok rows=%s", probe.select_rows)
    except Exception as exc:
        probe.select_error = format_supabase_error(exc)
        logger.error("probe_app_settings(): select failed: %s", probe.select_error, exc_info=True)

    logger.info("probe_app_settings(): upsert auto_sync_enabled=true")
    try:
        client.table("app_settings").upsert(
            {"key": AUTO_SYNC_ENABLED_KEY, "value": "true", "updated_at": _now_iso()},
            on_conflict="key",
        ).execute()
        probe.upsert_ok = True
        logger.info("probe_app_settings(): upsert ok")
    except Exception as exc:
        probe.upsert_error = format_supabase_error(exc)
        logger.error("probe_app_settings(): upsert failed: %s", probe.upsert_error, exc_info=True)

    return probe
