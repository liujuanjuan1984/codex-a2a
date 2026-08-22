from __future__ import annotations

import os
import stat
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from codex_a2a.config import Settings

_SQLITE_JOURNAL_MODE = "WAL"
_SQLITE_BUSY_TIMEOUT_MS = 30_000
_SQLITE_SYNCHRONOUS_MODE = "NORMAL"
_SQLITE_FILE_MODE = 0o600
_SQLITE_DIR_MODE = 0o700


def _sqlite_database_path(database_url: str) -> Path | None:
    """Return the filesystem path of a file-backed SQLite database URL.

    Memory databases (``:memory:`` and in-memory ``file:`` URIs) are exempt
    from filesystem hardening and return ``None``. The returned path is
    absolute but does not resolve symlinks, so the final path component can
    still be validated as a regular file.
    """
    database_path = make_url(database_url).database
    if not database_path or database_path == ":memory:" or database_path.startswith("file:"):
        return None
    return Path(os.path.abspath(database_path))


def _create_private_sqlite_file(path: Path) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, _SQLITE_FILE_MODE)
    try:
        os.fchmod(fd, _SQLITE_FILE_MODE)
    finally:
        os.close(fd)


def _hardened_sqlite_stat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _verify_sqlite_file_stat(path: Path, file_stat: os.stat_result) -> None:
    if stat.S_ISLNK(file_stat.st_mode):
        raise RuntimeError(
            f"Refusing SQLite database path {path}: symlink is not allowed; "
            "use a private regular file."
        )
    if not stat.S_ISREG(file_stat.st_mode):
        raise RuntimeError(f"Refusing SQLite database path {path}: expected a regular file.")
    if file_stat.st_uid != os.geteuid():
        raise RuntimeError(
            f"Refusing SQLite database path {path}: owned by uid {file_stat.st_uid}, "
            f"expected {os.geteuid()}."
        )


def _apply_private_sqlite_modes(path: Path) -> None:
    os.chmod(path, _SQLITE_FILE_MODE)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        sidecar_stat = _hardened_sqlite_stat(sidecar)
        if sidecar_stat is None:
            continue
        if stat.S_ISLNK(sidecar_stat.st_mode) or not stat.S_ISREG(sidecar_stat.st_mode):
            raise RuntimeError(
                f"Refusing SQLite sidecar file {sidecar}: expected a regular file, "
                "not a symlink or special file."
            )
        os.chmod(sidecar, _SQLITE_FILE_MODE)


def _harden_sqlite_file(path: Path) -> None:
    """Fail-closed POSIX hardening for a file-backed SQLite database."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=_SQLITE_DIR_MODE)
    if os.name != "posix":
        return
    file_stat = _hardened_sqlite_stat(path)
    if file_stat is None:
        try:
            _create_private_sqlite_file(path)
        except FileExistsError:
            pass
        file_stat = _hardened_sqlite_stat(path)
        if file_stat is None:
            raise RuntimeError(f"Failed to create SQLite database file at {path}.")
    _verify_sqlite_file_stat(path, file_stat)
    _apply_private_sqlite_modes(path)


def _configure_sqlite_connection(
    dbapi_connection: Any,
    _connection_record: Any,
    *,
    database_path: Path | None = None,
) -> None:
    if database_path is not None:
        _harden_sqlite_file(database_path)
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA journal_mode={_SQLITE_JOURNAL_MODE}")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute(f"PRAGMA synchronous={_SQLITE_SYNCHRONOUS_MODE}")
    finally:
        cursor.close()


def build_database_engine(settings: Settings) -> AsyncEngine:
    database_url = settings.a2a_database_url
    if database_url is None:
        raise ValueError("A2A_DATABASE_URL is required to build a database engine")

    url = make_url(database_url)
    sqlite_path: Path | None = None
    if url.drivername.startswith("sqlite"):
        sqlite_path = _sqlite_database_path(database_url)
        if sqlite_path is not None:
            _harden_sqlite_file(sqlite_path)

    engine = create_async_engine(
        database_url,
        pool_pre_ping=not url.drivername.startswith("sqlite"),
    )
    if url.drivername.startswith("sqlite"):
        event.listen(
            engine.sync_engine,
            "connect",
            partial(_configure_sqlite_connection, database_path=sqlite_path),
        )
    return engine
