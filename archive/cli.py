"""CLI output functions, sparkbar, and report printing."""

import sys
import os
from datetime import datetime, date, timedelta

from toggl.const import (
    GREEN, RED, YELLOW, CYAN, MAGENTA, BLUE, BOLD, DIM, RESET,
    TABLE_W, SPARK_W, BLAME_W, SPARK_BAR_W, SPARK_PTS_W,
)
from toggl.config import POINTS, NEGATIVES, POSITIVES, get_daily_target
from toggl.cache import (
    DataCache, get_cache, reset_cache,
    get_current_week, get_week_dates, get_sunday_of_week, get_week_str,
    needs_auto_update, get_last_updated_str, _load_history,
)
from toggl.calc import calculate, format_signed, get_negative_catalog_rows, get_positive_catalog_rows
from toggl.api import (
    API_RUN_STATS, _reset_api_stats, _print_api_usage_summary,
    get_api_token, check_quota,
    TogglRateLimitError, TogglAPIError,
)
from toggl.neg import (
    log_positive, log_negative, log_positive_direct, log_negative_direct,
    pick_positive_interactive, pick_negative_interactive,
    print_pos_log, print_neg_log,
)
from toggl.cache import sync_current_week_light, sync_api_to_csv


# ── Standalone query wrappers (delegate to DataCache singleton) ──

def get_negatives_for_context(label, context_type):
    return get_cache().get_negatives_for_context(label, context_type)

def get_positives_for_context(label, context_type):
    return get_cache().get_positives_for_context(label, context_type)

def get_data_for_week(target_week):
    return get_cache().get_week_projects(target_week)

def get_data_for_day(target_day):
    return get_cache().get_day_projects(target_day)

def get_all_time_data():
    return get_cache().get_all_time_projects()

def get_negative_log_rows(limit=30):
    return get_cache().get_negative_log_rows(limit)

def get_positive_log_rows(limit=30):
    return get_cache().get_positive_log_rows(limit)

def get_day_metrics(day_str):
    return get_cache().get_day_metrics(day_str)

def get_week_dashboard_rows(label):
    return get_cache().get_week_dashboard_rows(label)

def get_report_sections(label, context_type):
    return get_cache().get_report_sections(label, context_type)

def get_recovery_rows(label, context_type):
    return get_cache().get_recovery_rows(label, context_type)

def get_week_neg_breakdown(week_str):
    return get_cache().get_week_neg_breakdown(week_str)

def get_week_pos_breakdown(week_str):
    return get_cache().get_week_pos_breakdown(week_str)

def get_sync_status_data():
    history = _load_history()
    from toggl.api import get_projects_cache_age_days
    return {
        "last_updated": get_last_updated_str(),
        "projects_cache_age_days": get_projects_cache_age_days(),
        "current_week": get_current_week(),
        "synced_weeks": history.get("synced_weeks", {}),
        "synced_days": history.get("synced_days", {}),
        "quota_remaining": API_RUN_STATS["remaining"],
        "quota_limit": API_RUN_STATS["limit"],
        "quota_resets_in": API_RUN_STATS["resets_in"],
    }

def get_sparkbar_text():
    return "\n".join(build_week_sparkbar_lines())


# ── CLI Print Functions ──

def print_neg_catalog():
    print(f"\n  {BOLD}{RED}NEGATIVES CATALOG{RESET}")
    print("  " + "─" * 35)
    for name, points in get_negative_catalog_rows():
        print(f"  {name:<25} {MAGENTA}-{points:>4.1f}{RESET}")
    print()

def print_pos_catalog():
    print(f"\n  {BOLD}{GREEN}POSITIVES CATALOG{RESET}")
    print("  " + "─" * 35)
    for name, points in get_positive_catalog_rows():
        print(f"  {name:<25} {GREEN}+{points:>4.1f}{RESET}")
    print()

