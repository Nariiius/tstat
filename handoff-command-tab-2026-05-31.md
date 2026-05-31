# Handoff: Command Tab — Trajectory Analytics View

**Date:** 2026-05-31  
**Branch:** `overview-redesign`  
**Approved Plan:** `/Users/sai/.plannotator/plans/command-tab-trajectory-analyti-2026-05-30-approved.md`

---

## 1. What was built

A new **"Command" tab** (index 1, immediately after Overview) — a graph-first analytics workspace rendering TStat point data as a plotext trajectory chart. Includes:

- **`toggl/period.py`** — `PeriodController`: pure date-range navigation engine. Day/Week modes, 4 zoom scales each (7/30/60/90 days; 4/13/26/52 weeks). Offset-based nav (0 = current, negative = past, capped at 0).
- **`toggl/graph.py`** — `GraphWidget`: Textual Widget wrapping plotext v5.3.2. Dark TStat theme, percentile-scaled Y axis, braille smooth lines, zero line prominent, star markers for best/worst/today.
- **`toggl/command.py`** — `CommandTab` + `CalendarWidget`: full layout — top bar (nav arrows + mode toggle + zoom), graph summary line (Net/Best/Worst/Avg), 85/15 graph/calendar split, colored calendar day cells (green=positive, red=negative), bottom mode selector (Trajectory/Positive/Negative/LoggedPos/LoggedNeg).
- **`toggl/cache.py`** — added `get_daily_data_for_range(start, end)` returning per-day aggregates with net/positive/negative/logged_pos/logged_neg fields.
- **`toggl/tui.py`** — wired Command tab into VIEWS array (shifts Day from index 1→2, all other indices shift +1). Added `refresh_command_view()`, focus target, visibility toggling, zoom keybinds (z/Z).
- **`tests/unit/test_command.py`** — 19 unit tests: PeriodController (14 tests) + DataCache range queries (5 tests).

## 2. Critical design decisions from grilling session

| Decision | Choice |
|----------|--------|
| Rendering engine | plotext v5.3.2 (added to requirements.txt) |
| Initial period modes | Day and Week only (Month/Quarter/Year/Lifetime deferred) |
| Day scales | 7d, 30d, 60d, 90d |
| Week scales | 4w, 13w, 26w, 52w |
| No-data days policy | Show as 0 — continuous line, no gaps. Future days also 0 |
| Trajectory data | **Cumulative** running total (not daily net). Other modes use daily values |
| Calendar width | 17 cols (~15%) after post-implementation fix |
| Plotext frame | Removed (`plt.frame(False)`) — double-bordering was cluttered. Graph wrapper has Textual border instead |
| Y-axis scaling | 5th/95th percentile with 15% padding — clips outlier spikes |
| Graph mode | Trajectory = cumulative line. Positive/Negative/LoggedPos/LoggedNeg = daily values |
| Logged Pos data | Sum of points (NOT count of log entries) |
| Logged Neg data | Sum of points (NOT count of log entries) |
| Calendar interaction | Click day in Day mode → centers graph. Click day in Week mode → selects containing week |
| Tab order | Overview(0) → Command(1) → Day(2) → Week(3) → Month(4) → Sync/Quota(5). Day stays default landing (index 2) |

## 3. Key color palette

| Element | RGB | Hex |
|---------|-----|-----|
| Canvas background | (11, 16, 22) | #0b1016 |
| Green (positive/earned) | (55, 217, 148) | #37d994 |
| Red (negative) | (255, 95, 95) | #ff5f5f |
| Cyan (logged pos) | (45, 212, 191) | #2DD4BF |
| Purple (logged neg) | (192, 132, 252) | #C084FC |
| Gold (today marker) | (226, 183, 20) | #e2b714 |
| Zero line | (215, 221, 232) | bright |
| Grid lines | (30, 40, 50) | very dim |

## 4. Notable implementation details

### Plotext date format
plotext v5 parses all string X-values as dates in `%d/%m/%Y` format. The graph widget converts ISO dates (`2026-05-31`) → plotext format (`31/05/2026`) via `_iso_to_plotext()`. The `date_form(output_form='%m/%d')` controls display labels.

### Cumulative trajectory
In `CommandTab.refresh_all()`, when mode is `"trajectory"`, values are transformed:
```python
cum = 0.0
for v in raw_values:
    cum += v
    values.append(round(cum, 1))
```

