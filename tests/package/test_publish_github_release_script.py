from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_RELEASE_SCRIPT = REPO_ROOT / "scripts" / "publish_github_release.sh"


def _write_fake_gh(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_gh = tmp_path / "gh"
    state_path = tmp_path / "gh-state.json"
    log_path = tmp_path / "gh.log"
    fake_gh.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            from __future__ import annotations

            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["FAKE_GH_STATE"])
            log_path = Path(os.environ["FAKE_GH_LOG"])

            if state_path.exists():
                state = json.loads(state_path.read_text())
            else:
                state = {"release_exists": False, "assets": []}

            args = sys.argv[1:]
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(" ".join(args) + "\\n")

            if len(args) < 3 or args[0] != "release":
                print(f"unsupported gh invocation: {args}", file=sys.stderr)
                sys.exit(2)

            command = args[1]
            tag = args[2]

            if command == "view":
                if not state["release_exists"]:
                    print("release not found", file=sys.stderr)
                    sys.exit(1)
                if args[3:] == ["--json", "assets"]:
                    print(json.dumps({"assets": [{"name": name} for name in state["assets"]]}))
                    sys.exit(0)
                print(f"release {tag}")
                sys.exit(0)

            if command == "create":
                if os.environ.get("FAKE_GH_FAIL_CREATE") == "1":
                    print("synthetic create failure", file=sys.stderr)
                    sys.exit(1)
                state["release_exists"] = True
                state_path.write_text(json.dumps(state), encoding="utf-8")
                print(f"created {tag}")
                sys.exit(0)

            if command == "upload":
                if not state["release_exists"]:
                    print("release not found", file=sys.stderr)
                    sys.exit(1)
                if os.environ.get("FAKE_GH_FAIL_UPLOAD") == "1":
                    print("synthetic upload failure", file=sys.stderr)
                    sys.exit(1)
                asset_name = Path(args[3]).name
                if asset_name not in state["assets"]:
                    state["assets"].append(asset_name)
                state_path.write_text(json.dumps(state), encoding="utf-8")
                print(f"uploaded {asset_name}")
                sys.exit(0)

            print(f"unsupported gh release command: {args}", file=sys.stderr)
            sys.exit(2)
            """
        ),
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
    return fake_gh, state_path, log_path


def _write_release_assets(tmp_path: Path) -> Path:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "codex_a2a-0.5.1.tar.gz").write_text("sdist", encoding="utf-8")
    (dist_dir / "codex_a2a-0.5.1-py3-none-any.whl").write_text("wheel", encoding="utf-8")
    return dist_dir


def _script_env(fake_gh_dir: Path, state_path: Path, log_path: Path, dist_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_gh_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_GH_STATE"] = str(state_path)
    env["FAKE_GH_LOG"] = str(log_path)
    env["DIST_DIR"] = str(dist_dir)
    env["RELEASE_TAG"] = "v0.5.1"
    env["RELEASE_RETRY_ATTEMPTS"] = "2"
    env["RELEASE_RETRY_DELAY_SECONDS"] = "0"
    env["PYTHON_BIN"] = sys.executable
    return env


def test_publish_release_script_creates_missing_release_before_upload(tmp_path: Path) -> None:
    fake_gh, state_path, log_path = _write_fake_gh(tmp_path)
    dist_dir = _write_release_assets(tmp_path)

    result = subprocess.run(
        ["bash", str(PUBLISH_RELEASE_SCRIPT)],
        cwd=REPO_ROOT,
        env=_script_env(fake_gh.parent, state_path, log_path, dist_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["release_exists"] is True
    assert set(state["assets"]) == {
        "codex_a2a-0.5.1.tar.gz",
        "codex_a2a-0.5.1-py3-none-any.whl",
    }
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert "release create v0.5.1 --generate-notes --verify-tag" in log_lines
    assert "release upload v0.5.1 " + str(dist_dir / "codex_a2a-0.5.1.tar.gz") in log_lines
    assert "release upload v0.5.1 " + str(dist_dir / "codex_a2a-0.5.1-py3-none-any.whl") in log_lines


def test_publish_release_script_fails_when_asset_upload_keeps_failing(tmp_path: Path) -> None:
    fake_gh, state_path, log_path = _write_fake_gh(tmp_path)
    dist_dir = _write_release_assets(tmp_path)
    env = _script_env(fake_gh.parent, state_path, log_path, dist_dir)
    env["FAKE_GH_FAIL_UPLOAD"] = "1"

    result = subprocess.run(
        ["bash", str(PUBLISH_RELEASE_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "synthetic upload failure" in result.stderr
    assert "Command failed after 2 attempts" in result.stderr
