"""Negative and positive action logging and lookup."""

import os
import csv
import io
from datetime import date
from typing import Any, Literal

from toggl.const import NEGATIVES_CSV_FILE, POSITIVES_CSV_FILE
from toggl.config import NEGATIVES, POSITIVES
from toggl.services.sync import _atomic_write


def _write_activity_csv(filepath: str, field_name: str, rows: list[dict[str, Any]]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", field_name, "Points"])
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(filepath, buf.getvalue())


def log_activity_direct(name: str, mode: Literal["positive", "negative"], entry_date: str | None = None) -> tuple[bool, str]:
    """Log a positive or negative action directly (no CLI prompts).

    Args:
        name: Activity name (case-insensitive lookup).
        mode: ``"positive"`` or ``"negative"``.
        entry_date: Date string ``YYYY-MM-DD`` for the log entry.
            Defaults to today if ``None``.

    Returns:
        (True, message) on success, (False, error_message) on failure.
    """
    lookup = POSITIVES if mode == "positive" else NEGATIVES
    lower_map = {k.lower(): k for k in lookup}
    canonical = lower_map.get(name.strip().lower())
    if not canonical:
        label = "Positive" if mode == "positive" else "Negative"
        return False, f"{label} '{name}' not found"

    csv_file = POSITIVES_CSV_FILE if mode == "positive" else NEGATIVES_CSV_FILE
    field = "Positive" if mode == "positive" else "Negative"
    alt_field = "Bonus" if mode == "positive" else "Penalty"
    sign = "+" if mode == "positive" else ""

    log_date = entry_date if entry_date else date.today().strftime("%Y-%m-%d")

    rows = []
    if os.path.exists(csv_file):
        with open(csv_file, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                val = row.get(field) or row.get(alt_field)
                rows.append({
                    "Date": row["Date"],
                    field: val,
                    "Points": row["Points"],
                })
    rows.append({
        "Date": log_date,
        field: canonical,
        "Points": lookup[canonical],
    })
    _write_activity_csv(csv_file, field, rows)
    return True, f"Logged {canonical} ({sign}{lookup[canonical]} pts)"


def delete_activity_entry(mode: Literal["positive", "negative"], date_str: str, name: str) -> tuple[bool, str]:
    """Delete a specific logged entry from the CSV.

    Args:
        mode: ``"positive"`` or ``"negative"``.
        date_str: Date of the entry to delete (``YYYY-MM-DD``).
        name: Exact activity name to delete.

    Returns:
        (True, message) on success, (False, error_message) on failure.
    """
    csv_file = POSITIVES_CSV_FILE if mode == "positive" else NEGATIVES_CSV_FILE
    field = "Positive" if mode == "positive" else "Negative"
    alt_field = "Bonus" if mode == "positive" else "Penalty"

    if not os.path.exists(csv_file):
        return False, "No log entries exist"

    rows = []
    deleted = False
    with open(csv_file, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            val = row.get(field) or row.get(alt_field)
            r_name = str(val).strip() if val else ""
            r_date = str(row.get("Date", "")).strip()
            # Delete only the first matching row (date + name)
            if not deleted and r_date == date_str and r_name == name:
                deleted = True
                continue
            rows.append({
                "Date": row["Date"],
                field: val,
                "Points": row["Points"],
            })

    if not deleted:
        return False, f"Entry '{name}' on {date_str} not found"

    _write_activity_csv(csv_file, field, rows)
    return True, f"Deleted '{name}' ({date_str})"


def update_activity_date(mode: Literal["positive", "negative"], old_date: str, name: str, new_date: str) -> tuple[bool, str]:
    """Change the date of an existing logged entry.

    Args:
        mode: ``"positive"`` or ``"negative"``.
        old_date: Current date string of the entry (``YYYY-MM-DD``).
        name: Exact activity name.
        new_date: New date string (``YYYY-MM-DD``).

    Returns:
        (True, message) on success, (False, error_message) on failure.
    """
    csv_file = POSITIVES_CSV_FILE if mode == "positive" else NEGATIVES_CSV_FILE
    field = "Positive" if mode == "positive" else "Negative"
    alt_field = "Bonus" if mode == "positive" else "Penalty"

    if not os.path.exists(csv_file):
        return False, "No log entries exist"

    rows = []
    updated = False
    with open(csv_file, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            val = row.get(field) or row.get(alt_field)
            r_name = str(val).strip() if val else ""
            r_date = str(row.get("Date", "")).strip()
            if not updated and r_date == old_date and r_name == name:
                updated = True
                rows.append({
                    "Date": new_date,
                    field: val,
                    "Points": row["Points"],
                })
            else:
                rows.append({
                    "Date": row["Date"],
                    field: val,
                    "Points": row["Points"],
                })

    if not updated:
        return False, f"Entry '{name}' on {old_date} not found"

    _write_activity_csv(csv_file, field, rows)
    return True, f"Moved '{name}' from {old_date} to {new_date}"
