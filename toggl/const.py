"""Constants: ANSI colours, layout widths, file paths."""

import os
import re

# ──────────────────────────────────────────────
# TASK SHORT NAMES (for catchup block)
# ──────────────────────────────────────────────
TASK_SHORT_NAMES = {
    "Building Projects": "Build",
    "Finance / Markets": "Finance",
    "Learning to Code": "Code",
    "Fitness": "Fitness",
    "Learning Japanese": "Japanese",
    "Obligations / Social": "Social",
    "Personal Development": "Personal Dev",
    "Acads / Study": "Acads",
    "Plan / Org / Review": "Plan/Org",
    "Focus Thoughts": "Focus",
    "Chores / Waste": "Chores",
}

# ──────────────────────────────────────────────
# ANSI COLOURS
# ──────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# ──────────────────────────────────────────────
# VISUAL WIDTH HELPERS
# ──────────────────────────────────────────────
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(s):
    return _ANSI_RE.sub("", s)


def vlen(s):
    """Visual length of a string (ignores ANSI escape codes)."""
    return len(strip_ansi(s))


def pad_ansi(s, width):
    """Right-pad an ANSI string so its visual length equals `width`."""
    vis = vlen(s)
    if vis >= width:
        return s
    return s + " " * (width - vis)


# ──────────────────────────────────────────────
# LAYOUT CONSTANTS
# ──────────────────────────────────────────────
COL1, COL2, COL3, COL4 = 23, 8, 8, 10
TABLE_W = 2 + COL1 + 1 + COL2 + 1 + COL3 + 1 + COL4  # = 54

SPARK_PTS_W = 5
SPARK_BAR_W = 3
BLAME_W = 3

SPARK_W = (
    SPARK_PTS_W + 1 + SPARK_BAR_W + 1 + 3 + 1 + SPARK_BAR_W + 1
    + SPARK_PTS_W + 2 + BLAME_W
)  # = 28

TABLE_SPARK_GAP = 1
SPARK_START_ROW = 1

# ──────────────────────────────────────────────
# FILE PATHS
# ──────────────────────────────────────────────
DIR_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(DIR_PATH, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
CSV_FILE = os.path.join(DATA_DIR, "toggl_data.csv")
DAILY_CSV_FILE = os.path.join(DATA_DIR, "toggl_daily.csv")
NEGATIVES_CSV_FILE = os.path.join(DATA_DIR, "toggl_negatives.csv")
POSITIVES_CSV_FILE = os.path.join(DATA_DIR, "toggl_positives.csv")
HISTORY_FILE = os.path.join(DATA_DIR, "toggl_sync_history.json")
CONFIG_FILE = os.path.join(DIR_PATH, "toggl_config.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "toggl_projects.json")
BACKFILL_DB = os.path.join(DATA_DIR, "toggl_backfill.db")

DEFAULT_DAILY_TARGET = 13.0
LOW_QUOTA_WARNING = 5
PROJECTS_CACHE_MAX_AGE_DAYS = 7
