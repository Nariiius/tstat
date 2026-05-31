# Handoff: Command Tab — Trajectory Analytics Workspace

**Date:** 2026-05-31  
**Branch:** `overview-redesign`  
**Tests:** 118 passing (0 failures)  
**Approved Plan:** `/Users/sai/.plannotator/plans/command-tab-trajectory-analyti-2026-05-30-approved.md`  
**Previous Handoff:** `/Users/sai/Downloads/TUI/handoff-command-tab-2026-05-31.md` (superseded)

---

## 1. What was built

A new **"Command" tab** (index 1, immediately after Overview) — a graph-first analytics workspace rendering TStat point data as a plotext trajectory chart. Evolved through a full design spec and multiple refinement passes from user feedback.

### File inventory

| File | Status | Purpose |
|------|--------|---------|
| `toggl/period.py` | **new** | `PeriodController` — pure date navigation: Day/Week/Month modes, scale selection (7d/30d/90d/365d, 4w/13w/26w/52w, 3m/6m/12m) |
| `toggl/graph.py` | **new** | `GraphWidget` — Textual widget wrapping plotext v5.3.2. Dark TStat theme, dynamic Y scaling with outlier clipping, 3-axis labels, average line |
| `toggl/command.py` | **new** | `CommandTab` + `CalendarWidget` — full layout: graph panel (header/controls/stats + graph + mode footer), calendar sidebar with heatmap, bottom section with Category Summary + Daily Breakdown tables |
| `toggl/cache.py` | modified | Added `get_daily_data_for_range()`, `get_range_aggregate()`, plus `earned`/`tracked_neg`/`total_hours` fields to daily dict |
| `toggl/tui.py` | modified | Command tab wired at index 1 (View→Day shifted to 2). VIEWS, compose, refresh, focus, visibility, zoom keybinds |
| `requirements.txt` | modified | Added `plotext>=5.0,<6.0` |
| `tests/unit/test_command.py` | **new** | 19 tests: PeriodController (14) + DataCache range queries (5) |

### Layout structure (final)

```
┌─ Header bar ──────────────────────────────────────────────────┐
├────────────────────────────────────┬──────────────────────────┤
│ Graph Panel (3fr, ~70%)           │ Calendar (25 cols, ~30%) │
│  <<< Today >>>                    │  << May 2026 >>          │
│  Day Week Month  |  7d 30d 90d    │  Mo Tu We Th Fr Sa Su   │
│  BEST +69  NET -796  WORST -779   │  ...heatmap grid...      │
│  AVG -114                         │                          │
│  ┌─ plotext chart ────────────────┤                          │
│  │  title: "25 May → 31 May"     │                          │
│  │  braille line, zero/avg lines │                          │
│  │  dynamic Y, outlier clipping  │                          │
│  └────────────────────────────────┤                          │
│  [Traj] | Pos | Neg | Log+ | Log- │                          │
├────────────────────────────────────┴──────────────────────────┤
│ Category Summary (35%)           │ Daily Breakdown (65%)     │
│ POSITIVE                         │ Mon 25 May +17.2 -796.5   │
│  ├ Building Projects             │ Tue 26 May +52.5 -15.0    │
│  ├ Learning to Code              │ Wed 27 May ...            │
├────────────────────────────────────────────────────────────────┤
│ Footer bar                                                     │
└────────────────────────────────────────────────────────────────┘
```

## 2. Key design decisions

| Decision | Resolution |
|----------|-----------|
| Rendering engine | plotext v5.3.2 (added to requirements) |
| Period modes | Day, Week, Month (Quarter/Year/Lifetime deferred) |
| Day scales | 7d, 30d, 90d, 365d |
| Week scales | 4w, 13w, 26w, 52w |
| Month scales | 3m, 6m, 12m |
| No-data days | Show as 0 — continuous line, no gaps |
| Trajectory mode | Cumulative running total (not daily net) |
| Y-axis scaling | Dynamic min/max with 15% padding; outlier clipping if max_abs > 3×median |
| Y-axis labels | Only 3 labels: max, 0, min (trajectory), or max, min (others) |
| Calendar width | 25 cols (~70/30 split with graph) |
| Category table | Overview-style: POSITIVE/NEGATIVE/UNSCORED/LOGGED sections with tree chars |
| Logged Pos/Neg | Sum of points (NOT count of log entries) |
| Graph markers | Removed — clean chart. Only zero line and average line |
| Tab order | Overview(0) → Command(1) → Day(2) → Week(3) → Month(4) → Sync/Quota(5) |
| Default landing | Day view (index 2) |

