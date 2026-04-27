"""Negative and positive action logging and lookup."""

import sys
import os
import csv
import io
from datetime import date

from toggl.const import NEGATIVES_CSV_FILE, POSITIVES_CSV_FILE
from toggl.const import RED, GREEN, YELLOW, MAGENTA, BOLD, DIM, RESET
from toggl.config import NEGATIVES, POSITIVES
from toggl.api import _prompt_yes_no


def log_positive_direct(pos_name):
    lower_map = {k.lower(): k for k in POSITIVES}
    canonical = lower_map.get(pos_name.strip().lower())
    if not canonical:
        return False, f"Positive '{pos_name}' not found"
    rows = []
    if os.path.exists(POSITIVES_CSV_FILE):
        with open(POSITIVES_CSV_FILE, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if "Bonus" in row and "Positive" not in row:
                    row = {"Date": row["Date"], "Positive": row["Bonus"], "Points": row["Points"]}
                rows.append(row)
    rows.append({
        "Date": date.today().strftime("%Y-%m-%d"),
        "Positive": canonical,
        "Points": POSITIVES[canonical],
    })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Positive", "Points"])
    writer.writeheader()
    writer.writerows(rows)
    from toggl.cache import _atomic_write
    _atomic_write(POSITIVES_CSV_FILE, buf.getvalue())
    return True, f"Logged {canonical} (+{POSITIVES[canonical]} pts)"


def log_negative_direct(neg_name):
    lower_map = {k.lower(): k for k in NEGATIVES}
    canonical = lower_map.get(neg_name.strip().lower())
    if not canonical:
        return False, f"Negative '{neg_name}' not found"
    rows = []
# NEW
    if os.path.exists(NEGATIVES_CSV_FILE):
        with open(NEGATIVES_CSV_FILE, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if "Penalty" in row and "Negative" not in row:
                    row = {"Date": row["Date"], "Negative": row["Penalty"], "Points": row["Points"]}
                rows.append(row)
    rows.append({
        "Date": date.today().strftime("%Y-%m-%d"),
        "Negative": canonical,
        "Points": NEGATIVES[canonical],
    })
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["Date", "Negative", "Points"])
    writer.writeheader()
    writer.writerows(rows)
    from toggl.cache import _atomic_write
    _atomic_write(NEGATIVES_CSV_FILE, buf.getvalue())
    return True, f"Logged {canonical} (-{NEGATIVES[canonical]} pts)"


def log_positive(pos_name):
    lower_map = {k.lower(): k for k in POSITIVES}
    canonical = lower_map.get(pos_name.strip().lower())
    if not canonical:
        print(f"{RED}Positive '{pos_name}' not found.{RESET}")
        sys.exit(1)
    cost = POSITIVES[canonical]
    if not _prompt_yes_no(
        f"{YELLOW}Log positive '{canonical}' for +{cost} pts? (y/n): {RESET}"
    ):
        print(f"{DIM}Action cancelled.{RESET}")
        sys.exit(0)
    ok, message = log_positive_direct(canonical)
    if ok:
        print(f"\n{GREEN}✓ {message}{RESET}\n")
    else:
        print(f"\n{RED}✗ {message}{RESET}\n")
    sys.exit(0)


def log_negative(neg_name):
    lower_map = {k.lower(): k for k in NEGATIVES}
    canonical = lower_map.get(neg_name.strip().lower())
    if not canonical:
        print(f"{RED}Negative '{neg_name}' not found.{RESET}")
        print(f"{DIM}Run --negative for the picker or -n for the catalog.{RESET}")
        sys.exit(1)
    cost = NEGATIVES[canonical]
    if not _prompt_yes_no(
        f"{YELLOW}Log negative '{canonical}' for -{cost} pts? (y/n): {RESET}"
    ):
        print(f"{DIM}Action cancelled.{RESET}")
        sys.exit(0)
    ok, message = log_negative_direct(canonical)
    if ok:
        print(f"\n{RED}✓ {message}{RESET}\n")
    else:
        print(f"\n{RED}✗ {message}{RESET}\n")
    sys.exit(0)


def pick_positive_interactive():
    names = list(POSITIVES.keys())
    print(f"\n  {BOLD}{GREEN}POSITIVES{RESET}")
    print("  " + "─" * 35)
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name:<25} {GREEN}+{POSITIVES[name]:>4.1f}{RESET}")
    print()
    while True:
        try:
            choice = input(f"  {YELLOW}Enter number: {RESET}").strip()
            if not choice:
                return None
            index = int(choice)
            if 1 <= index <= len(names):
                return names[index - 1]
        except (ValueError, IndexError):
            pass
        print(f"{YELLOW}Please enter a valid number from the list.{RESET}")


