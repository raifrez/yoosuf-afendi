"""Publish a generated population to a shared data folder and rebuild its database."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REQUIRED_FILES = (
    "islands.parquet", "households.parquet", "persons.parquet",
    "population_groups.parquet", "journey_requests.parquet",
    "manifest.json", "generation_report.json", "preview.json",
)


def publish_run(source, shared_data):
    """Retain the previous Parquet snapshot if the shared database build fails."""
    source, shared_data = Path(source).resolve(), Path(shared_data).resolve()
    builder = shared_data / "build.py"
    if not builder.is_file():
        raise ValueError(f"Shared database builder is missing: {builder}")
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise ValueError(f"Incomplete generated population: {missing}")
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("schema_version") != "1.0" or manifest.get("synthetic") is not True:
        raise ValueError("Expected a version 1.0 synthetic population manifest")
    processed = shared_data / "processed"
    processed.mkdir(exist_ok=True)
    destination = processed / "population"
    if source == destination:
        raise ValueError("Use the immutable generation output as source, not the shared destination")
    temporary = Path(tempfile.mkdtemp(prefix=".population-publish-", dir=processed))
    working, backup = temporary / "new", temporary / "previous"
    working.mkdir()
    had_previous = destination.exists()
    published = False
    try:
        for name in REQUIRED_FILES:
            shutil.copy2(source / name, working / name)
        if had_previous:
            destination.rename(backup)
        try:
            working.rename(destination)
            published = True
            subprocess.run([sys.executable, str(builder)], cwd=shared_data.parent, check=True)
        except BaseException:
            if published:
                shutil.rmtree(destination)
            if had_previous:
                backup.rename(destination)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        # Preserve the backup if restoring the previous snapshot itself failed.
        if not backup.exists():
            shutil.rmtree(temporary)
    return shared_data / "database/shared.duckdb"
