# AGENTS.md

This repo is a Textual-based TUI for Toggl time tracking data. This file is the starting point for AI agents.

## Start here
1. Read `docs/ai/README.md`.
2. Follow `docs/ai/AI_GUIDELINES.md`.
3. For reviews, also read:
   - `docs/ai/AI_REVIEW_GUIDELINES.md`
   - `docs/ai/CODE_REVIEW_GUIDELINES.md`
4. See the active upgrade work in `docs/plan/IMPROVEMENT_PLAN.md`.

## Repo map (high-level)
- `app.py`: entrypoint
- `TogglTrack.py`: main loop, error handling, TUI startup
- `toggl/`:
  - `tui.py`: Textual UI views, input handling, navigation
  - `cache.py`: DataCache; loads CSV data and serves queries
  - `api.py`: Toggl API helpers, quota handling
  - `calc.py`: metric calculations (net, target, etc.)
  - `config.py`: runtime config loader for `toggl_config.json`
  - `const.py`: constants, layout widths, data paths

## Local config (required to run)
`toggl_config.json` in the repo root is **gitignored** (API token + personal point rules). Each worktree needs its own copy.

```bash
cp toggl_config.json.example toggl_config.json
# edit api_token and project/point mappings to match your Toggl setup
```

Required keys: `points`, `negatives`, `positives` (each a JSON object of name → number). Optional: `daily_target` (default 13), `api_token` (needed for sync/backfill only).

If the file is missing or incomplete, `toggl/config.py` prints a setup hint pointing at `toggl_config.json.example`.

## Data files (gitignored)
Data lives under `data/` per paths in `toggl/const.py`:
- `toggl_data.csv` (weekly)
- `toggl_daily.csv` (daily)
- `toggl_negatives.csv`, `toggl_positives.csv`
- `toggl_sync_history.json`, `toggl_projects.json`

Do **not** commit real data or secrets. `toggl_config.json` contains personal data/keys and is ignored.

## Tests
- Test runner: `pytest`
- Test structure: `tests/unit`, `tests/e2e`
- E2E uses Textual Pilot
- Prefer temp data directories + fixture CSVs; stub API calls

## Interaction rules (for AI)
- When a choice is required, use the OpenCode **question tool** with **one question per turn**.
- Use non-interactive shell flags; no editors or pagers.
- Use OpenCode file tools (`read`, `write`, `apply_patch`) for file edits.
- Do not commit/push unless explicitly asked.
