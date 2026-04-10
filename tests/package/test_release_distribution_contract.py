import tomllib
from pathlib import Path

PYPROJECT_TEXT = Path("pyproject.toml").read_text()
PYPROJECT_DATA = tomllib.loads(PYPROJECT_TEXT)
README_TEXT = Path("README.md").read_text()
CONTRIBUTING_TEXT = Path("CONTRIBUTING.md").read_text()
SECURITY_TEXT = Path("SECURITY.md").read_text()
SCRIPTS_README_TEXT = Path("scripts/README.md").read_text()
CI_WORKFLOW_TEXT = Path(".github/workflows/ci.yml").read_text()
DEPENDENCY_HEALTH_WORKFLOW_TEXT = Path(".github/workflows/dependency-health.yml").read_text()
PUBLISH_WORKFLOW_TEXT = Path(".github/workflows/publish.yml").read_text()
DEPENDENCY_HEALTH_SCRIPT_TEXT = Path("scripts/dependency_health.sh").read_text()
SMOKE_TEST_SCRIPT_TEXT = Path("scripts/smoke_test_built_cli.sh").read_text()
RUNTIME_MATRIX_SCRIPT_TEXT = Path("scripts/validate_runtime_matrix.sh").read_text()
SYNC_CODEX_DOCS_TEXT = Path("scripts/sync_codex_docs.sh").read_text()


def test_readme_documents_released_cli_installation_via_uv_tool() -> None:
    assert "uv tool install codex-a2a" in README_TEXT
    assert "uv tool upgrade codex-a2a" in README_TEXT
    assert 'uv tool install "codex-a2a==<version>"' in README_TEXT
    assert "Self-start the released CLI against a workspace root:" in README_TEXT
    assert "## Development From Source" not in README_TEXT
    assert "## Development From Source" in CONTRIBUTING_TEXT
    assert "CODEX_WORKSPACE_ROOT=/abs/path/to/workspace uv run codex-a2a" in CONTRIBUTING_TEXT
    assert "http://127.0.0.1:8000/.well-known/agent-card.json" in CONTRIBUTING_TEXT
    assert "Install and verify the local `codex` CLI itself." in README_TEXT
    assert "does not provision Codex providers, login state, or API keys for you" in README_TEXT
    assert "Startup fails fast if the local `codex` runtime is missing" in README_TEXT
    assert "CODEX_WORKSPACE_ROOT=/abs/path/to/workspace" in README_TEXT  # pragma: allowlist secret
    assert (
        "A2A_DATABASE_URL=sqlite+aiosqlite:////abs/path/to/workspace/.codex-a2a/codex-a2a.db"
        in README_TEXT
    )
    static_auth_example = (
        'A2A_STATIC_AUTH_CREDENTIALS=\'[{"id":"local-bearer","scheme":"bearer",'
        '"token":"\'"${DEMO_BEARER_TOKEN}"\'","principal":"automation"}]\' \\'
    )
    assert static_auth_example in README_TEXT
    assert "CODEX_WORKSPACE_ROOT=/abs/path/to/workspace \\\ncodex-a2a" in README_TEXT
    assert "export A2A_HOST=127.0.0.1" not in README_TEXT
    assert "A2A_CLIENT_BASIC_AUTH" in README_TEXT
    assert "--token your-outbound-token" not in README_TEXT
    assert "codex-a2a deploy" not in README_TEXT
    assert "GH_TOKEN" not in README_TEXT
    assert "create a PR from the working branch" in README_TEXT
    assert "merge into `main` after human review" in README_TEXT
    assert "[Compatibility Guide](docs/compatibility.md)" in README_TEXT
    assert "[External Conformance Experiments](docs/conformance.md)" in README_TEXT
    assert "[Contributing Guide](CONTRIBUTING.md)" in README_TEXT
    assert "single-tenant trust boundary" in README_TEXT
    assert "Portable vs Private Surface" in README_TEXT
    assert "Codex-specific control plane" in README_TEXT


