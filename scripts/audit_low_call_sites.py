#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_PROJECT_ROOTS: Final = (Path("src/codex_a2a"),)
DEFAULT_SEARCH_ROOTS: Final = (Path("src/codex_a2a"), Path("tests"))
DEFAULT_MIN_CALLS: Final = 1
DEFAULT_MAX_CALLS: Final = 2
DEFAULT_CALLER_SAMPLE_LIMIT: Final = 5


@dataclass(frozen=True)
class FunctionDefinition:
    path: Path
    lineno: int
    symbol_type: str
    module_name: str
    qualified_name: str
    class_qualified_name: str | None
    name: str


@dataclass(frozen=True)
class CallSite:
    path: Path
    lineno: int
    caller: str


@dataclass(frozen=True)
class FunctionUsage:
    definition: FunctionDefinition
    source_calls: tuple[CallSite, ...]
    test_calls: tuple[CallSite, ...]

    @property
    def total_calls(self) -> int:
        return len(self.source_calls) + len(self.test_calls)


def _python_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
            continue
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _module_name_for_path(path: Path, project_roots: tuple[Path, ...]) -> str:
    for root in project_roots:
        if path == root:
            return path.stem
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        root_package = [] if root.name == "src" else [root.name]
        return ".".join(root_package + parts) if parts else root.name
    raise ValueError(f"Unable to derive module name for {path}")


def collect_definitions(
    *, project_roots: tuple[Path, ...] = DEFAULT_PROJECT_ROOTS
) -> tuple[
    dict[str, FunctionDefinition],
    dict[str, str],
    dict[str, str],
    dict[str, list[str]],
]:
    definitions: dict[str, FunctionDefinition] = {}
    top_level_functions: dict[str, str] = {}
    class_names: dict[str, str] = {}
    methods_by_name: dict[str, list[str]] = defaultdict(list)

    for path in _python_files(project_roots):
        module_name = _module_name_for_path(path, project_roots)
        tree = ast.parse(path.read_text(), filename=str(path))

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified_name = f"{module_name}.{node.name}"
                definition = FunctionDefinition(
                    path=path,
                    lineno=node.lineno,
                    symbol_type="function",
                    module_name=module_name,
                    qualified_name=qualified_name,
                    class_qualified_name=None,
                    name=node.name,
                )
                definitions[qualified_name] = definition
                top_level_functions[qualified_name] = qualified_name
                continue

            if not isinstance(node, ast.ClassDef):
                continue

            class_qualified_name = f"{module_name}.{node.name}"
            class_names[class_qualified_name] = class_qualified_name
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                qualified_name = f"{class_qualified_name}.{child.name}"
                definition = FunctionDefinition(
                    path=path,
                    lineno=child.lineno,
                    symbol_type="method",
                    module_name=module_name,
                    qualified_name=qualified_name,
                    class_qualified_name=class_qualified_name,
                    name=child.name,
                )
                definitions[qualified_name] = definition
                methods_by_name[child.name].append(qualified_name)

    return definitions, top_level_functions, class_names, methods_by_name


