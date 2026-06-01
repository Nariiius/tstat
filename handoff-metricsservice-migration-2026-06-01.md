# Handoff — MetricsService Migration (Final Sweep)

> **Generated:** 2026-06-01
> **Branch:** `main` (uncommitted changes)
> **Test status:** 120 unit tests passing (all green)

---

## What Was Accomplished

Completed the MetricsService migration — porting the remaining 3 query methods from `cache.py` into `services/metrics.py`, wiring constructor DI for config, and updating all callers.

### Changes (uncommitted, 304 insertions / 330 deletions across 10 files)

| File | Δ | What changed |
|------|---|-------------|
| `toggl/services/metrics.py` | +166 lines | Ported `get_daily_data_for_range`, `get_range_aggregate`, `get_recovery_rows`; constructor now accepts `points`, `negatives`, `positives`, `recovery_ignore`, `get_daily_target` via DI |
| `toggl/cache.py` | −249 lines | Deleted 8 methods: `get_day_metrics`, `get_week_dashboard_rows`, `get_report_sections` (delegating wrappers); `get_yearly_day_net_map`, `get_monthly_aggregates` (dead code); `get_daily_data_for_range`, `get_range_aggregate`, `get_recovery_rows` (native implementations). Cleaned imports (`calculate`, `RECOVERY_IGNORE`, `get_daily_target` removed) |
| `toggl/tui.py` | +33 lines | Composition root: `_build_metrics()` helper, `_metrics` attribute, updated `load_data()` / `_on_auto_refresh_done()` / `_on_sync_done()` |
| `toggl/panels.py` | +20 / −20 lines | Uses injected `self.app._metrics` instead of ad-hoc `MetricsService(cache)` |
| `toggl/command.py` | +15 / −15 lines | Removed ad-hoc `MetricsService(cache)` in `refresh_all()` |
| `toggl/widgets/tables.py` | +14 / −14 lines | Uses injected `MetricsService` via `app._metrics` |
| `toggl/models/project.py` | +8 lines | Docstring fix (stale fields) |
| `tests/unit/test_cache.py` | +47 / −47 lines | Uses `MetricsService` via `_make_svc` helper |
| `tests/unit/test_command.py` | +29 / −29 lines | Same pattern |
| `tests/unit/test_metrics.py` | +53 / −53 lines | Expanded tests for new methods |

### What was NOT changed

- `toggl/cache.py` still has ~514 lines (remaining query methods: `get_negative_log_rows`, `get_positive_log_rows`, `get_positive_summary`, `get_negative_summary`, project lookups, CSV I/O)
- `get_daily_breakdown` was already in `MetricsService` from prior session
- `get_report_sections` was never in `MetricsService` — it was a cache.py orchestrator that called migrated methods; its callers now use migrated methods individually

---

## Uncommitted Changes

All 10 modified files are unstaged. They should be reviewed and committed as a single cohesive unit:

```
 M tests/unit/test_cache.py
 M tests/unit/test_command.py
 M tests/unit/test_metrics.py
 M toggl/cache.py
 M toggl/command.py
 M toggl/models/project.py
 M toggl/panels.py
 M toggl/services/metrics.py
 M toggl/tui.py
 M toggl/widgets/tables.py
```

---

## Known Issues & Next Steps

### 1. Commit the MetricsService migration

The 10 modified files are ready. Suggested commit message:

```
Complete MetricsService migration

Port get_daily_data_for_range, get_range_aggregate, get_recovery_rows
from cache.py into services/metrics.py with config DI. Wire single
MetricsService instance in tui.py composition root. Update all callers.
Delete 8 dead wrapper/migrated methods from cache.py (-249 lines).
Clean up imports. All 120 unit tests pass.
```

### 2. Pre-existing e2e failure

`test_neg_log_button_opens_negative_modal` fails even on clean checkout — appears to be a Textual Pilot timing/selector issue, not related to this migration.

### 3. Stale visual snapshot baselines

~16 snapshot baselines reference removed views (day-table, week-table, etc.). To regenerate:

```bash
python -m pytest tests/visual/ --snapshot-update
```

### 4. Remaining `cache.py` surface area

`cache.py` at ~514 lines is no longer a god class but still has CSV I/O mixed with query methods. Potential future splits:
- `repository/csv_repo.py` for CSV I/O
- Keep `DataCache` as a thin query facade

### 5. `command.py` still at ~490 lines

Could benefit from further decomposition — `CommandTab` still handles both period navigation and category/metric display.

### 6. No `__init__.py` in `services/` package

`toggl/services/` lacks an `__init__.py` — Python 3.3+ namespace packages work fine, but adding one with explicit exports is cleaner.

---

## Reference Documents

| Doc | Path |
|-----|------|
| General handoff (broader context) | `./HANDOFF.md` |
| Architecture remediation handoff | `./handoff-architecture-remediation-2026-05-31.md` |
| Architecture review (full) | `./architecture_review_v4.md` |
| View widget extraction plan | `./docs/superpowers/plans/2026-05-31-view-widget-extraction.md` |
| Improvement plan | `./docs/plan/IMPROVEMENT_PLAN.md` |
| AI guidelines | `./docs/ai/` |

---

## Architecture Snapshot

### Dependency flow (unidirectional)

```
tui.py → panels.py, command.py
       → services/metrics.py → cache.py
       → screens/dialogs.py
       → formatters/
```

### MetricsService instance lifecycle

```
TogglTUI (App) owns _metrics: MetricsService
  └── built in _build_metrics() when DataCache is loaded
  └── passed to panels/tabs via self.app._metrics
  └── NOT recreated per refresh — single instance
```

---

## Suggested Skills

When starting work, invoke the relevant skill:

| Skill | When |
|-------|------|
| `skill({name: "brainstorming"})` | Before any new feature or structural change |
| `skill({name: "writing-plans"})` | After scoping work that needs a structured plan |
| `skill({name: "test-driven-development"})` | When adding new functions, query methods, or fixing bugs |
| `skill({name: "systematic-debugging"})` | If you encounter unexpected test failures (incl. the pre-existing e2e issue) |
| `skill({name: "requesting-code-review"})` | Before merging or finishing a branch |
| `skill({name: "verification-before-completion"})` | Before claiming work is done — run tests, verify no regressions |
| `skill({name: "finishing-a-development-branch"})` | When implementation is complete and tests pass — to decide between commit + merge, PR, or cleanup |
| `skill({name: "handoff"})` | If you need to compact context for another agent mid-stream |

---

## Running Tests

```bash
python -m pytest tests/unit/ -x -q        # unit tests (120 pass)
python -m pytest tests/e2e/ -x -q         # e2e tests (1 known failure)
python -m pytest tests/visual/ --snapshot-update  # regenerate snapshot baselines
python -m pytest tests/ -x -q             # all tests (except visual snapshots)
```