### Calendar click handling
Calendar days are Labels with IDs `cal-day-0` through `cal-day-41`. The `@on(Click, "#cal-grid Label.cal-day")` handler extracts the cell index from the label ID, computes the actual date from `grid_start + cell_idx`, and calls `PeriodController.set_from_day()` or `set_from_week()`.

### GraphWidget border
The graph wrapper container `#cmd-graph` has `border: round #3d4f63` in CSS. plotext's own frame is disabled. This avoids double-framing.

## 5. What's NOT done (future work)

### From the original spec
1. **Month, Quarter, Year, Lifetime** period modes — architecture supports adding them to `PeriodController` with new scale lists and range formulas
2. **Custom Range** — calendar-based range selection not yet built
3. **"Select a specific completed week/month from calendar"** — the calendar currently navigates to days/weeks, but doesn't have a dedicated "jump to completed week" mode
4. **Future-proof plug-in system** — heatmaps, rolling averages, trend overlays, moving averages, goal lines, forecasts are all deferred

### From post-implementation feedback (priority 8–10)
5. **Different chart styles per mode**: Trajectory (line), Positive (area chart), Negative (area chart), Logged Pos (bar chart), Logged Neg (bar chart). Currently all modes use the same line chart. plotext supports `bar()`, `plot(fillx=True)` for area fill.
6. **Heatmap calendar** — the calendar currently colors cells by net value but isn't a full heatmap
7. **Trend overlays** — moving averages, goal lines not implemented
8. **Replace Day/Week toggle** with simpler labels: 7d, 30d, 90d, 180d, 365d (user suggested this as a simplification)

## 6. Test status

```
116 passed (97 existing + 19 new)
```
All unit tests pass. No e2e tests written specifically for the Command tab (Textual Pilot-based e2e tests exist for other views at `tests/e2e/`).

## 7. Running the app

```bash
cd /Users/sai/Downloads/TUI
.venv/bin/pip install -r requirements.txt   # if plotext not installed
.venv/bin/python TogglTrack.py
```

Requires `toggl_config.json` with `points`, `negatives`, `positives` objects. Copy from `toggl_config.json.example` if missing.

Navigate: `Ctrl+Right` from Overview to Command, or click the "Command" tab. Keyboard: `z` zoom in, `Z` zoom out, left/right for period navigation.

## 8. Suggested skills for the next agent

- **`using-superpowers`** — establish workflow
- **`systematic-debugging`** — if graph rendering issues or layout bugs appear
- **`tdd`** — for writing e2e tests for the Command tab or adding future graph modes
- **`prototype`** — for exploring different chart styles (area, bar) before implementing
- **`verification-before-completion`** — before claiming any fix/feature is done, run `pytest tests/` and verify visually

## 9. Project map (relevant files only)

```
toggl/
  period.py      — PeriodController (date navigation, pure logic)
  graph.py       — GraphWidget (plotext widget)
  command.py     — CommandTab + CalendarWidget (layout, data flow, controls)
  cache.py       — DataCache + get_daily_data_for_range()
  tui.py         — TogglTUI app (VIEWS, compose, refresh wiring)
  calc.py        — calculate() scoring engine (used by cache for net)
  config.py      — POINTS, NEGATIVES, POSITIVES config (used by calc)
tests/unit/
  test_command.py — 19 tests for PeriodController + DataCache range query
requirements.txt  — textual>=0.86,<1.0 + plotext>=5.0,<6.0
```

## 10. Known quirks / pitfalls

1. **plotext date parsing**: X values MUST be `%d/%m/%Y` format. The `_iso_to_plotext` helper handles conversion. Any new date path must go through this.
2. **`frame(False)` removes ALL axes**: Labels, ticks, everything. We rely on subtle axes color + grid. The Textual widget border provides the visual frame.
3. **`DataCache.load()` called on every refresh**: `refresh_all()` creates a fresh cache on each invocation. This is consistent with how other views work (`refresh_all_views()` calls `DataCache.load()` in `TogglTUI`).
4. **Venom pip broken**: The `.venv/bin/pip` has a hardcoded shebang path from a previous worktree. Use `.venv/bin/python -m pip install` instead.
5. **The `snapshot_report.html` is staged**: Not related to this work. Don't commit it accidentally.