class _CallCollector(ast.NodeVisitor):
    def __init__(
        self,
        *,
        path: Path,
        module_name: str,
        top_level_definitions: dict[str, str],
        class_names: dict[str, str],
        unique_methods_by_name: dict[str, str],
    ) -> None:
        self._path = path
        self._module_name = module_name
        self._top_level_definitions = top_level_definitions
        self._class_names = class_names
        self._unique_methods_by_name = unique_methods_by_name
        self._class_stack: list[str] = []
        self._function_stack: list[str] = []
        self._imports: dict[str, str] = {}
        self.calls_by_target: dict[str, list[CallSite]] = defaultdict(list)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level != 0 or not node.module:
            return
        for alias in node.names:
            local_name = alias.asname or alias.name
            qualified_name = f"{node.module}.{alias.name}"
            self._imports[local_name] = qualified_name

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self._imports[local_name] = alias.name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        target = self._resolve_call_target(node.func)
        if target is not None:
            self.calls_by_target[target].append(
                CallSite(
                    path=self._path,
                    lineno=node.lineno,
                    caller=self._current_caller_name(),
                )
            )
        self.generic_visit(node)

    def _current_caller_name(self) -> str:
        if self._class_stack and self._function_stack:
            return f"{self._module_name}.{self._class_stack[-1]}.{self._function_stack[-1]}"
        if self._function_stack:
            return f"{self._module_name}.{self._function_stack[-1]}"
        if self._class_stack:
            return f"{self._module_name}.{self._class_stack[-1]}"
        return self._module_name

    def _resolve_call_target(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            imported = self._imports.get(node.id)
            if imported and imported in self._top_level_definitions:
                return imported
            same_module = f"{self._module_name}.{node.id}"
            if same_module in self._top_level_definitions:
                return same_module
            return None

        if not isinstance(node, ast.Attribute):
            return None

        if isinstance(node.value, ast.Name):
            if node.value.id in {"self", "cls"} and self._class_stack:
                current_class = f"{self._module_name}.{self._class_stack[-1]}"
                candidate = f"{current_class}.{node.attr}"
                if candidate in self._unique_methods_by_name.values():
                    return candidate
                return None

            imported = self._imports.get(node.value.id)
            if imported and imported in self._class_names:
                candidate = f"{imported}.{node.attr}"
                if candidate in self._unique_methods_by_name.values():
                    return candidate
                return None

            same_module_class = f"{self._module_name}.{node.value.id}"
            if same_module_class in self._class_names:
                candidate = f"{same_module_class}.{node.attr}"
                if candidate in self._unique_methods_by_name.values():
                    return candidate
                return None

        unique_method = self._unique_methods_by_name.get(node.attr)
        if unique_method is not None:
            return unique_method
        return None


def collect_function_usage(
    *,
    project_roots: tuple[Path, ...] = DEFAULT_PROJECT_ROOTS,
    search_roots: tuple[Path, ...] = DEFAULT_SEARCH_ROOTS,
) -> list[FunctionUsage]:
    definitions, top_level_definitions, class_names, methods_by_name = collect_definitions(
        project_roots=project_roots
    )
    unique_methods_by_name = {
        name: qualified_names[0]
        for name, qualified_names in methods_by_name.items()
        if len(qualified_names) == 1
    }
    search_files = _python_files(search_roots)
    test_root_names = {root.name for root in search_roots if root.name == "tests"}

    calls_by_target: dict[str, list[CallSite]] = defaultdict(list)
    for path in search_files:
        module_name = _module_name_for_path(path, search_roots)
        collector = _CallCollector(
            path=path,
            module_name=module_name,
            top_level_definitions=top_level_definitions,
            class_names=class_names,
            unique_methods_by_name=unique_methods_by_name,
        )
        collector.visit(ast.parse(path.read_text(), filename=str(path)))
        for target, call_sites in collector.calls_by_target.items():
            calls_by_target[target].extend(call_sites)

    usages: list[FunctionUsage] = []
    for qualified_name, definition in definitions.items():
        call_sites = calls_by_target.get(qualified_name, [])
        source_calls = tuple(
            call for call in call_sites if not _is_test_path(call.path, test_root_names)
        )
        test_calls = tuple(call for call in call_sites if _is_test_path(call.path, test_root_names))
        usages.append(
            FunctionUsage(
                definition=definition,
                source_calls=source_calls,
                test_calls=test_calls,
            )
        )
    return sorted(
        usages,
        key=lambda item: (
            item.total_calls,
            str(item.definition.path),
            item.definition.lineno,
            item.definition.qualified_name,
        ),
    )


def _is_test_path(path: Path, test_root_names: set[str]) -> bool:
    return any(part in test_root_names for part in path.parts)


def filter_low_call_candidates(
    usages: list[FunctionUsage],
    *,
    min_calls: int = DEFAULT_MIN_CALLS,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> list[FunctionUsage]:
    return [
        usage
        for usage in usages
        if min_calls <= usage.total_calls <= max_calls
    ]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report project-local function and method definitions with low direct "
            "call counts for manual abstraction review."
        )
    )
    parser.add_argument(
        "--project-root",
        action="append",
        default=None,
        help="Python source root that owns the definitions to audit. Defaults to src/codex_a2a.",
    )
    parser.add_argument(
        "--search-root",
        action="append",
        default=None,
        help=(
            "Python roots to scan for direct call sites. Defaults to src/codex_a2a and tests."
        ),
    )
    parser.add_argument(
        "--min-calls",
        type=int,
        default=DEFAULT_MIN_CALLS,
        help="Minimum direct call count to include in the report. Defaults to 1.",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=DEFAULT_MAX_CALLS,
        help="Maximum direct call count to include in the report. Defaults to 2.",
    )
    parser.add_argument(
        "--caller-sample-limit",
        type=int,
        default=DEFAULT_CALLER_SAMPLE_LIMIT,
        help="Maximum caller locations to print per candidate. Defaults to 5.",
    )
    return parser.parse_args(argv)


def _format_call_sites(call_sites: tuple[CallSite, ...], *, limit: int) -> str:
    if not call_sites:
        return "-"
    sample = ", ".join(
        f"{call.path}:{call.lineno} ({call.caller})" for call in call_sites[:limit]
    )
    remainder = len(call_sites) - min(len(call_sites), limit)
    if remainder > 0:
        return f"{sample}, +{remainder} more"
    return sample


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_roots = tuple(Path(root) for root in (args.project_root or DEFAULT_PROJECT_ROOTS))
    search_roots = tuple(Path(root) for root in (args.search_root or DEFAULT_SEARCH_ROOTS))
    usages = collect_function_usage(project_roots=project_roots, search_roots=search_roots)
    candidates = filter_low_call_candidates(
        usages,
        min_calls=args.min_calls,
        max_calls=args.max_calls,
    )

    if not candidates:
        print("No low-call-count function wrappers detected in the requested range.")
        return 0

    print(
        "Low-call-count function and method candidates "
        "(manual review only; dynamic dispatch is intentionally unresolved):"
    )
    for usage in candidates:
        print(
            f"- {usage.definition.path}:{usage.definition.lineno} "
            f"[{usage.definition.symbol_type}] {usage.definition.qualified_name} "
            f"total={usage.total_calls} src={len(usage.source_calls)} tests={len(usage.test_calls)}"
        )
        print(
            f"  src callers: {_format_call_sites(usage.source_calls, limit=args.caller_sample_limit)}"
        )
        print(
            f"  test callers: {_format_call_sites(usage.test_calls, limit=args.caller_sample_limit)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
