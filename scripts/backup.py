#!/usr/bin/env python3
"""Create a consistent online backup of the Novin SQLite catalog."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


def create_backup(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise ValueError(f"source database does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    if source == destination:
        raise ValueError("source and destination must differ")
    if not destination.parent.is_dir():
        raise ValueError(f"destination directory does not exist: {destination.parent}")

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)

    try:
        with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as source_connection:
            with sqlite3.connect(temporary) as destination_connection:
                source_connection.backup(destination_connection)
                result = destination_connection.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError(f"backup integrity check failed: {result}")
        with temporary.open("rb") as backup_file:
            os.fsync(backup_file.fileno())
        os.link(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="source SQLite database")
    parser.add_argument("destination", type=Path, help="new backup file")
    arguments = parser.parse_args()

    try:
        destination = create_backup(arguments.source, arguments.destination)
    except Exception as error:
        print(f"backup failed: {error}", file=sys.stderr)
        return 1

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