def test_publish_workflow_builds_and_smoke_tests_release_artifacts() -> None:
    assert "name: Release Publish" in PUBLISH_WORKFLOW_TEXT
    assert 'tags:\n      - "v*"' in PUBLISH_WORKFLOW_TEXT
    assert "workflow_dispatch" in PUBLISH_WORKFLOW_TEXT
    assert "name: Build Release Artifacts" in PUBLISH_WORKFLOW_TEXT
    assert "name: Publish to PyPI" in PUBLISH_WORKFLOW_TEXT
    assert "name: Sync GitHub Release" in PUBLISH_WORKFLOW_TEXT
    assert "Export runtime requirements for vulnerability audit" in PUBLISH_WORKFLOW_TEXT
    assert "Run runtime dependency vulnerability audit" in PUBLISH_WORKFLOW_TEXT
    assert "uv run pip-audit --requirement /tmp/runtime-requirements.txt" in PUBLISH_WORKFLOW_TEXT
    assert "uv build --no-sources" in PUBLISH_WORKFLOW_TEXT
    assert "bash ./scripts/smoke_test_built_cli.sh" in PUBLISH_WORKFLOW_TEXT
    assert "gh-action-pypi-publish" in PUBLISH_WORKFLOW_TEXT


def test_ci_workflow_deduplicates_full_gate_and_runtime_matrix() -> None:
    assert "name: Validation" in CI_WORKFLOW_TEXT
    assert "quality-gate:" in CI_WORKFLOW_TEXT
    assert "name: Validation Baseline" in CI_WORKFLOW_TEXT
    assert 'python-version: "3.13"' in CI_WORKFLOW_TEXT
    assert "bash ./scripts/validate_baseline.sh" in CI_WORKFLOW_TEXT
    assert "runtime-matrix:" in CI_WORKFLOW_TEXT
    assert "name: Runtime Matrix (Python ${{ matrix.python-version }})" in CI_WORKFLOW_TEXT
    assert 'python-version: ["3.11", "3.12"]' in CI_WORKFLOW_TEXT
    assert "bash ./scripts/validate_runtime_matrix.sh" in CI_WORKFLOW_TEXT


def test_dependency_health_workflow_runs_as_a_standalone_check() -> None:
    assert "name: Dependency Health" in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert "workflow_dispatch" in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert 'cron: "0 3 1 * *"' in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert "dependency-health:" in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert "name: Dependency Health Audit" in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert 'python-version: "3.13"' in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert "enable-cache: false" in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert "bash ./scripts/dependency_health.sh" in DEPENDENCY_HEALTH_WORKFLOW_TEXT
    assert "uv pip list --outdated" in DEPENDENCY_HEALTH_SCRIPT_TEXT
    assert "uv run pip-audit" in DEPENDENCY_HEALTH_SCRIPT_TEXT


def test_scripts_index_exposes_built_cli_smoke_test() -> None:
    assert "doctor.sh" in SCRIPTS_README_TEXT
    assert "conformance.sh" in SCRIPTS_README_TEXT
    assert "validate_runtime_matrix.sh" in SCRIPTS_README_TEXT
    assert "dependency_health.sh" in SCRIPTS_README_TEXT
    assert "smoke_test_built_cli.sh" in SCRIPTS_README_TEXT
    assert "`uv tool`" in SCRIPTS_README_TEXT
    assert "runtime entrypoints live in the released `codex-a2a` CLI" in SCRIPTS_README_TEXT
    assert "Repository-maintainer scripts live here." in SCRIPTS_README_TEXT
    assert "deploy_light.sh" not in SCRIPTS_README_TEXT
    assert "start_services.sh" not in SCRIPTS_README_TEXT


def test_runtime_docs_no_longer_publish_deployment_guide() -> None:
    assert not Path("docs/deployment.md").exists()
    assert "[Deployment Guide](docs/deployment.md)" not in README_TEXT


