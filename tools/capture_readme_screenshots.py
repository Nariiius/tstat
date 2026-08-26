#!/usr/bin/env python3
"""Capture README screenshots of TStat using demo data, not live logs."""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Skip auto-sync against the real Toggl API while capturing.
sys.modules.setdefault("pytest", type(sys)("pytest"))

# Cursor/CI often sets NO_COLOR, which makes Textual dump grayscale SVGs.
os.environ.pop("NO_COLOR", None)
os.environ["FORCE_COLOR"] = "1"

OUT_DIR = PROJECT_ROOT / "docs" / "screenshots"
TERM_SIZE = (140, 42)

PERSONAL_LEAKS = (
    "Wuwa Dailies",
    "Job?",
    "Good deed",
    "Lips",
    "GI Dailies",
    "Doomscrolling",
    "Abs Cinema",
    "Existence Extrovert",
    "Projects/Gacha",
    "Learning Japanese",
)


def patch_paths(tmp: Path) -> Path:
    """Point every imported path binding at a temp dir.

    ``import toggl.const`` runs ``toggl/__init__.py``, which binds CSV/config
    paths in cache/config/backup *before* we can patch const. Copy the new
    paths onto every module that imported them.
    """
    import toggl.api as api
    import toggl.cache as cache
    import toggl.config as config
    import toggl.const as const
    import toggl.neg as neg
    import toggl.services.backup as backup
    import toggl.services.insights_bundle as insights_bundle

    data_dir = tmp / "data"
    data_dir.mkdir(parents=True)
    config_path = str(tmp / "toggl_config.json")

    paths = {
        "DATA_DIR": str(data_dir),
        "CSV_FILE": str(data_dir / "toggl_data.csv"),
        "DAILY_CSV_FILE": str(data_dir / "toggl_daily.csv"),
        "NEGATIVES_CSV_FILE": str(data_dir / "toggl_negatives.csv"),
        "POSITIVES_CSV_FILE": str(data_dir / "toggl_positives.csv"),
        "HISTORY_FILE": str(data_dir / "toggl_sync_history.json"),
        "PROJECTS_FILE": str(data_dir / "toggl_projects.json"),
        "PLAYBOOK_CACHE_FILE": str(data_dir / "toggl_insights_bundle.json"),
        "CONFIG_FILE": config_path,
    }
    for mod in (const, cache, config, neg, api, backup, insights_bundle):
        for key, val in paths.items():
            if hasattr(mod, key):
                setattr(mod, key, val)

    backup.BACKUP_DIR = os.path.join(paths["DATA_DIR"], "backups")
    backup.LOG_FILE = os.path.join(paths["DATA_DIR"], "sync_debug.log")
    backup._CSV_HEADERS = {
        paths["CSV_FILE"]: ["Week", "Project", "Hours"],
        paths["DAILY_CSV_FILE"]: ["Date", "Project", "Hours"],
        paths["NEGATIVES_CSV_FILE"]: ["Date", "Negative", "Points"],
        paths["POSITIVES_CSV_FILE"]: ["Date", "Positive", "Points"],
    }
    backup._BACKUP_SOURCE_FILES = [
        paths["CSV_FILE"],
        paths["DAILY_CSV_FILE"],
        paths["NEGATIVES_CSV_FILE"],
        paths["POSITIVES_CSV_FILE"],
        paths["HISTORY_FILE"],
        paths["PROJECTS_FILE"],
        paths["PLAYBOOK_CACHE_FILE"],
        paths["CONFIG_FILE"],
        backup.LOG_FILE,
    ]
    config.CONFIG_EXAMPLE_FILE = str(PROJECT_ROOT / "toggl_config.json.example")
    return data_dir


