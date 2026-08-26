# TStat

Terminal dashboard for [Toggl Track](https://toggl.com/track/). Syncs time entries, scores them against your own rules, and shows trends, habits, and coaching signals.

Built with Python and [Textual](https://textual.textualize.io/).

## Why it exists

Toggl tells you where time went. TStat turns that into a daily scoreboard: points per project, positives and negatives you log by hand, graphs over day/week/month, and insights based on *your* recent baseline rather than generic advice.

## Features

- Sync with the Toggl Track API (rate-limit aware, local CSV cache)
- **Overview**, **Command**, and **Insights** views
- Custom point system, categories, positives, negatives, and activity rules
- Personal-baseline coaching, streaks, and a playbook of next actions
- Keyboard-first TUI with backups, gap backfill, and config safety checks

## Quick start

Needs Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp toggl_config.json.example toggl_config.json
# Put your Toggl API token in the file, or:
export TOGGL_API_TOKEN="your_token_here"

python TogglTrack.py
```

Get a token from Toggl Track → Profile → API token.

`toggl_config.json` and everything under `data/` are gitignored. Do not commit them. They contain your API token and personal time logs.

## Config

`toggl_config.json.example` is the template. The live file maps Toggl projects onto:

- **points** — score per hour (or per logged event for positives/negatives)
- **categories** — groups and colours for the UI
- **activity rules** — daily limits, streaks, combos
- **playbook** — controllability and default durations used by Insights

Token lookup order: `TOGGL_API_TOKEN` environment variable, then `api_token` in `toggl_config.json`.

## Keyboard

| Key | Action |
|---|---|
| `Ctrl+Left` / `Ctrl+Right` | Switch views |
| `u` / `U` | Sync current week / full sync |
| `r` | Refresh from local data |
| `n` / `p` | Log a negative / positive |
| `m` | Manage logs |
| `b` / `B` | Backup / backfill gaps |
| `q` | Quit |

## Architecture

```
TogglTrack.py          entry point
toggl/
  api.py               Toggl Track HTTP client
  cache.py / calc.py   local data + scoring
  config.py            JSON config
  tui.py               Textual app shell
  command.py           Command (analytics) tab
  services/            sync, metrics, coach, playbook, backup
  widgets/ / screens/  tables, graphs, calendar, dialogs
data/                  runtime CSVs, caches, backups (not in git)
```

## Tests

```bash
pip install pytest
pytest tests/unit tests/ui_quality tests/e2e -q
```

Unit, e2e, and UI-quality tests cover scoring, cache, sync edge cases, and keyboard/accessibility behaviour. Visual snapshot tests exist under `tests/visual/` but are unstable across runs (dynamic CSS class names), so they are better as a manual check than CI.

## Privacy

This app stores a Toggl API token and your time-tracking history on disk. Keep the repo private until you are ready, never commit `toggl_config.json` or `data/`, and rotate the token if it may have leaked.
