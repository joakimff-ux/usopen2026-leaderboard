"""Tests for app_settings helpers."""

from lib import app_settings


class FakeApiError(Exception):
    def __init__(self, payload: dict):
        super().__init__(str(payload))
        self.code = payload.get("code")
        self.message = payload.get("message")
        self.details = payload.get("details")
        self.hint = payload.get("hint")
        self.args = (payload,)


def test_format_supabase_error_from_dict_args() -> None:
    exc = FakeApiError(
        {
            "message": 'new row violates row-level security policy for table "app_settings"',
            "code": "42501",
            "hint": None,
            "details": None,
        }
    )
    formatted = app_settings.format_supabase_error(exc)
    assert "row-level security policy" in formatted
    assert "code=42501" in formatted


def test_parse_bool() -> None:
    assert app_settings.parse_bool("true") is True
    assert app_settings.parse_bool("false") is False
    assert app_settings.parse_bool("TRUE") is True
    assert app_settings.parse_bool(None) is False
    assert app_settings.parse_bool("") is False


def main() -> int:
    test_parse_bool()
    test_format_supabase_error_from_dict_args()
    print("PASS: app_settings unit tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