def write_demo_data(data_dir: Path, config_path: Path) -> None:
    import toggl.const as const
    from toggl.cache import get_week_str

    shutil.copyfile(PROJECT_ROOT / "toggl_config.json.example", config_path)

    today = date.today()
    daily_rows: list[tuple[str, str, float]] = []
    weekly: dict[str, dict[str, float]] = {}

    catalog = [
        ("Coding", 2.0, 0.6),
        ("Writing", 1.1, 0.5),
        ("Study", 0.9, 0.4),
        ("Exercise", 0.8, 0.35),
        ("Planning", 0.4, 0.2),
        ("Entertainment", 0.7, 0.4),
        ("Chores", 0.3, 0.2),
        ("Rest", 7.5, 0.4),
    ]

    for age in range(90, -1, -1):
        day = today - timedelta(days=age)
        ds = day.strftime("%Y-%m-%d")
        week = get_week_str(day)
        weekday = day.weekday()
        for name, base, spread in catalog:
            if name == "Rest":
                hours = round(base + ((age % 5) - 2) * 0.15, 2)
            elif weekday >= 5 and name in {"Coding", "Writing", "Study"}:
                hours = round(max(0.2, base * 0.45 + (age % 3) * 0.1), 2)
            else:
                hours = round(max(0.0, base + ((age + weekday) % 5 - 2) * spread * 0.35), 2)
            if hours <= 0:
                continue
            daily_rows.append((ds, name, hours))
            weekly.setdefault(week, {})
            weekly[week][name] = weekly[week].get(name, 0.0) + hours

    with open(const.DAILY_CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Project", "Hours"])
        writer.writerows(daily_rows)

    with open(const.CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Week", "Project", "Hours"])
        for week in sorted(weekly):
            for name, hours in weekly[week].items():
                writer.writerow([week, name, round(hours, 2)])

    positives = [
        (today - timedelta(days=d), name)
        for d, name in (
            (0, "Meditation"),
            (0, "Workout"),
            (1, "Exercise"),
            (1, "Reading"),
            (2, "Meditation"),
            (4, "Social Time"),
            (5, "Reading"),
            (7, "Early Night"),
        )
    ]
    negatives = [
        (today - timedelta(days=d), name)
        for d, name in (
            (0, "Distraction"),
            (3, "Procrastination"),
            (6, "Junk Food"),
        )
    ]

    with open(const.POSITIVES_CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Positive", "Points"])
        for day, name in positives:
            writer.writerow([day.strftime("%Y-%m-%d"), name, 3])

    with open(const.NEGATIVES_CSV_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Negative", "Points"])
        for day, name in negatives:
            writer.writerow([day.strftime("%Y-%m-%d"), name, 2])

    with open(const.HISTORY_FILE, "w") as f:
        json.dump({"last_updated": f"{today.isoformat()}T12:00:00"}, f)


def capture(name: str, press: tuple[str, ...], pause: float = 1.6) -> Path:
    from textual._doc import take_svg_screenshot
    from toggl.tui import TogglTUI

    async def settle(pilot):
        await pilot.pause(pause)

    svg = take_svg_screenshot(
        app=TogglTUI(),
        press=press,
        terminal_size=TERM_SIZE,
        title=f"TStat — {name}",
        run_before=settle,
        wait_for_animation=True,
        simplify=True,
    )
    leaks = PERSONAL_LEAKS
    for leak in leaks:
        if leak in svg:
            raise SystemExit(f"Refusing to write {name}: personal data {leak!r} in screenshot")
    if "#63f3ff" not in svg.lower() and "63f3ff" not in svg.lower():
        raise SystemExit(
            f"Refusing to write {name}: screenshot has no accent color "
            "(NO_COLOR is probably still on)"
        )
    out = OUT_DIR / f"{name}.svg"
    out.write_text(svg, encoding="utf-8")
    print(f"  wrote {out.relative_to(PROJECT_ROOT)} ({out.stat().st_size} bytes)")
    return out


def svg_to_png(svg_path: Path) -> Path | None:
    png_path = svg_path.with_suffix(".png")
    ql = shutil.which("qlmanage")
    if not ql:
        return None
    import subprocess

    subprocess.run(
        [ql, "-t", "-s", "1800", "-o", str(OUT_DIR), str(svg_path)],
        check=False,
        capture_output=True,
    )
    produced = OUT_DIR / f"{svg_path.name}.png"
    if produced.exists():
        produced.replace(png_path)
        print(f"  wrote {png_path.relative_to(PROJECT_ROOT)}")
        return png_path
    return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="tstat_shots_"))
    try:
        print("Patching paths and writing demo data...")
        data_dir = patch_paths(tmp)
        import toggl.const as const

        write_demo_data(data_dir, Path(const.CONFIG_FILE))
        from toggl.cache import reset_cache

        reset_cache()
        cfg_text = Path(const.CONFIG_FILE).read_text()
        if "YOUR_TOGGL_API_TOKEN" not in cfg_text:
            raise SystemExit("Refusing to capture: demo config is not the example template")

        shots = [
            ("command", ()),
            ("overview", ("ctrl+left",)),
            ("insights", ("ctrl+right",)),
            ("log-positive", ("p",)),
        ]
        print("Capturing views...")
        for name, press in shots:
            print(f"[{name}]")
            svg = capture(name, press, pause=2.0 if name == "insights" else 1.6)
            svg_to_png(svg)
        print(f"\nScreenshots in {OUT_DIR}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
