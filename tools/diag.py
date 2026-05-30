#!/usr/bin/env python3
"""Diagnostic: dump sync+backfill status to stdout.  Run from repo root."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from toggl.tui import get_sync_status_data


def main():
    status = get_sync_status_data()

    print("\n=== Sync Status ===")
    for key in ("current_week", "last_updated", "synced_weeks", "synced_days",
                "quota_remaining", "quota_limit", "quota_resets_in",
                "projects_cache_age_days"):
        val = status.get(key, "—")
        print(f"  {key:24s} {val}")

    bf = status.get("backfill_status", {})
    bf_status = bf.get("status")
    weeks_done = bf.get("weeks_backfilled", 0)
    weeks_total = bf.get("weeks_discovered", 0) or bf.get("total_weeks", 0)
    weeks_left = bf.get("weeks_remaining", 0)
    requests_used = bf.get("requests_used", 0)
    requests_needed = bf.get("requests_needed", 0)
    q_rem = status.get("quota_remaining")
    q_limit = status.get("quota_limit")

    print("\n=== Backfill Status ===")
    print(f"  {'Status:':24s} {bf_status} ({bf.get('stopped_reason', '-')})")
    print(f"  {'Earliest week:':24s} {bf.get('earliest_week', '—')}")
    print(f"  {'Last completed:':24s} {bf.get('last_completed_week', '—')}")
    print(f"  {'Weeks done:':24s} {weeks_done} / {weeks_total}")
    print(f"  {'Weeks remaining:':24s} {weeks_left}")
    print(f"  {'Requests used:':24s} {requests_used}")
    print(f"  {'Requests needed:':24s} {requests_needed}")
    if q_rem is not None and weeks_left > 0:
        possible = min(int(q_rem), weeks_left)
        print(f"  {'Quota → possible:':24s} {q_rem}/{q_limit} → ~{possible} weeks/hr")
    if weeks_total > 0:
        pct = min(100, int(weeks_done / weeks_total * 100))
        print(f"  {'Progress:':24s} {pct}% ({weeks_done}/{weeks_total})")
    print()

    # JSON dump for scripting
    if "--json" in sys.argv:
        # Clean non-serializable values
        out = dict(status)
        out["backfill_status"] = dict(out.get("backfill_status", {}))
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
