"""Negative and positive action logging and lookup."""

import os
import csv
import io
from datetime import date
from typing import Literal

from toggl.const import NEGATIVES_CSV_FILE, POSITIVES_CSV_FILE
from toggl.const import RED, GREEN, YELLOW, MAGENTA, BOLD, DIM, RESET
from toggl.config import NEGATIVES, POSITIVES


def log_activity_direct(name: str, mode: Literal["positive", "negative"]) -> tuple[bool, str]:
    """Log a positive or negative action directly (no CLI prompts).

    Args:
        name: Activity name (case-insensitive lookup).
        mode: ``"positive"`` or ``"negative"``.

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
        "Date": date.today().strftime("%Y-%m-%d"),
        field: canonical,
        "Points": lookup[canonical],
    })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", field, "Points"])
    writer.writeheader()
    writer.writerows(rows)
    from toggl.cache import _atomic_write
    _atomic_write(csv_file, buf.getvalue())
    return True, f"Logged {canonical} ({sign}{lookup[canonical]} pts)"


def log_positive_direct(pos_name: str) -> tuple[bool, str]:
    """Log a positive action. Convenience wrapper around ``log_activity_direct``."""
    return log_activity_direct(pos_name, "positive")


def log_negative_direct(neg_name: str) -> tuple[bool, str]:
    """Log a negative action. Convenience wrapper around ``log_activity_direct``."""
    return log_activity_direct(neg_name, "negative")

