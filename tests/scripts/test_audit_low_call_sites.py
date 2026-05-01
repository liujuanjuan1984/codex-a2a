from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_script_module():
    script_path = Path("scripts/audit_low_call_sites.py")
    spec = importlib.util.spec_from_file_location("audit_low_call_sites", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_function_usage_resolves_local_imported_and_method_calls(
    tmp_path: Path,
) -> None:
    module = _load_script_module()

    project_root = tmp_path / "src" / "sample_pkg"
    tests_root = tmp_path / "tests"
    project_root.mkdir(parents=True)
    tests_root.mkdir()

    (project_root / "helpers.py").write_text(
        "\n".join(
            [
                "def leaf() -> int:",
                "    return 1",
                "",
                "def wrapper() -> int:",
                "    return leaf()",
                "",
                "class Service:",
                "    def ping(self) -> int:",
                "        return leaf()",
                "",
                "    def invoke(self) -> int:",
                "        return self.ping()",
                "",
                "class Runner:",
                "    def run(self) -> int:",
                "        return Service.ping(self)",
            ]
        )
        + "\n"
    )
    (project_root / "consumer.py").write_text(
        "\n".join(
            [
                "from sample_pkg.helpers import leaf as imported_leaf, Service",
                "",
                "def use_leaf() -> int:",
                "    return imported_leaf()",
                "",
                "def use_method() -> int:",
                "    return Service.ping(Service())",
            ]
        )
        + "\n"
    )
    (tests_root / "test_helpers.py").write_text(
        "\n".join(
            [
                "from sample_pkg.helpers import leaf",
                "",
                "def test_leaf() -> None:",
                "    assert leaf() == 1",
            ]
        )
        + "\n"
    )

    usages = module.collect_function_usage(
        project_roots=(project_root,),
        search_roots=(project_root, tests_root),
    )
    usage_by_name = {usage.definition.qualified_name: usage for usage in usages}

    leaf_usage = usage_by_name["sample_pkg.helpers.leaf"]
    assert leaf_usage.total_calls == 4
    assert len(leaf_usage.source_calls) == 3
    assert len(leaf_usage.test_calls) == 1

    ping_usage = usage_by_name["sample_pkg.helpers.Service.ping"]
    assert ping_usage.total_calls == 3
    assert len(ping_usage.source_calls) == 3
    assert not ping_usage.test_calls

    wrapper_usage = usage_by_name["sample_pkg.helpers.wrapper"]
    assert wrapper_usage.total_calls == 0

    invoke_usage = usage_by_name["sample_pkg.helpers.Service.invoke"]
    assert invoke_usage.total_calls == 0

    run_usage = usage_by_name["sample_pkg.helpers.Runner.run"]
    assert run_usage.total_calls == 0


def test_main_reports_only_requested_low_call_range(
    tmp_path: Path,
    capsys,
) -> None:
    module = _load_script_module()

    project_root = tmp_path / "src" / "sample_pkg"
    project_root.mkdir(parents=True)
    (project_root / "helpers.py").write_text(
        "\n".join(
            [
                "def leaf() -> int:",
                "    return 1",
                "",
                "def wrapper() -> int:",
                "    return leaf()",
                "",
                "def top() -> int:",
                "    return wrapper()",
            ]
        )
        + "\n"
    )

    exit_code = module.main(
        [
            "--project-root",
            str(project_root),
            "--search-root",
            str(project_root),
            "--min-calls",
            "1",
            "--max-calls",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "sample_pkg.helpers.leaf total=1" in captured.out
    assert "sample_pkg.helpers.wrapper total=1" in captured.out
    assert "sample_pkg.helpers.top total=" not in captured.out
