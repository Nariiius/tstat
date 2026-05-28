# AI Guidelines

These rules are authoritative for AI agents working in this repo.

## 1) Non-negotiable constraints
- Use the OpenCode **question tool** for user choices, **one question per turn**.
- Use OpenCode file tools (`read`, `write`, `apply_patch`) for any file edits.
- Use non-interactive shell flags only. No editors or pagers.
- Do **not** commit, push, or create PRs unless explicitly asked.

## 2) Product intent
- This is a **Textual TUI** for **Toggl** time tracking.
- Data is cached locally in CSVs under `data/` (paths in `toggl/const.py`).
- The system aims to show **week/day/month** performance and to support **backfill** for “all time” data.

## 3) Data safety
- Never commit real data or secrets. `toggl_config.json` and `data/` are ignored.
- When adding features, respect the existing CSV schemas (weekly/daily/positives/negatives).

## 4) Testing discipline
- Use **pytest**. Place tests in `tests/unit` or `tests/e2e`.
- For UI flows, use Textual **Pilot** and run E2E tests by default.
- Prefer temp data dirs with fixture CSVs. Stub API calls.
- Follow TDD: test must fail before production code is written.

## 5) Architecture boundaries
- `toggl/tui.py` owns view composition & navigation.
- `toggl/cache.py` owns CSV loading & in-memory query helpers.
- `toggl/api.py` owns Toggl API and quota handling.
- `toggl/config.py` owns runtime config loading.

Avoid leaking concerns across these seams unless the plan explicitly requires it.