def test_security_policy_declares_single_tenant_boundary() -> None:
    assert "single-tenant trust boundary" in SECURITY_TEXT
    assert "GH_TOKEN" not in SECURITY_TEXT


def test_released_cli_entrypoint_points_to_cli_module() -> None:
    assert 'codex-a2a = "codex_a2a.cli:main"' in PYPROJECT_TEXT
    assert "[tool.setuptools.package-data]" in PYPROJECT_TEXT
    assert 'codex_a2a = ["py.typed"]' in PYPROJECT_TEXT


def test_project_metadata_exposes_open_source_entrypoints_cleanly() -> None:
    project = PYPROJECT_DATA["project"]
    assert project["authors"] == [{"name": "liujuanjuan1984@Intelligent-Internet"}]
    assert project["license"] == "Apache-2.0"
    assert project["urls"]["Documentation"].endswith("/tree/main/docs")
    assert project["urls"]["Releases"].endswith("/releases")
    assert project["urls"]["Security"].endswith("/security/policy")


def test_repository_no_longer_ships_deploy_assets() -> None:
    assert not Path("src/codex_a2a/assets").exists()


def test_repository_removes_redundant_deploy_wrappers() -> None:
    assert not Path("scripts/deploy.sh").exists()
    assert not Path("scripts/deploy").exists()
    assert not Path("scripts/shell_helpers.sh").exists()
    assert not Path("scripts/init_system.sh").exists()
    assert not Path("scripts/uninstall.sh").exists()


def test_repository_wrappers_only_keep_remaining_user_or_maintainer_entrypoints() -> None:
    assert "uv tool install" in SMOKE_TEST_SCRIPT_TEXT
    assert '--python "${python_bin}"' in SMOKE_TEST_SCRIPT_TEXT
    assert "--python 3.13" not in SMOKE_TEST_SCRIPT_TEXT
    assert 'export PATH="${tool_bin_dir}:${PATH}"' in SMOKE_TEST_SCRIPT_TEXT
    assert 'UV_LINK_MODE="copy"' in SMOKE_TEST_SCRIPT_TEXT
    assert 'find "${tool_dir}" \\( -type f -o -type l \\) -path ' in SMOKE_TEST_SCRIPT_TEXT
    assert '"${installed_python}" -c "import codex_a2a; print(codex_a2a.__version__)"' in (
        SMOKE_TEST_SCRIPT_TEXT
    )
    assert "uv run pytest --no-cov" in RUNTIME_MATRIX_SCRIPT_TEXT
    assert 'CODEX_CLI_BIN="${fake_codex_bin}"' in SMOKE_TEST_SCRIPT_TEXT
    assert 'A2A_DATABASE_URL="sqlite+aiosqlite:///${database_path}"' in SMOKE_TEST_SCRIPT_TEXT
    assert 'cat >"${fake_codex_bin}"' in SMOKE_TEST_SCRIPT_TEXT
    assert ">/dev/null 2>&1" in SMOKE_TEST_SCRIPT_TEXT
    assert "git clone --depth 1 https://github.com/openai/codex.git" in SYNC_CODEX_DOCS_TEXT


def test_validation_and_publish_paths_filter_known_build_warnings() -> None:
    validate_baseline_text = Path("scripts/validate_baseline.sh").read_text()
    assert "vcs_versioning._backends._git" in validate_baseline_text
    assert "vcs_versioning.overrides" in validate_baseline_text
    assert "uv run pip-audit --requirement" in validate_baseline_text
    assert "vcs_versioning._backends._git" in PUBLISH_WORKFLOW_TEXT
    assert "vcs_versioning.overrides" in PUBLISH_WORKFLOW_TEXT


def test_gitignore_keeps_python_sources_without_unignoring_runtime_caches() -> None:
    gitignore_text = Path(".gitignore").read_text()
    assert "!tests/parts/*.py" in gitignore_text
    assert "!tests/parts/**" not in gitignore_text
