from pathlib import Path

ENABLE_INSTANCE_TEXT = Path("scripts/deploy/enable_instance.sh").read_text()
DEPLOYMENT_GUIDE_TEXT = Path("docs/deployment.md").read_text()
GUIDE_TEXT = Path("docs/guide.md").read_text()
SCRIPTS_README_TEXT = Path("scripts/README.md").read_text()


def test_enable_instance_probes_authenticated_health() -> None:
    assert 'source "${SCRIPT_DIR}/../shell_helpers.sh"' in ENABLE_INSTANCE_TEXT
    assert "Authorization: Bearer %s" in ENABLE_INSTANCE_TEXT
    assert 'curl -fsS -H "@${A2A_HEALTHCHECK_AUTH_HEADER_FILE}"' in ENABLE_INSTANCE_TEXT
    assert "resolve_healthcheck_bearer_token" in ENABLE_INSTANCE_TEXT
    assert "A2A_ENABLE_HEALTH_ENDPOINT" in ENABLE_INSTANCE_TEXT


def test_docs_describe_authenticated_health_probe() -> None:
    assert "authenticated lightweight `/health` probe" in GUIDE_TEXT
    assert "authenticated `GET /health` probe" in DEPLOYMENT_GUIDE_TEXT
    assert "authenticated `/health` readiness" in SCRIPTS_README_TEXT
