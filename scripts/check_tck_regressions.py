#!/usr/bin/env python3
"""Compare A2A TCK failures with the version-controlled known-failure baseline."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _junit_nodeid(testcase: ET.Element) -> str:
    classname = testcase.attrib.get("classname", "").strip()
    name = testcase.attrib.get("name", "").strip()
    parts = classname.split(".") if classname else []
    class_index = next(
        (index for index, part in enumerate(parts) if part[:1].isupper()),
        len(parts),
    )
    module_parts = parts[:class_index]
    class_parts = parts[class_index:]
    module_path = "/".join(module_parts)
    if module_path:
        module_path += ".py"
    suffix = "::".join((*class_parts, name))
    return f"{module_path}::{suffix}" if module_path else suffix


def failures_from_junit(report_path: Path) -> list[dict[str, str]]:
    # The input is a local report from the pinned TCK checkout, not an uploaded XML document.
    root = ET.parse(report_path).getroot()  # noqa: S314
    failures: list[dict[str, str]] = []
    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        outcome = "failed"
        if failure is None:
            failure = testcase.find("error")
            outcome = "error"
        if failure is None:
            continue
        failures.append(
            {
                "nodeid": _junit_nodeid(testcase),
                "outcome": outcome,
                "message": str(failure.attrib.get("message") or failure.text or ""),
            }
        )
    return failures


def failures_from_json_report(report_path: Path) -> list[dict[str, str]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    for test in report.get("tests", []):
        outcome = test.get("outcome")
        if outcome not in {"failed", "error"}:
            continue
        call = test.get("call") if isinstance(test.get("call"), dict) else {}
        message = call.get("longrepr") or test.get("longrepr") or ""
        failures.append(
            {
                "nodeid": str(test.get("nodeid") or ""),
                "outcome": str(outcome),
                "message": str(message),
            }
        )
    return failures


def compare_failures(
    *,
    actual: list[dict[str, str]],
    expected: list[dict[str, str]],
    transport: str,
) -> dict[str, Any]:
    expected_by_nodeid = {item["nodeid"]: item for item in expected}
    actual_by_nodeid = {item["nodeid"]: item for item in actual}
    known: list[dict[str, str]] = []
    regressions: list[dict[str, str]] = []

    for nodeid, failure in sorted(actual_by_nodeid.items()):
        baseline = expected_by_nodeid.get(nodeid)
        if baseline is None:
            regressions.append({**failure, "reason": "new_failure"})
            continue
        if failure["outcome"] != baseline["outcome"]:
            regressions.append(
                {
                    **failure,
                    "reason": "outcome_changed",
                    "expected_outcome": baseline["outcome"],
                }
            )
            continue
        pattern = baseline["message_pattern"]
        if re.search(pattern, failure["message"], flags=re.DOTALL) is None:
            regressions.append(
                {
                    **failure,
                    "reason": "failure_category_changed",
                    "expected_category": baseline["failure_category"],
                    "expected_message_pattern": pattern,
                }
            )
            continue
        known.append(
            {
                "nodeid": nodeid,
                "outcome": failure["outcome"],
                "failure_category": baseline["failure_category"],
            }
        )

    resolved = [
        {
            "nodeid": nodeid,
            "failure_category": baseline["failure_category"],
        }
        for nodeid, baseline in sorted(expected_by_nodeid.items())
        if nodeid not in actual_by_nodeid
    ]
    return {
        "status": "regressed" if regressions else "compatible",
        "transport": transport,
        "counts": {
            "actual_failures": len(actual),
            "known_failures": len(known),
            "resolved_known_failures": len(resolved),
            "regressions": len(regressions),
        },
        "known_failures": known,
        "resolved_known_failures": resolved,
        "regressions": regressions,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--transport", choices=("jsonrpc", "http_json"), required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--tck-commit", required=True)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--junit-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if baseline.get("tck_commit") != args.tck_commit:
        raise SystemExit(
            "TCK commit does not match known-failure baseline: "
            f"expected {baseline.get('tck_commit')}, got {args.tck_commit}"
        )
    category = "must" if args.category == "mandatory" else args.category
    if baseline.get("category") != category:
        raise SystemExit(
            "TCK category does not match known-failure baseline: "
            f"expected {baseline.get('category')}, got {category}"
        )
    expected = baseline.get("transports", {}).get(args.transport)
    if not isinstance(expected, list):
        raise SystemExit(f"No known-failure baseline for transport {args.transport}")

    if args.json_report is not None and args.json_report.is_file():
        actual = failures_from_json_report(args.json_report)
        evidence = str(args.json_report)
    elif args.junit_report is not None and args.junit_report.is_file():
        actual = failures_from_junit(args.junit_report)
        evidence = str(args.junit_report)
    else:
        raise SystemExit("No pytest JSON or JUnit report is available for comparison")

    summary = compare_failures(actual=actual, expected=expected, transport=args.transport)
    summary["baseline"] = str(args.baseline)
    summary["evidence"] = evidence
    summary["tck_commit"] = args.tck_commit
    summary["category"] = category
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.output.parent / "failed-tests.json").write_text(
        json.dumps(actual, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = summary["counts"]
    print(
        "TCK incremental gate "
        f"{summary['status']}: transport={args.transport} "
        f"known={counts['known_failures']} "
        f"resolved={counts['resolved_known_failures']} "
        f"regressions={counts['regressions']}"
    )
    for regression in summary["regressions"]:
        print(f"- {regression['reason']}: {regression['nodeid']}")
    return 1 if summary["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
