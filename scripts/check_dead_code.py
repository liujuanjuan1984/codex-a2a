#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PRIVATE_NAME_PATTERN: Final = re.compile(r"^_[A-Za-z0-9_]+$")
DEFAULT_PROJECT_ROOTS: Final = (Path("src/codex_a2a"),)
DEFAULT_SEARCH_ROOTS: Final = (Path("src/codex_a2a"), Path("tests"))


@dataclass(frozen=True)
class DeadSymbol:
    path: Path
    lineno: int
    symbol_type: str
    qualified_name: str
    name: str


def _python_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.append(root)
            continue
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _count_symbol_occurrences(name: str, files: tuple[Path, ...]) -> int:
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    return sum(len(pattern.findall(path.read_text())) for path in files)


def _is_conservative_private_candidate(name: str) -> bool:
    return bool(PRIVATE_NAME_PATTERN.match(name)) and not name.startswith("__")


def collect_dead_symbols(
    *,
    project_roots: tuple[Path, ...] = DEFAULT_PROJECT_ROOTS,
    search_roots: tuple[Path, ...] = DEFAULT_SEARCH_ROOTS,
) -> list[DeadSymbol]:
    search_files = tuple(_python_files(search_roots))
    dead_symbols: list[DeadSymbol] = []

    for path in _python_files(project_roots):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not _is_conservative_private_candidate(node.name) or node.decorator_list:
                    continue
                if _count_symbol_occurrences(node.name, search_files) == 1:
                    dead_symbols.append(
                        DeadSymbol(
                            path=path,
                            lineno=node.lineno,
                            symbol_type="function",
                            qualified_name=node.name,
                            name=node.name,
                        )
                    )
                continue

            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if not _is_conservative_private_candidate(child.name) or child.decorator_list:
                        continue
                    if _count_symbol_occurrences(child.name, search_files) == 1:
                        dead_symbols.append(
                            DeadSymbol(
                                path=path,
                                lineno=child.lineno,
                                symbol_type="method",
                                qualified_name=f"{node.name}.{child.name}",
                                name=child.name,
                            )
                        )
                continue

            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not _is_conservative_private_candidate(target.id):
                    continue
                if _count_symbol_occurrences(target.id, search_files) == 1:
                    dead_symbols.append(
                        DeadSymbol(
                            path=path,
                            lineno=node.lineno,
                            symbol_type="constant",
                            qualified_name=target.id,
                            name=target.id,
                        )
                    )
    return sorted(dead_symbols, key=lambda item: (str(item.path), item.lineno, item.qualified_name))


def main() -> int:
    dead_symbols = collect_dead_symbols()
    if not dead_symbols:
        print("No high-confidence private dead code detected.")
        return 0

    print("High-confidence private dead code candidates detected:", file=sys.stderr)
    for symbol in dead_symbols:
        print(
            f"- {symbol.path}:{symbol.lineno} [{symbol.symbol_type}] {symbol.qualified_name}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
