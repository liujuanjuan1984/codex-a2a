from pathlib import Path

DEPENDENCY_HEALTH_TEXT = Path("scripts/dependency_health.sh").read_text()
CONFORMANCE_TEXT = Path("scripts/conformance.sh").read_text()
HEALTH_COMMON_TEXT = Path("scripts/health_common.sh").read_text()
SCRIPTS_INDEX_TEXT = Path("scripts/README.md").read_text()
DOCTOR_TEXT = Path("scripts/doctor.sh").read_text()
VALIDATE_BASELINE_TEXT = Path("scripts/validate_baseline.sh").read_text()
DEPENDABOT_TEXT = Path(".github/dependabot.yml").read_text()


def test_shared_repo_health_prerequisites_live_in_common_helper() -> None:
    assert "run_shared_repo_health_prerequisites()" in HEALTH_COMMON_TEXT
    assert 'echo "[${label}] sync locked environment"' in HEALTH_COMMON_TEXT
    assert 'echo "[${label}] verify dependency compatibility"' in HEALTH_COMMON_TEXT
    assert "uv sync --all-extras --frozen" in HEALTH_COMMON_TEXT
    assert "uv pip check" in HEALTH_COMMON_TEXT


def test_validate_baseline_keeps_local_regression_scope() -> None:
    assert "uv run pre-commit run --all-files" in VALIDATE_BASELINE_TEXT
    assert "uv run mypy --config-file mypy.ini" in VALIDATE_BASELINE_TEXT
    assert "uv run pytest" in VALIDATE_BASELINE_TEXT
    assert "uv export" in VALIDATE_BASELINE_TEXT
    assert "uv run pip-audit" in VALIDATE_BASELINE_TEXT
    assert "uv pip list --outdated" not in VALIDATE_BASELINE_TEXT


def test_doctor_is_thin_default_regression_alias() -> None:
    assert 'exec bash "${SCRIPT_DIR}/validate_baseline.sh" "$@"' in DOCTOR_TEXT
    assert "uv run pytest" not in DOCTOR_TEXT
    assert "uv run mypy" not in DOCTOR_TEXT
    assert "uv run pip-audit" not in DOCTOR_TEXT


def test_conformance_keeps_external_tck_experiment_scope() -> None:
    assert "Run the official A2A TCK as a local/manual experiment." in CONFORMANCE_TEXT
    assert 'run_shared_repo_health_prerequisites "conformance"' in CONFORMANCE_TEXT
    assert "https://github.com/a2aproject/a2a-tck.git" in CONFORMANCE_TEXT
    assert "DummyChatCodexClient" in CONFORMANCE_TEXT
    assert "run_tck.run_test_category" in CONFORMANCE_TEXT
    assert "failed-tests.json" in CONFORMANCE_TEXT
    assert "uv run pre-commit run --all-files" not in CONFORMANCE_TEXT
    assert "uv run mypy" not in CONFORMANCE_TEXT


def test_dependency_health_keeps_dependency_review_scope() -> None:
    assert (
        'source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/health_common.sh"'
        in DEPENDENCY_HEALTH_TEXT
    )
    assert 'run_shared_repo_health_prerequisites "dependency-health"' in DEPENDENCY_HEALTH_TEXT
    assert "uv pip list --outdated" in DEPENDENCY_HEALTH_TEXT
    assert "uv run pip-audit" in DEPENDENCY_HEALTH_TEXT
    assert "uv run pytest" not in DEPENDENCY_HEALTH_TEXT
    assert "uv run mypy" not in DEPENDENCY_HEALTH_TEXT
    assert "uv run pre-commit run --all-files" not in DEPENDENCY_HEALTH_TEXT


def test_scripts_index_documents_split_health_entrypoints() -> None:
    assert "doctor.sh" in SCRIPTS_INDEX_TEXT
    assert "conformance.sh" in SCRIPTS_INDEX_TEXT
    assert "shortest maintainer entrypoint" in SCRIPTS_INDEX_TEXT
    assert "outside the default regression gate" in SCRIPTS_INDEX_TEXT
    assert "default local validation baseline used by contributors and CI" in SCRIPTS_INDEX_TEXT
    assert "standalone dependency review flow" in SCRIPTS_INDEX_TEXT
    assert "health_common.sh" in SCRIPTS_INDEX_TEXT
    assert "intentionally remain separate entrypoints" in SCRIPTS_INDEX_TEXT
    assert "single weekly grouped Dependabot PR for `uv`" in SCRIPTS_INDEX_TEXT


def test_dependabot_configuration_prefers_a_single_grouped_uv_pr() -> None:
    assert 'package-ecosystem: "uv"' in DEPENDABOT_TEXT
    assert 'package-ecosystem: "github-actions"' not in DEPENDABOT_TEXT
    assert "open-pull-requests-limit: 1" in DEPENDABOT_TEXT
    assert "uv-all-updates" in DEPENDABOT_TEXT