def _parse_day_arg(arg):
    if not arg: return None
    arg = arg.lower()
    if arg == "today": return date.today().strftime("%Y-%m-%d")
    if arg == "yesterday": return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    days = {"sun":0, "mon":1, "tue":2, "wed":3, "thu":4, "fri":5, "sat":6}
    if arg in days:
        target_weekday = days[arg]
        today_weekday = (date.today().weekday() + 1) % 7
        diff = (today_weekday - target_weekday) % 7
        return (date.today() - timedelta(days=diff)).strftime("%Y-%m-%d")
    return arg

def print_weekly_dashboard(label):
    start_d, end_d = get_week_dates(label)
    cache = get_cache()
    print(f"\n  {BOLD}{CYAN}DAILY BREAKDOWN{RESET} {DIM}({label}){RESET}")
    table_width = 85
    print("  " + "─" * table_width)
    print(
        f"  {BOLD}{'Day':<10} {'Date':<8} {'Hours':>8} {'Earned':>9} {'Pos':>8} {'Negs':>8} {'Goal':>8} {'Δ':>8} {'Net':>8}{RESET}"
    )
    print("  " + "─" * table_width)
    has_data = False
    cumulative_net = 0.0
    cumulative_days = 0
    cutoff = min(end_d, date.today()) if label == get_current_week() else end_d
    for i in range(7):
        d = start_d + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        day_name = d.strftime("%A")[:3]
        date_short = d.strftime("%d %b")
        projs = cache.daily_data.get(d_str, {})
        neg_entries = cache.negatives_raw.get(d_str, [])
        pos_entries = cache.positives_raw.get(d_str, [])
        if not projs and not neg_entries and not pos_entries and d > date.today():
            continue
        has_data = True
        results = calculate(projs)
        earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
        tracked_neg = sum(abs(r[3]) for r in results if r[3] is not None and r[3] < 0)
        hours = sum(projs.values())
        neg_cost = sum(e["points"] for e in neg_entries)
        pos_bonus = sum(e["points"] for e in pos_entries)
        net = earned - tracked_neg - neg_cost + pos_bonus
        h_str = f"{hours:.1f}h" if hours > 0 else "—"
        e_str = (
            f"+{earned:.1f}"
            if earned > 0
            else (f"{earned:.1f}" if earned < 0 else "0.0")
        )
        if earned == 0 and hours == 0:
            e_str = "—"
        p_str = f"+{pos_bonus:.1f}" if pos_bonus > 0 else "—"
        n_str = f"-{neg_cost:.1f}" if neg_cost > 0 else "—"
        g_str = f"{get_daily_target():.0f}"
        delta = net - get_daily_target()
        d_str_fmt = format_signed(delta)
        net_str = format_signed(net)
        if d <= cutoff:
            cumulative_net += net
            cumulative_days += 1
        print(
            f"  {day_name:<10} {date_short:<8} {h_str:>8} {e_str:>9} {p_str:>8} {n_str:>8} {g_str:>8} {d_str_fmt:>8} {net_str:>8}"
        )
    print("  " + "─" * table_width)
    expected = round(get_daily_target() * cumulative_days, 1)
    actual = round(cumulative_net, 1)
    delta = round(actual - expected, 1)
    print(
        f"  {'Cumulative':<10} {'':8} {'':8} {'':9} {'':8} {'':8} {expected:>8.0f} {format_signed(delta):>8} {format_signed(actual):>8}"
    )
    print()
    if not has_data and label != get_current_week():
        print(f"  {DIM}Daily breakdown is only available for the current week.{RESET}")
    print()


# ── Sparkbar Helpers ──

def build_blame_bar(tracked, logged, n=BLAME_W):
    total = tracked + logged
    if total == 0:
        return " " * n
    red_count = round(tracked / total * n)
    mag_count = n - red_count
    return f"{RED}{'█' * red_count}{RESET}{MAGENTA}{'█' * mag_count}{RESET}"


def time_left_in_week():
    now = datetime.now()
    current_sunday = get_sunday_of_week(date.today())
    end_of_sat = datetime.combine(
        current_sunday + timedelta(days=6), datetime.max.time()
    )
    diff = end_of_sat - now
    if diff.total_seconds() <= 0:
        return "0h"
    total_secs = int(diff.total_seconds())
    days = total_secs // 86400
    hours = (total_secs % 86400) // 3600
    return f"{days}d {hours:02d}h" if days > 0 else f"{hours}h"


