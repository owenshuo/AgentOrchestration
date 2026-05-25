import datetime as dt

from scripts.scan_image_licenses import evaluate_report


def test_license_scan_allows_runtime_system_and_python_packages():
    report = {
        "packages": [
            {
                "ecosystem": "system",
                "name": "libc6",
                "version": "2.36",
                "license": "UNKNOWN",
            },
            {
                "ecosystem": "python",
                "name": "fastapi",
                "version": "0.104.0",
                "license": "MIT",
            },
        ]
    }
    policy = {
        "allow_licenses": ["MIT"],
        "prohibited_licenses": ["GPL-3.0-only"],
        "deny_unknown": False,
        "exceptions": [],
    }

    violations, packages = evaluate_report(report, policy, dt.date(2026, 1, 1))

    assert violations == []
    ecosystems = {package["ecosystem"] for package in packages}

    assert ecosystems == {"system", "python"}


def test_license_scan_blocks_prohibited_image_dependency():
    report = {
        "packages": [
            {
                "ecosystem": "python",
                "name": "badlib",
                "version": "1.0.0",
                "license": "GPL-3.0-only",
            },
        ]
    }
    policy = {
        "allow_licenses": ["MIT"],
        "prohibited_licenses": ["GPL-3.0-only"],
        "deny_unknown": False,
        "exceptions": [],
    }

    violations, _ = evaluate_report(report, policy, dt.date(2026, 1, 1))

    assert violations == [
        "python:badlib 1.0.0 uses prohibited license GPL-3.0-only",
    ]


def test_license_scan_requires_exception_owner_and_expiration():
    report = {
        "packages": [
            {
                "ecosystem": "python",
                "name": "coveredlib",
                "version": "1.0.0",
                "license": "GPL-3.0-only",
            },
        ]
    }
    policy = {
        "allow_licenses": [],
        "prohibited_licenses": ["GPL-3.0-only"],
        "deny_unknown": False,
        "exceptions": [
            {
                "ecosystem": "python",
                "package": "coveredlib",
                "license": "GPL-3.0-only",
                "owner": "security",
                "expires": "2026-12-31",
                "reason": "approved migration window",
            },
            {
                "ecosystem": "python",
                "package": "brokenlib",
                "license": "GPL-3.0-only",
                "owner": "",
                "expires": "2026-12-31",
                "reason": "missing owner should fail policy validation",
            },
        ],
    }

    violations, packages = evaluate_report(
        report,
        policy,
        today=dt.date(2026, 1, 1),
    )

    assert violations == [
        "invalid exception for python:brokenlib (GPL-3.0-only): missing owner",
    ]
    assert packages[0]["exception"]["owner"] == "security"
