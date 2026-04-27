#!/usr/bin/env python3
"""
TogglTrack.py — Toggl Track API → Life Points Calculator

Usage:
  python3 TogglTrack.py                 # Launch TUI (default)
  python3 TogglTrack.py --update        # Sync current week only (uses cached projects)
  python3 TogglTrack.py --update-all    # Full sync: refresh projects + last 4 weeks
  python3 TogglTrack.py --update-all 8  # Full sync: refresh projects + last 8 weeks

  # Weekly Views (reads toggl_data.csv - Weeks start on SUNDAY)
  python3 TogglTrack.py --week          # Show detailed dashboard for the CURRENT week
  python3 TogglTrack.py --week YYNN     # Show specific week (e.g. 2616)

  # Daily Views (reads toggl_daily.csv - current week only)
  python3 TogglTrack.py --today         # Show today's points
  python3 TogglTrack.py --yesterday     # Show yesterday's points
  python3 TogglTrack.py --day mon       # Show specific day (sun, mon, tue, etc.)

  # Negatives System
  python3 TogglTrack.py --negatives       # View the catalog of negative actions
  python3 TogglTrack.py --negative        # Pick a negative action interactively
  python3 TogglTrack.py --negative "Name" # Log a negative action by name
  python3 TogglTrack.py --neg-log         # Show negatives log grouped by week (default)
  python3 TogglTrack.py --neg-log month   # Show negatives log grouped by month

  # API Quota
  python3 TogglTrack.py --quota           # Show remaining API requests & time until reset
"""

import sys
import argparse
from datetime import date, timedelta

from toggl.const import RED, GREEN, DIM, BOLD, RESET
from toggl.config import load_runtime_settings
from toggl.cache import get_current_week, reset_cache, sync_current_week_light, sync_api_to_csv
from toggl.api import (
    TogglRateLimitError, TogglAPIError,
    _reset_api_stats, get_api_token, _print_api_usage_summary,
)
from toggl.cli import (
    get_report_sections, print_report, print_recovery_cli,
    print_neg_catalog, print_pos_catalog, _parse_day_arg,
)
from toggl.neg import (
    log_positive, log_negative, pick_positive_interactive, pick_negative_interactive,
    print_pos_log, print_neg_log,
)
from toggl.tui import TogglTUI


def main():
    try:
        _main()
    except TogglRateLimitError as e:
        print(f"\n  {RED}{BOLD}{e}{RESET}")
        sys.exit(1)
    except TogglAPIError as e:
        print(f"\n  {RED}{e}{RESET}")
        sys.exit(1)


def _main():
    load_runtime_settings()

    if len(sys.argv) == 1:
        TogglTUI().run()
        return

    parser = argparse.ArgumentParser(description="Toggl Track Life Points CLI")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--update-all", type=int, nargs='?', const=4)
    parser.add_argument("--week", type=str, nargs='?', const=get_current_week())
    parser.add_argument("--today", action="store_true")
    parser.add_argument("--yesterday", action="store_true")
    parser.add_argument("--day", type=str)
    parser.add_argument("--negatives", action="store_true")
    parser.add_argument("--negative", type=str, nargs='?', const="")
    parser.add_argument("--neg-log", type=str, nargs='?', const="week")
    parser.add_argument("--positives", action="store_true")
    parser.add_argument("--positive", type=str, nargs='?', const="")
    parser.add_argument("--pos-log", type=str, nargs='?', const="week")
    parser.add_argument("--quota", action="store_true")
    parser.add_argument("--recovery", action="store_true")

    args = parser.parse_args()

    if args.update:
        result = sync_current_week_light()
        reset_cache()
        if result["success"]:
            print(f"{GREEN}✓ {result['message']}{RESET}")
        else:
            print(f"{DIM}{result.get('message', 'Sync skipped')}{RESET}")
    elif args.update_all is not None:
        result = sync_api_to_csv(weeks_back=args.update_all)
        reset_cache()
        if result["success"]:
            print(f"{GREEN}✓ {result['message']}{RESET}")
        else:
            print(f"{DIM}{result.get('message', 'Sync skipped')}{RESET}")
    elif args.quota:
        _reset_api_stats()
        get_api_token()
        _print_api_usage_summary()
    elif args.negatives:
        print_neg_catalog()
    elif args.negative is not None:
        if args.negative == "":
            neg_name = pick_negative_interactive()
            if neg_name: log_negative(neg_name)
        else:
            log_negative(args.negative)
    elif args.neg_log:
        print_neg_log(args.neg_log)
    elif args.positives:
        print_pos_catalog()
    elif args.positive is not None:
        if args.positive == "":
            pos_name = pick_positive_interactive()
            if pos_name: log_positive(pos_name)
        else:
            log_positive(args.positive)
    elif args.pos_log:
        print_pos_log(args.pos_log)
    elif args.today:
        d_str = date.today().strftime("%Y-%m-%d")
        report = get_report_sections(d_str, "DAY")
        print_report(report["results"], report["negative_results"], report["positive_results"], d_str, "DAY")
    elif args.yesterday:
        d_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        report = get_report_sections(d_str, "DAY")
        print_report(report["results"], report["negative_results"], report["positive_results"], d_str, "DAY")
    elif args.day:
        d_str = _parse_day_arg(args.day)
        if d_str is None:
            print(f"{RED}Error: --day requires a value (e.g. mon, today, YYYY-MM-DD){RESET}")
            sys.exit(1)
        report = get_report_sections(d_str, "DAY")
        print_report(report["results"], report["negative_results"], report["positive_results"], d_str, "DAY")
    elif args.week:
        report = get_report_sections(args.week, "WEEK")
        print_report(report["results"], report["negative_results"], report["positive_results"], args.week, "WEEK")
    elif args.recovery:
        report = get_report_sections("ALL_TIME", "ALL")
        print_recovery_cli(report["results"], report["negative_results"], report["positive_results"], "ALL_TIME", "ALL")
    else:
        report = get_report_sections("ALL_TIME", "ALL")
        print_report(report["results"], report["negative_results"], report["positive_results"], "ALL_TIME", "ALL")


if __name__ == "__main__":
    main()
