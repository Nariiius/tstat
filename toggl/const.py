"""Constants: ANSI colours and file paths."""

import os

__version__ = "1.5.0"

# ──────────────────────────────────────────────
# ANSI COLOURS
# ──────────────────────────────────────────────
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

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

DEFAULT_DAILY_TARGET = 13.0
LOW_QUOTA_WARNING = 5
PROJECTS_CACHE_MAX_AGE_DAYS = 7

PLAYBOOK_CACHE_FILE = os.path.join(DATA_DIR, "toggl_insights_bundle.json")
