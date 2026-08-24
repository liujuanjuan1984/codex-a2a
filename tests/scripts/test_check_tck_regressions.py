import json

from scripts.check_tck_regressions import (
    compare_failures,
    failures_from_json_report,
    failures_from_junit,
    snapshot_metadata_mismatch,
)

_NODEID = "tests/compatibility/test_demo.py::TestDemo::test_known[jsonrpc]"
_EXPECTED = [
    {
        "nodeid": _NODEID,
        "outcome": "failed",
        "failure_category": "known_demo_gap",
        "message_pattern": "expected demo, got fixture",
    }
]


def test_junit_parser_preserves_exact_pytest_nodeid_and_failure_message(tmp_path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        """<?xml version="1.0"?>
<testsuites><testsuite>
  <testcase classname="tests.compatibility.test_demo.TestDemo"
            name="test_known[jsonrpc]">
    <failure message="expected demo, got fixture">traceback</failure>
  </testcase>
</testsuite></testsuites>
""",
        encoding="utf-8",
    )

    assert failures_from_junit(report) == [
        {
            "nodeid": _NODEID,
            "outcome": "failed",
            "message": "expected demo, got fixture",
        }
    ]


def test_json_report_parser_extracts_failed_and_error_outcomes(tmp_path) -> None:
    report = tmp_path / "pytest.json"
    report.write_text(
        json.dumps(
            {
                "tests": [
                    {
                        "nodeid": _NODEID,
                        "outcome": "failed",
                        "call": {"longrepr": "expected demo, got fixture"},
                    },
                    {"nodeid": "test_ok", "outcome": "passed"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert failures_from_json_report(report) == [
        {
            "nodeid": _NODEID,
            "outcome": "failed",
            "message": "expected demo, got fixture",
        }
    ]


def test_incremental_gate_allows_known_and_resolved_failures() -> None:
    known = {
        "nodeid": _NODEID,
        "outcome": "failed",
        "message": "expected demo, got fixture",
    }

    matching = compare_failures(actual=[known], expected=_EXPECTED, transport="jsonrpc")
    resolved = compare_failures(actual=[], expected=_EXPECTED, transport="jsonrpc")

    assert matching["status"] == "unchanged"
    assert matching["counts"]["known_failures"] == 1
    assert resolved["status"] == "unchanged"
    assert resolved["counts"]["resolved_known_failures"] == 1


def test_incremental_gate_rejects_new_or_changed_failures() -> None:
    changed = {
        "nodeid": _NODEID,
        "outcome": "failed",
        "message": "unexpected timeout",
    }
    new = {
        "nodeid": "tests/compatibility/test_demo.py::test_new",
        "outcome": "error",
        "message": "new regression",
    }

    summary = compare_failures(
        actual=[changed, new],
        expected=_EXPECTED,
        transport="jsonrpc",
    )

    assert summary["status"] == "drifted"
    assert {item["reason"] for item in summary["regressions"]} == {
        "failure_category_changed",
        "new_failure",
    }


def test_incremental_gate_rejects_infrastructure_and_unreported_failures() -> None:
    infrastructure = compare_failures(
        actual=[],
        expected=_EXPECTED,
        transport="jsonrpc",
        tck_exit=2,
    )
    unreported = compare_failures(
        actual=[],
        expected=_EXPECTED,
        transport="jsonrpc",
        tck_exit=1,
    )

    assert infrastructure["status"] == "drifted"
    assert infrastructure["regressions"][-1]["reason"] == "tck_execution_failed"
    assert infrastructure["counts"]["resolved_known_failures"] == 0
    assert unreported["status"] == "drifted"
    assert unreported["regressions"][-1]["reason"] == "unreported_tck_failure"
    assert unreported["counts"]["resolved_known_failures"] == 0


def test_incremental_gate_accepts_resolved_baseline_only_on_successful_tck_exit() -> None:
    summary = compare_failures(
        actual=[],
        expected=_EXPECTED,
        transport="jsonrpc",
        tck_exit=0,
    )

    assert summary["status"] == "unchanged"
    assert summary["counts"]["resolved_known_failures"] == 1


def test_snapshot_metadata_makes_non_normative_spec_scope_explicit() -> None:
    baseline = {
        "scope": "non_normative_tck_behavior_snapshot",
        "tck_commit": "tck-sha",
        "tck_spec_snapshot": {"release": "v1.0.0", "commit": "spec-sha"},
    }

    assert (
        snapshot_metadata_mismatch(
            baseline,
            tck_commit="tck-sha",
            tck_spec_release="v1.0.0",
            tck_spec_commit="spec-sha",
        )
        is None
    )
    assert "embedded protocol snapshot" in snapshot_metadata_mismatch(
        baseline,
        tck_commit="tck-sha",
        tck_spec_release="v1.0.1",
        tck_spec_commit="new-spec-sha",
    )
