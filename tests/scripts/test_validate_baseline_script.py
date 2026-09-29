import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

BASELINE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_baseline.sh"


@pytest.mark.parametrize(
    ("audit_statuses", "expected_status"),
    [([0], 0), ([7, 0], 0), ([7, 8, 0], 0), ([1, 1, 1], 1), ([2, 2, 2], 2), ([7, 8, 9], 9)],
)
def test_baseline_audit_gates_build_and_preserves_failure_status(
    tmp_path: Path, audit_statuses: list[int], expected_status: int
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            log = Path("commands.jsonl")
            calls = []
            if log.exists():
                calls = [json.loads(line) for line in log.read_text().splitlines()]
            entry = {"args": args}
            status = 0
            if args[:2] == ["run", "pip-audit"]:
                attempt = sum(call["args"][:2] == ["run", "pip-audit"] for call in calls)
                status = json.loads(os.environ["AUDIT_STATUSES"])[attempt]
                entry["cache"] = os.environ["XDG_CACHE_HOME"]
                assert Path(entry["cache"]).is_dir()
                assert Path(args[args.index("--requirement") + 1]).is_file()
            elif args[0] == "export":
                Path(args[args.index("--output-file") + 1]).write_text("example==1.0\\n")
            elif args[0] == "build":
                Path("dist").mkdir()
                Path("dist/codex_a2a-0.0.0-py3-none-any.whl").touch()
            with log.open("a") as handle:
                handle.write(json.dumps(entry) + "\\n")
            sys.exit(status)
            """
        )
    )
    fake_uv.chmod(0o755)
    fake_sleep = bin_dir / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_sleep.chmod(0o755)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "smoke_test_built_cli.sh").write_text("touch smoke-ran\n")

    result = subprocess.run(
        ["bash", str(BASELINE_SCRIPT)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "AUDIT_STATUSES": json.dumps(audit_statuses),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == expected_status, result.stdout + result.stderr
    calls = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    audits = [call for call in calls if call["args"][:2] == ["run", "pip-audit"]]
    assert len(audits) == len(audit_statuses)
    assert len({call["cache"] for call in audits}) == len(audits)
    assert all(not Path(call["cache"]).exists() for call in audits)
    requirements = audits[0]["args"][-1]
    assert not Path(requirements).exists()
    assert any(call["args"][0] == "build" for call in calls) == (expected_status == 0)
    assert (tmp_path / "smoke-ran").exists() == (expected_status == 0)
    if expected_status:
        assert "pip-audit failed after 3 attempts" in result.stderr
