"""Backup service: integrity checks, snapshot creation, and rotation.

Provides startup CSV/JSON validation and an on-demand backup system that
snapshots all local data files + config to a timestamped directory under
``data/backups/``, keeping the last N snapshots.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
from datetime import datetime, timezone

from toggl.const import (
    CONFIG_FILE,
    CSV_FILE,
    DAILY_CSV_FILE,
    DATA_DIR,
    DIR_PATH,
    HISTORY_FILE,
    NEGATIVES_CSV_FILE,
    PLAYBOOK_CACHE_FILE,
    POSITIVES_CSV_FILE,
    PROJECTS_FILE,
)

logger = logging.getLogger("TStat")

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

BACKUP_DIR = os.path.join(DATA_DIR, "backups")
MAX_BACKUPS = 5
LOG_FILE = os.path.join(DATA_DIR, "sync_debug.log")

# Map of file paths to their expected CSV headers (for integrity checks).
_CSV_HEADERS: dict[str, list[str]] = {
    CSV_FILE: ["Week", "Project", "Hours"],
    DAILY_CSV_FILE: ["Date", "Project", "Hours"],
    NEGATIVES_CSV_FILE: ["Date", "Negative", "Points"],
    POSITIVES_CSV_FILE: ["Date", "Positive", "Points"],
}

# All files that should be included in a backup snapshot.
_BACKUP_SOURCE_FILES = [
    CSV_FILE,
    DAILY_CSV_FILE,
    NEGATIVES_CSV_FILE,
    POSITIVES_CSV_FILE,
    HISTORY_FILE,
    PROJECTS_FILE,
    PLAYBOOK_CACHE_FILE,
    CONFIG_FILE,
    LOG_FILE,
]

# Directories to include recursively in each backup snapshot.
_BACKUP_SOURCE_DIRS = [
    os.path.join(DIR_PATH, "tests", "visual", "__snapshots__"),
]


# ──────────────────────────────────────────────
# Integrity checks
# ──────────────────────────────────────────────


def integrity_check() -> list[str]:
    """Validate all local data files and return a list of problems.

    Returns an empty list if everything is healthy. Each problem string
    is a human-readable description of what's wrong.
    """
    problems: list[str] = []

    for path, expected_headers in _CSV_HEADERS.items():
        if not os.path.exists(path):
            continue  # Missing files are normal for first run

        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                actual_headers = reader.fieldnames

                if actual_headers is None:
                    problems.append(f"{os.path.basename(path)}: empty or unreadable")
                    continue

                if set(actual_headers) != set(expected_headers):
                    problems.append(
                        f"{os.path.basename(path)}: unexpected headers "
                        f"{actual_headers} (expected {expected_headers})"
                    )
                    continue

                row_count = 0
                for row in reader:
                    row_count += 1
                    # Verify each row has the right number of columns
                    if len(row) != len(expected_headers):
                        problems.append(
                            f"{os.path.basename(path)}: row {row_count + 1} has "
                            f"{len(row)} columns (expected {len(expected_headers)})"
                        )
                        break  # One broken row is enough to flag the file
                    # Verify numeric Hours/Points fields are parseable
                    for numeric_col in ("Hours", "Points"):
                        if numeric_col in expected_headers:
                            try:
                                float(row.get(numeric_col, "0"))
                            except (ValueError, TypeError):
                                problems.append(
                                    f"{os.path.basename(path)}: row {row_count + 1} "
                                    f"has non-numeric {numeric_col}='{row.get(numeric_col)}'"
                                )
                                break

        except Exception as e:
            problems.append(f"{os.path.basename(path)}: read error — {e}")

    # Quick JSON file checks
    for json_path in (HISTORY_FILE, PROJECTS_FILE, PLAYBOOK_CACHE_FILE, CONFIG_FILE):
        if not os.path.exists(json_path):
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            problems.append(f"{os.path.basename(json_path)}: invalid JSON — {e}")
            continue
        except Exception as e:
            problems.append(f"{os.path.basename(json_path)}: read error — {e}")
            continue

        # Config-specific validation
        if json_path == CONFIG_FILE:
            if not isinstance(data, dict):
                problems.append("toggl_config.json: top-level must be a JSON object")
                continue
            for key in ("points", "negatives", "positives"):
                if key not in data or not isinstance(data[key], dict):
                    problems.append(f"toggl_config.json: missing or invalid '{key}' map")
            api_token = data.get("api_token")
            if api_token is not None and not isinstance(api_token, str):
                problems.append("toggl_config.json: 'api_token' must be a string")
            if api_token and len(api_token.strip()) < 10:
                problems.append("toggl_config.json: 'api_token' looks too short to be valid")

    return problems


def config_safety_check() -> str | None:
    """Lightweight pre-flight config check. Returns None if ok, or an error message.

    Designed to run before the TUI starts, so it cannot depend on any
    framework machinery. Only checks the bare minimum required to boot.
    """
    if not os.path.exists(CONFIG_FILE):
        return f"Config file not found: {CONFIG_FILE}"

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return f"Config file is invalid JSON: {e}"
    except OSError as e:
        return f"Cannot read config file: {e}"

    if not isinstance(data, dict):
        return "Config file must contain a JSON object"

    missing = [k for k in ("points", "negatives", "positives") if not data.get(k)]
    if missing:
        return f"Config is missing required section(s): {', '.join(missing)}"

    return None


def startup_integrity_check() -> str | None:
    """Run integrity check and return a summary message (or None if clean).

    Called during launcher startup. Logs problems and returns a single
    warning string suitable for display.
    """
    logger.debug("Running startup integrity check")
    problems = integrity_check()
    if not problems:
        logger.debug("Integrity check: all clean")
        return None

    for p in problems:
        logger.warning("Integrity check: %s", p)

    if len(problems) == 1:
        return f"Data integrity issue: {problems[0]}"

    return f"{len(problems)} data integrity issues detected"


# ──────────────────────────────────────────────
# Backup creation and rotation
# ──────────────────────────────────────────────


def _backup_timestamp() -> str:
    """Return a compact sortable timestamp for the backup folder name."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _backup_metadata_path(backup_folder: str) -> str:
    return os.path.join(backup_folder, "_backup_meta.json")


