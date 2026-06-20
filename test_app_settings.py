"""Tests for app_settings helpers."""

from lib import app_settings


def main() -> int:
    assert app_settings.parse_bool("true") is True
    assert app_settings.parse_bool("false") is False
    assert app_settings.parse_bool("TRUE") is True
    assert app_settings.parse_bool(None) is False
    assert app_settings.parse_bool("") is False
    print("PASS: app_settings bool parsing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