def build_week_sparkbar_lines(week_str=None):
    week_str = week_str or get_current_week()
    start_d, _ = get_week_dates(week_str)
    cache = get_cache()

    day_data = []
    for i in range(7):
        d = start_d + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        projs = cache.daily_data.get(d_str, {})
        neg_entries = cache.negatives_raw.get(d_str, [])
        pos_entries = cache.positives_raw.get(d_str, {})

        results = calculate(projs)
        earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
        logged_neg = sum(e["points"] for e in neg_entries)
        logged_pos = sum(e["points"] for e in pos_entries)
        tracked_neg = sum(
            abs(r[3]) for r in results if r[3] is not None and r[3] < 0
        )
        net = round(earned - tracked_neg - logged_neg + logged_pos, 1)
        if abs(net) < 0.05:
            net = 0.0

        day_data.append(
            {
                "name": d.strftime("%a"),
                "net": net,
                "tracked_neg": round(tracked_neg, 1),
                "logged_neg": round(logged_neg, 1),
                "logged_pos": round(logged_pos, 1),
                "is_today": d == date.today(),
                "future": d > date.today(),
                "has_data": bool(projs or neg_entries or pos_entries),
            }
        )

    nonzero = [abs(dd["net"]) for dd in day_data if dd["has_data"] and dd["net"] != 0]
    max_abs = max(nonzero, default=1)

    lines: list[str] = []

    BOX_W = SPARK_W + 2
    title_p4w = f" Past 4 Weeks "
    title_p4w_vis = len(title_p4w)
    top_border_p4w = "┌" + f"{BOLD}{CYAN}{title_p4w}{RESET}" + "─" * (BOX_W - title_p4w_vis - 2) + "┐"
    lines.append(top_border_p4w)

    current_sunday = get_sunday_of_week(date.today())

    past_weeks_data = []
    max_abs_pw = 0.1

    for i in range(3, 0, -1):
        pw_sunday = current_sunday - timedelta(days=7 * i)
        pw = get_week_str(pw_sunday)
        pw_num = pw.split("W")[1]
        pw_label = f"W{int(pw_num)}"

        pw_data = get_data_for_week(pw)
        if pw_data:
            pw_results = calculate(pw_data)
            pw_earned = sum(r[3] for r in pw_results if r[3] is not None and r[3] > 0)
            pw_tracked_neg = sum(abs(r[3]) for r in pw_results if r[3] is not None and r[3] < 0)
        else:
            pw_earned = 0.0
            pw_tracked_neg = 0.0

        pw_tracked, pw_logged = get_week_neg_breakdown(pw)
        pw_logged_pos = get_week_pos_breakdown(pw)
        pw_net = round(pw_earned - pw_tracked_neg - pw_logged + pw_logged_pos, 1)

        max_abs_pw = max(max_abs_pw, abs(pw_net))
        past_weeks_data.append(
            {
                "label": pw_label,
                "net": pw_net,
                "tracked_neg": pw_tracked,
                "logged_neg": pw_logged,
            }
        )

    for pw in past_weeks_data:
        net = pw["net"]
        tracked = pw["tracked_neg"]
        logged = pw["logged_neg"]
        bar = _build_spark_ansi(net, max_abs_pw, tracked=tracked, logged=logged)
        label = pw["label"]
        pts_str = format_signed(net)
        lines.append(f"│ {BOLD}{label}{RESET} {bar} {pts_str:>7} │")

    # Current week header
    title_cw = f" Current Week ({week_str}) "
    title_cw_vis = len(title_cw)
    mid_border = "├" + f"{BOLD}{CYAN}{title_cw}{RESET}" + "─" * (BOX_W - title_cw_vis - 2) + "┤"
    lines.append(mid_border)

    for dd in day_data:
        if dd["future"] and not dd["has_data"]:
            continue
        net = dd["net"]
        tracked = dd["tracked_neg"]
        logged = dd["logged_neg"]
        bar = _build_spark_ansi(net, max_abs, tracked=tracked, logged=logged)
        name = dd["name"]
        marker = "▸" if dd["is_today"] else " "
        pts_str = format_signed(net)
        lines.append(f"│{marker}{name} {bar} {pts_str:>7} │")

    # Catch-up section
    from toggl.const import TASK_SHORT_NAMES
    all_time = get_all_time_data() or {}
    all_results = calculate(all_time)
    all_neg = get_negatives_for_context("ALL_TIME", "ALL")
    all_pos = get_positives_for_context("ALL_TIME", "ALL")
    all_earned = sum(r[3] for r in all_results if r[3] is not None and r[3] > 0)
    all_tracked_neg = sum(abs(r[3]) for r in all_results if r[3] is not None and r[3] < 0)
    all_logged_neg = sum(abs(r[3]) for r in all_neg)
    all_logged_pos = sum(r[3] for r in all_pos)
    all_net = round(all_earned - all_tracked_neg - all_logged_neg + all_logged_pos, 1)

    if all_net < 0:
        deficit = abs(all_net)
        title_cu = f" Catch Up ({format_signed(all_net)} pts) "
        title_cu_vis = len(title_cu)
        cu_border = "├" + f"{BOLD}{RED}{title_cu}{RESET}" + "─" * (BOX_W - title_cu_vis - 2) + "┤"
        lines.append(cu_border)

        rates_sorted = sorted(
            [(name, rate) for name, rate in POINTS.items() if rate > 0],
            key=lambda item: -item[1],
        )
        group_colors = [RED, YELLOW, GREEN, CYAN, BLUE, MAGENTA]
        for i, (name, rate) in enumerate(rates_sorted):
            hours_needed = deficit / rate
            h = int(hours_needed)
            m = int((hours_needed - h) * 60)
            h_str = f"{h}h {m:02d}m"
            rate_str = f"×{int(rate) if rate == int(rate) else rate}"
            short = [TASK_SHORT_NAMES.get(t) or t for t in [name]]
            task_str = " ".join(short)
            color = group_colors[i % len(group_colors)]
            lines.append(f"│ {color}{h_str:<8}{rate_str:<5}{task_str}{RESET}│")

    bot_border = "└" + "─" * (BOX_W - 2) + "┘"
    lines.append(bot_border)
    return lines