def pick_negative_interactive():
    names = list(NEGATIVES.keys())
    print(f"\n  {BOLD}{RED}NEGATIVES{RESET}")
    print("  " + "─" * 35)
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name:<25} {MAGENTA}-{NEGATIVES[name]:>4.1f}{RESET}")
    print()
    while True:
        try:
            choice = input(f"  {YELLOW}Enter number: {RESET}").strip()
            if not choice:
                return None
            index = int(choice)
            if 1 <= index <= len(names):
                return names[index - 1]
        except (ValueError, IndexError):
            pass
        print(f"{YELLOW}Please enter a valid number from the list.{RESET}")


def print_pos_log(group_by="week"):
    from toggl.cache import get_week_str, get_week_dates
    if not os.path.exists(POSITIVES_CSV_FILE):
        print(f"{YELLOW}No positives logged yet.{RESET}")
        return
    rows = []
    with open(POSITIVES_CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                from datetime import datetime
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                name = row.get("Positive") or row.get("Bonus") or "?"
                pts = float(row["Points"])
                rows.append((d, name, pts))
            except (KeyError, ValueError):
                continue
    if not rows:
        print(f"{YELLOW}No positives logged yet.{RESET}")
        return
    rows.sort(key=lambda x: x[0])
    groups: dict[str, list] = {}
    for d, name, pts in rows:
        key = d.strftime("%Y-%m") if group_by == "month" else get_week_str(d)
        groups.setdefault(key, []).append((d, name, pts))
    print(f"\n  {BOLD}{GREEN}POSITIVES LOG{RESET}  {DIM}· by {group_by}{RESET}")
    for key in sorted(groups.keys()):
        entries = groups[key]
        if group_by == "week":
            from datetime import datetime
            start_d, end_d = get_week_dates(key)
            header = f"{BOLD}{key}{RESET}  {DIM}({start_d.strftime('%d %b')} – {end_d.strftime('%d %b %Y')}){RESET}"
        else:
            from datetime import datetime
            header = f"{BOLD}{datetime.strptime(key, '%Y-%m').strftime('%B %Y')}{RESET}"
        group_total = sum(p for _, _, p in entries)
        print(f"\n  {header}")
        print("  " + "─" * 50)
        for d, name, pts in entries:
            date_str = d.strftime("%a %d %b")
            print(f"    {DIM}{date_str:<12}{RESET}  {name:<26} {GREEN}+{pts:.0f} pts{RESET}")
        print(f"  {'':>42} {GREEN}{BOLD}+{group_total:.0f} pts total{RESET}")
    print()


def print_neg_log(group_by="week"):
    from toggl.cache import get_week_str, get_week_dates
    if not os.path.exists(NEGATIVES_CSV_FILE):
        print(f"{YELLOW}No negatives logged yet.{RESET}")
        return
    rows = []
    with open(NEGATIVES_CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                from datetime import datetime
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                name = row.get("Negative") or row.get("Penalty") or "?"
                pts = float(row["Points"])
                rows.append((d, name, pts))
            except (KeyError, ValueError):
                continue
    if not rows:
        print(f"{YELLOW}No negatives logged yet.{RESET}")
        return
    rows.sort(key=lambda x: x[0])
    groups: dict[str, list] = {}
    for d, name, pts in rows:
        key = d.strftime("%Y-%m") if group_by == "month" else get_week_str(d)
        groups.setdefault(key, []).append((d, name, pts))
    print(f"\n  {BOLD}{CYAN}NEGATIVES LOG{RESET}  {DIM}· by {group_by}{RESET}")
    for key in sorted(groups.keys()):
        entries = groups[key]
        if group_by == "week":
            from datetime import datetime
            start_d, end_d = get_week_dates(key)
            header = f"{BOLD}{key}{RESET}  {DIM}({start_d.strftime('%d %b')} – {end_d.strftime('%d %b %Y')}){RESET}"
        else:
            from datetime import datetime
            header = f"{BOLD}{datetime.strptime(key, '%Y-%m').strftime('%B %Y')}{RESET}"
        group_total = sum(p for _, _, p in entries)
        print(f"\n  {header}")
        print("  " + "─" * 50)
        for d, name, pts in entries:
            date_str = d.strftime("%a %d %b")
            print(f"    {DIM}{date_str:<12}{RESET}  {name:<26} {MAGENTA}-{pts:.0f} pts{RESET}")
        print(f"  {'':>42} {RED}{BOLD}-{group_total:.0f} pts total{RESET}")
    print()
