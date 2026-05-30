#!/usr/bin/env python3
"""
Generate SVG screenshots of all 9 TogglTUI views and produce an HTML savepoint.

Usage:
    python tools/generate_view_snapshots.py [--width 120] [--height 40] [--output report.html]
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import tempfile
import textwrap
from datetime import timedelta
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_fixtures() -> dict[str, Any]:
    """Create temp data dir, monkeypatch all path constants and config.

    Mirrors the pytest fixtures in tests/conftest.py.
    """
    import toggl.const
    import toggl.cache
    import toggl.backfill
    import toggl.neg
    import toggl.config
    import toggl.calc

    tmp_dir = Path(tempfile.mkdtemp(prefix="togglui_snap_"))
    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True)

    # ── Patch path constants ──────────────────────────────────
    patched = {}
    patched["DATA_DIR"] = str(data_dir)
    patched["BACKFILL_DB"] = str(data_dir / "toggl_backfill.db")
    patched["CSV_FILE"] = str(data_dir / "toggl_data.csv")
    patched["DAILY_CSV_FILE"] = str(data_dir / "toggl_daily.csv")
    patched["NEGATIVES_CSV_FILE"] = str(data_dir / "toggl_negatives.csv")
    patched["POSITIVES_CSV_FILE"] = str(data_dir / "toggl_positives.csv")
    patched["HISTORY_FILE"] = str(data_dir / "toggl_sync_history.json")
    patched["PROJECTS_FILE"] = str(data_dir / "toggl_projects.json")

    for key, val in patched.items():
        setattr(toggl.const, key, val)

    # Mirror imports in cache/backfill/neg modules
    setattr(toggl.cache, "CSV_FILE", toggl.const.CSV_FILE)
    setattr(toggl.cache, "DAILY_CSV_FILE", toggl.const.DAILY_CSV_FILE)
    setattr(toggl.cache, "NEGATIVES_CSV_FILE", toggl.const.NEGATIVES_CSV_FILE)
    setattr(toggl.cache, "POSITIVES_CSV_FILE", toggl.const.POSITIVES_CSV_FILE)
    setattr(toggl.cache, "HISTORY_FILE", toggl.const.HISTORY_FILE)
    setattr(toggl.backfill, "BACKFILL_DB", toggl.const.BACKFILL_DB)
    setattr(toggl.neg, "NEGATIVES_CSV_FILE", toggl.const.NEGATIVES_CSV_FILE)
    setattr(toggl.neg, "POSITIVES_CSV_FILE", toggl.const.POSITIVES_CSV_FILE)

    # ── Write sync history to suppress auto-refresh ───────────
    import json

    with open(toggl.const.HISTORY_FILE, "w") as f:
        json.dump({"last_updated": "2026-05-30T12:00:00"}, f)

    # ── Write sample weekly CSV ───────────────────────────────
    w_lines = ["Week,Project,Hours"]
    w_lines.append("2023-W01,Learning to Code,10.5")
    w_lines.append("2023-W01,Building Projects,4.2")
    w_lines.append("2023-W02,Learning to Code,8.0")
    with open(toggl.const.CSV_FILE, "w") as f:
        f.write("\n".join(w_lines) + "\n")

    # ── Write sample daily CSV ────────────────────────────────
    from toggl.cache import get_week_dates

    d_lines = ["Date,Project,Hours"]
    for week_str in ("2023-W01", "2023-W02"):
        start_d, end_d = get_week_dates(week_str)
        for i in range(7):
            d = start_d + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            d_lines.append(f"{d_str},Learning to Code,1.5")
            d_lines.append(f"{d_str},Building Projects,0.6")
    with open(toggl.const.DAILY_CSV_FILE, "w") as f:
        f.write("\n".join(d_lines) + "\n")

    # ── Write sample config (points / negatives / positives) ──
    points = {
        "Learning to Code": 1.5,
        "Building Projects": 2.0,
        "Fitness": 1.0,
    }
    negatives = {
        "Procrastination": -3.0,
        "Junk Food": -2.0,
    }
    positives = {
        "Exercise": 3.0,
        "Reading": 2.0,
    }

    for mod in (toggl.config, toggl.calc, toggl.cache):
        setattr(mod, "POINTS", points)
    setattr(toggl.config, "NEGATIVES", negatives)
    setattr(toggl.config, "POSITIVES", positives)
    setattr(toggl.neg, "NEGATIVES", negatives)
    setattr(toggl.neg, "POSITIVES", positives)
    setattr(toggl.config, "DAILY_TARGET", 13.0)

    return {"tmp_dir": tmp_dir, "data_dir": data_dir}


def make_app():
    """Create a fresh TogglTUI instance."""
    from toggl.tui import TogglTUI

    return TogglTUI()


def capture_view(
    app_factory,
    press_sequence: tuple[str, ...],
    terminal_size: tuple[int, int] = (120, 40),
) -> str:
    """Return SVG string for a view reached by *press_sequence*."""
    from textual._doc import take_svg_screenshot

    app = app_factory()
    try:
        svg = take_svg_screenshot(
            app=app,
            press=press_sequence,
            terminal_size=terminal_size,
            simplify=True,
        )
    finally:
        # Ensure the app is properly cleaned up
        try:
            app._running = False
        except Exception:
            pass
    return svg


def inline_svg(svg: str, view_name: str) -> str:
    """Wrap an SVG in minimal boilerplate for embedding."""
    # Strip XML declaration if present (for HTML5 compat)
    svg = svg.replace('<?xml version="1.0" encoding="utf-8"?>\n', "")
    return svg


def build_html(view_svgs: list[tuple[str, str]], title: str = "TogglTUI View Snapshots") -> str:
    """Build a standalone HTML page that displays all view SVGs side by side."""
    sections = []
    for name, svg_content in view_svgs:
        sections.append(
            f"""    <div class="view-card">
      <h2>{name}</h2>
      {svg_content}
    </div>"""
        )

    html = textwrap.dedent(f"""\
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      body {{
        background: #0b1016;
        color: #d7dde8;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        padding: 2rem;
      }}
      h1 {{
        color: #63f3ff;
        font-size: 1.6rem;
        margin-bottom: 0.5rem;
      }}
      .subtitle {{
        color: #8d98a7;
        margin-bottom: 2rem;
        font-size: 0.9rem;
      }}
      .grid {{
        display: flex;
        flex-wrap: wrap;
        gap: 1.5rem;
        justify-content: center;
      }}
      .view-card {{
        background: #151c26;
        border: 1px solid #3d4f63;
        border-radius: 8px;
        padding: 1rem;
        max-width: 620px;
        width: 100%;
      }}
      .view-card h2 {{
        color: #63f3ff;
        font-size: 1rem;
        margin-bottom: 0.75rem;
        padding-bottom: 0.4rem;
        border-bottom: 2px solid #63f3ff;
      }}
      .view-card svg {{
        width: 100%;
        height: auto;
        display: block;
      }}
    </style>
    </head>
    <body>
      <h1>{title}</h1>
      <p class="subtitle">Generated {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')} &middot; {len(view_svgs)} views</p>
      <div class="grid">
    {chr(10).join(sections)}
      </div>
    </body>
    </html>
    """)
    return html


def main():
    parser = argparse.ArgumentParser(description="Generate TogglTUI view snapshots")
    parser.add_argument("--width", type=int, default=120, help="Terminal width (cols)")
    parser.add_argument("--height", type=int, default=40, help="Terminal height (rows)")
    parser.add_argument(
        "--output",
        type=str,
        default=PROJECT_ROOT / "snapshots_savepoint.html",
        help="Output HTML file path",
    )
    args = parser.parse_args()

    term_size = (args.width, args.height)
    output_path = Path(args.output)

    print(f"Setting up test fixtures ... ", end="", flush=True)
    setup_fixtures()
    print("done")

    # View definitions — name + press sequence from default (Day, index 1)
    views = [
        ("Overview",     ("ctrl+left",)),
        ("Day",          ()),
        ("Week",         ("ctrl+right",)),
        ("Month",        ("ctrl+right", "ctrl+right",)),
        ("Negatives",    ("ctrl+right", "ctrl+right", "ctrl+right",)),
        ("Positives",    ("ctrl+right", "ctrl+right", "ctrl+right", "ctrl+right",)),
        ("Recovery",     ("ctrl+right", "ctrl+right", "ctrl+right", "ctrl+right", "ctrl+right",)),
        ("Sync/Quota",   ("ctrl+right", "ctrl+right", "ctrl+right", "ctrl+right", "ctrl+right", "ctrl+right",)),
    ]

    view_svgs: list[tuple[str, str]] = []
    total = len(views)

    for idx, (name, press) in enumerate(views, 1):
        print(f"[{idx}/{total}] Capturing {name} ... ", end="", flush=True)
        try:
            svg = capture_view(make_app, press, term_size)
            view_svgs.append((name, inline_svg(svg, name)))
            print("ok")
        except Exception as e:
            print(f"FAILED: {e}")
            view_svgs.append((name, f'<div class="error">Error: {e}</div>'))

    print(f"\nBuilding HTML report ... ", end="", flush=True)
    html = build_html(view_svgs)
    output_path.write_text(html, encoding="utf-8")
    print(f"done\n\nReport saved → {output_path.resolve()}")


if __name__ == "__main__":
    main()