def _build_spark_ansi(net, max_abs, tracked=0, logged=0):
    """Build ANSI sparkbar string."""
    if max_abs == 0:
        max_abs = 1
    ratio = net / max_abs if max_abs else 0
    half = SPARK_BAR_W
    if ratio >= 0:
        pos_blocks = min(round(ratio * half), half)
        neg_blocks = 0
    else:
        neg_blocks = min(round(abs(ratio) * half), half)
        pos_blocks = 0

    axis = f"{DIM}│{RESET}"
    pos_bar = f"{GREEN}{'█' * pos_blocks}{RESET}" if pos_blocks else ""
    neg_bar = f"{RED}{'█' * neg_blocks}{RESET}" if neg_blocks else ""
    blame = build_blame_bar(tracked, logged)

    left_pad = " " * (half - pos_blocks)
    right_pad = " " * (half - neg_blocks)

    return f"{left_pad}{pos_bar}{axis}{neg_bar}{right_pad} {blame}"


def print_recovery_cli(results, negative_results, positive_results, label, context_type):
    from toggl.const import TASK_SHORT_NAMES
    all_earned = sum(r[3] for r in results if r[3] is not None and r[3] > 0)
    all_tracked_neg = sum(abs(r[3]) for r in results if r[3] is not None and r[3] < 0)
    all_logged_neg = sum(abs(r[3]) for r in negative_results)
    all_logged_pos = sum(r[3] for r in positive_results)
    total_pts = round(all_earned - all_tracked_neg - all_logged_neg + all_logged_pos, 1)
    if total_pts >= 0:
        print(f"\n  {GREEN}{BOLD}No deficit — you're ahead!{RESET}")
        return
    deficit = abs(total_pts)
    print(f"\n  {RED}{BOLD}DEFICIT: {format_signed(total_pts)} pts{RESET}")
    print(f"  {DIM}Hours needed in each positive category to break even:{RESET}\n")
    rates_sorted = sorted(
        [(name, rate) for name, rate in POINTS.items() if rate > 0],
        key=lambda item: -item[1],
    )
    group_colors = [RED, YELLOW, GREEN, CYAN, BLUE, MAGENTA]
    for i, (name, rate) in enumerate(rates_sorted):
        hours_needed = deficit / rate
        h = int(hours_needed)
        m = int((hours_needed - h) * 60)
        h_str = f"{h}h {m:02d}m"
        rate_str = f"×{int(rate) if rate == int(rate) else rate}"
        short: list[str] = [TASK_SHORT_NAMES.get(t) or t for t in [name]]
        task_str = " ".join(short)
        color_ansi = group_colors[i % len(group_colors)]
        remaining_rates = len(rates_sorted) - 1 - i
        print(f"  {color_ansi}{h_str:<10}{rate_str:<6}{task_str}{RESET}")
    print()