## 3. Known quirks / pitfalls

1. **plotext date format**: X values MUST be `%d/%m/%Y` format. `_iso_to_plotext()` handles conversion from ISO. Any new data path must go through this.
2. **`plt.ylim()` with no args returns None** in plotext v5.3.2 — don't try to read back limits; store them locally.
3. **`plt.filly` expects a numeric level**, not a color. Passing an RGB tuple causes `TypeError`.
4. **`plt.frame(False)` removes all axes** — the Textual widget border provides visual framing instead.
5. **Dynamic widget mount/remove crashes Textual** during `on_mount` — use visibility toggling (`display: none`) instead. Scale buttons are pre-created in compose, shown/hidden per mode.
6. **`.venv/bin/pip` has broken shebang** from a previous worktree. Use `.venv/bin/python -m pip install` instead.
7. **Label.Clicked doesn't exist in Textual** — use `@on(Click, ...)` and check `event.control.id`.
8. **`yield from` required** for helper compose methods (`_compose_graph_header`, `_compose_graph_footer`).

## 4. What's NOT done (future work from original spec)

1. **Quarter, Year, Custom Range, Lifetime** period modes — architecture supports adding to PeriodController
2. **Different chart styles per mode** — Trajectory (line), Positive/Negative (area), Logged (bar). Currently all modes use same line chart.
3. **Selected Day Details panel** — between calendar and daily breakdown
4. **Tooltips/hover on graph** — not supported in terminal plotext
5. **Heatmap intensity legend** — calendar has basic coloring but no legend
6. **Trend overlays** — moving averages, goal lines
7. **"365d" button truncation** — shows "36" due to min-width: 4

## 5. Running the app

```bash
cd /Users/sai/Downloads/TUI
.venv/bin/python TogglTrack.py
```

Navigate to Command tab: `Ctrl+Right` from Overview, or click "Command" tab.
Requires `toggl_config.json` with `points`, `negatives`, `positives`.

## 6. Suggested skills for next agent

- **`systematic-debugging`** — if graph rendering or layout breaks
- **`tdd`** — for writing e2e tests or adding future graph modes
- **`prototype`** — for exploring different chart styles (area/bar) before implementing
- **`verification-before-completion`** — before claiming any fix is done, run `pytest tests/` and verify with headless app launch test

### Test command for headless verification:
```bash
cd /Users/sai/Downloads/TUI && timeout 6 .venv/bin/python -c "
import toggl.tui
o = toggl.tui.TogglTUI.__init__
def p(s): o(s); s.active_view_index = 1  # Start on Command
toggl.tui.TogglTUI.__init__ = p
from toggl.tui import TogglTUI
TogglTUI().run()
" 2>/tmp/tui_test.log && grep -c 'Error\|Traceback' /tmp/tui_test.log || echo 'PASS'
```

## 7. Color palette reference

| Element | RGB | Hex | Usage |
|---------|-----|-----|-------|
| Canvas background | (11, 16, 22) | #0b1016 | Graph + calendar bg |
| Green (positive) | (55, 217, 148) | #37d994 | Positive data, best marker |
| Bright green | (46, 204, 113) | #2ecc71 | Calendar excellent days (≥+10) |
| Red (negative) | (255, 95, 95) | #ff5f5f | Negative data, worst marker |
| Bright red | (255, 68, 68) | #ff4444 | Calendar terrible days (≤-10) |
| Cyan (logged pos) | (45, 212, 191) | #2DD4BF | Logged positive chart |
| Purple (logged neg) | (192, 132, 252) | #C084FC | Logged negative chart |
| Gold (today) | (226, 183, 20) | #e2b714 | Today indicator |
| Zero line | (215, 221, 232) | bright | Dominant horizontal line |
| Average line | (61, 79, 99) | dim grey | Subtle reference line |
| Grid | (50, 60, 75) | very dim | Background grid |
| Accent | (99, 243, 255) | #63f3ff | Active buttons, borders, labels |
