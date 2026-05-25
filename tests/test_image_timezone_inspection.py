from scripts.inspect_image_timezone import validate_timezone


def test_timezone_inspection_accepts_utc_image_config():
    errors = validate_timezone(
        {"TZ": "UTC"},
        {
            "TZ": "UTC",
            "time_tzname": ["UTC", "UTC"],
            "timezone_offset": 0,
            "local_utc_offset": 0,
        },
    )

    assert errors == []


def test_timezone_inspection_rejects_missing_image_env():
    errors = validate_timezone(
        {},
        {
            "TZ": "UTC",
            "time_tzname": ["UTC", "UTC"],
            "timezone_offset": 0,
            "local_utc_offset": 0,
        },
    )

    assert errors == ["image Config.Env must include TZ=UTC"]


def test_timezone_inspection_rejects_non_utc_runtime_offset():
    errors = validate_timezone(
        {"TZ": "UTC"},
        {
            "TZ": "America/Los_Angeles",
            "time_tzname": ["PST", "PDT"],
            "timezone_offset": 28800,
            "local_utc_offset": -28800,
        },
    )

    assert errors == [
        "container runtime must expose TZ=UTC",
        "container local timezone offset must be zero seconds",
        "container time.tzname must include UTC",
    ]