def print_report(results, negative_results, positive_results, label, context_type):
    from toggl.const import TABLE_W, COL1, COL2, COL3, COL4, pad_ansi
    from toggl.calc import format_signed
    print(f"\n  {BOLD}{CYAN}POINTS REPORT{RESET}  {DIM}({label} · {context_type}){RESET}")
    print("  " + "─" * TABLE_W)
    print(
        f"  {BOLD}{pad_ansi('Project', COL1)} {pad_ansi('Hours', COL2)} {pad_ansi('Rate', COL3)} {pad_ansi('Points', COL4)}{RESET}"
    )
    print("  " + "─" * TABLE_W)
    for name, hours, rate, pts in results:
        h_str = f"{hours:.1f}h"
        if rate is not None:
            r_str = f"×{int(rate) if rate == int(rate) else rate}"
            p_str = format_signed(pts)
            if pts is not None and pts > 0:
                p_str = f"{GREEN}{p_str}{RESET}"
            elif pts is not None and pts < 0:
                p_str = f"{RED}{p_str}{RESET}"
            else:
                p_str = f"{DIM}{p_str}{RESET}"
        else:
            r_str = f"{DIM}—{RESET}"
            p_str = f"{DIM}—{RESET}"
        print(f"  {pad_ansi(name, COL1)} {pad_ansi(h_str, COL2)} {pad_ansi(r_str, COL3)} {pad_ansi(p_str, COL4)}")

    if negative_results:
        print(f"\n  {BOLD}{RED}Negatives{RESET}")
        for name, _, _, pts in negative_results:
            p_str = format_signed(pts)
            print(f"  {pad_ansi(name, COL1)} {pad_ansi('', COL2)} {pad_ansi('', COL3)} {pad_ansi(f'{RED}{p_str}{RESET}', COL4)}")

    if positive_results:
        print(f"\n  {BOLD}{GREEN}Positives{RESET}")
        for name, _, _, pts in positive_results:
            p_str = format_signed(pts)
            print(f"  {pad_ansi(name, COL1)} {pad_ansi('', COL2)} {pad_ansi('', COL3)} {pad_ansi(f'{GREEN}{p_str}{RESET}', COL4)}")

    total_pts = round(
        sum(r[3] for r in results if r[3] is not None)
        + sum(r[3] for r in negative_results)
        + sum(r[3] for r in positive_results),
        1,
    )
    total_hrs = round(sum(r[1] for r in results if r[1] is not None), 1)
    print("  " + "─" * TABLE_W)
    t_str = format_signed(total_pts)
    if total_pts > 0:
        t_str = f"{GREEN}{BOLD}{t_str}{RESET}"
    elif total_pts < 0:
        t_str = f"{RED}{BOLD}{t_str}{RESET}"
    else:
        t_str = f"{BOLD}{t_str}{RESET}"
    print(f"  {pad_ansi('TOTAL', COL1)} {pad_ansi(f'{total_hrs:.1f}h', COL2)} {pad_ansi('', COL3)} {pad_ansi(t_str, COL4)}")
    print()

    # Sparkbar
    spark_lines = build_week_sparkbar_lines()
    for line in spark_lines:
        print(f"  {line}")
    print()