def create_backup() -> tuple[bool, str]:
    """Create a timestamped backup of all local data files and config.

    Returns:
        (True, timestamp_string) on success, (False, error_message) on failure.
    """
    ts = _backup_timestamp()
    dest = os.path.join(BACKUP_DIR, ts)

    try:
        os.makedirs(dest, exist_ok=True)
        copied = 0

        for src in _BACKUP_SOURCE_FILES:
            if not os.path.exists(src):
                continue
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
            copied += 1

        for src_dir in _BACKUP_SOURCE_DIRS:
            if not os.path.isdir(src_dir):
                continue
            dir_dest = os.path.join(dest, os.path.relpath(src_dir, DIR_PATH))
            shutil.copytree(src_dir, dir_dest, dirs_exist_ok=True)
            copied += 1

        # Write metadata record inside the backup
        meta = {
            "created": datetime.now(timezone.utc).isoformat(),
            "files_copied": copied,
            "source_count": len(_BACKUP_SOURCE_FILES) + len(_BACKUP_SOURCE_DIRS),
        }
        with open(_backup_metadata_path(dest), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        logger.info("Backup created: %s (%d items)", ts, copied)
        return True, ts

    except OSError as e:
        logger.exception("Backup creation failed")
        return False, str(e)


def rotate_old_backups() -> int:
    """Remove oldest backups exceeding MAX_BACKUPS. Returns count of removed."""
    if not os.path.isdir(BACKUP_DIR):
        return 0

    entries = sorted(
        [
            e
            for e in os.listdir(BACKUP_DIR)
            if os.path.isdir(os.path.join(BACKUP_DIR, e))
        ]
    )
    removed = 0
    while len(entries) > MAX_BACKUPS:
        oldest = entries.pop(0)
        shutil.rmtree(os.path.join(BACKUP_DIR, oldest), ignore_errors=True)
        removed += 1
        logger.info("Rotated old backup: %s", oldest)

    return removed


def get_last_backup() -> datetime | None:
    """Return the creation time of the most recent backup, or None."""
    if not os.path.isdir(BACKUP_DIR):
        return None

    dirs = [
        d
        for d in os.listdir(BACKUP_DIR)
        if os.path.isdir(os.path.join(BACKUP_DIR, d))
    ]
    if not dirs:
        return None

    dirs.sort(reverse=True)
    newest = dirs[0]

    meta_path = _backup_metadata_path(os.path.join(BACKUP_DIR, newest))
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            created = meta.get("created")
            if created:
                dt = datetime.fromisoformat(created)
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt
        except Exception:
            pass

    # Fallback: use the directory modification time
    mtime = os.path.getmtime(os.path.join(BACKUP_DIR, newest))
    return datetime.fromtimestamp(mtime)


def get_last_backup_str() -> str:
    """Human-readable age of the last backup (e.g. ``3h12m ago``)."""
    dt = get_last_backup()
    if dt is None:
        return "--"
    now = datetime.now()
    secs = int((now - dt).total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    rem = mins % 60
    if hrs < 24:
        return f"{hrs}h{rem}m" if rem else f"{hrs}h"
    days = hrs // 24
    hrs_rem = hrs % 24
    return f"{days}d{hrs_rem}h" if hrs_rem else f"{days}d"
