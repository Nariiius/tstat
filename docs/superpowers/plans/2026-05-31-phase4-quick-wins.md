# Phase 4 Quick Wins Implementation Plan

> **For agentic workers:** Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task.

**Goal:** Split CLI code from TUI modules and add type annotations to all public functions.

**Architecture:** Remove dead CLI-only functions (only used by archive/cli.py which is itself dead) from `neg.py` and `api.py`. Refactor `_confirm_sync_quota` to separate quota-check logic from interactive prompt. Then add type annotations to all 244 public functions across `toggl/`.

**Tech Stack:** Python 3.11, typing, mypy-compatible annotations

---

### Task 1: Remove Dead CLI Code from `neg.py`

**Files:**
- Modify: `toggl/neg.py` (lines 71-237)
- Delete: `toggl/neg.py` functions `log_positive`, `log_negative`, `pick_positive_interactive`, `pick_negative_interactive`, `print_pos_log`, `print_neg_log`

- [ ] **Step 1: Remove dead CLI functions**

Delete these functions from `toggl/neg.py`:
- `log_positive()` (lines 71-88) — only used by `archive/cli.py`
- `log_negative()` (lines 91-109) — only used by `archive/cli.py`
- `pick_positive_interactive()` (lines 112-129) — only used by `archive/cli.py`
- `pick_negative_interactive()` (lines 132-149) — only used by `archive/cli.py`
- `print_pos_log()` (lines 152-193) — only used by `archive/cli.py`
- `print_neg_log()` (lines 196-237) — only used by `archive/cli.py`

Also remove the unused import of `_prompt_yes_no` from line 12 (only used by the deleted CLI functions).

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

- [ ] **Step 3: Verify no external refs remain**

```bash
cd /Users/sai/Downloads/TUI && rg "log_positive\(|log_negative\(|pick_positive_interactive|pick_negative_interactive|print_pos_log|print_neg_log" toggl/ tests/
```
Expected: No matches (only `log_positive_direct`, `log_negative_direct` should remain).

---

### Task 2: Remove Dead CLI Code from `api.py`

**Files:**
- Modify: `toggl/api.py`

- [ ] **Step 1: Remove dead CLI functions**

Delete these functions from `toggl/api.py`:
- `check_quota()` (lines 168-198) — only used by `archive/cli.py`
- `_print_api_usage_summary()` (lines 95-107) — only used by `archive/cli.py`
- `_prompt_yes_no()` (lines 214-221) — only used by deleted code and `_confirm_sync_quota`

- [ ] **Step 2: Refactor `_confirm_sync_quota`**

Replace the prompt behavior in `_confirm_sync_quota` with a parameter-free quota check that returns `(ok: bool, reason: str | None)`:

```python
def _confirm_sync_quota(token, estimated_requests, sync_label, prompt_on_warning=True):
    """Check quota before sync. Warns via print if low, prompts if prompt_on_warning."""
    url = "https://api.track.toggl.com/api/v9/me"
    _, _, err = _make_auth_request(url, token)

    if err == 402:
        wait = _format_reset_window(API_RUN_STATS["resets_in"])
        print(f"\n  {RED}{BOLD}Cannot start {sync_label}.{RESET}")
        print(f"  {DIM}Hourly quota is already exhausted. Reset in {wait}.{RESET}\n")
        return False
    if err == 429:
        print(f"\n  {RED}{BOLD}Cannot start {sync_label}.{RESET}")
        print(f"  {DIM}Rate limited right now. Wait a moment and try again.{RESET}\n")
        return False
    if err is not None:
        print(f"\n  {RED}Failed to check quota before {sync_label}: {err}{RESET}\n")
        return False

    remaining = API_RUN_STATS["remaining"]
    if remaining is None:
        return True

    needs_warning = remaining - estimated_requests < LOW_QUOTA_WARNING
    if not needs_warning:
        return True

    limit = API_RUN_STATS["limit"] if API_RUN_STATS["limit"] is not None else "?"
    wait = _format_reset_window(API_RUN_STATS["resets_in"])
    if not prompt_on_warning:
        return False

    print(f"\n  {YELLOW}{BOLD}⚠  Low API quota warning{RESET}")
    print(f"  Remaining quota     {YELLOW}{BOLD}{remaining}/{limit}{RESET}")
    print(f"  Estimated requests  {CYAN}{BOLD}{estimated_requests}{RESET}")
    print(f"  Window resets in    {DIM}{wait}{RESET}")
    print(f"  {DIM}Continuing could stop mid-sync if the quota runs out.{RESET}")
    print()
    while True:
        ans = input(f"{YELLOW}Continue sync anyway? (y/n): {RESET}").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print(f"{YELLOW}Please enter 'y' or 'n'.{RESET}")
```

Note: The inline prompt replaces the `_prompt_yes_no` call since it's the only remaining use.

- [ ] **Step 3: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

- [ ] **Step 4: Verify no external refs remain**

```bash
cd /Users/sai/Downloads/TUI && rg "check_quota|_print_api_usage_summary|_prompt_yes_no" toggl/ tests/
```
Expected: `_prompt_yes_no` has no matches; `check_quota` and `_print_api_usage_summary` only in `archive/cli.py`.

---

### Task 3: Delete `archive/` Directory

**Files:**
- Delete: `archive/` (entire directory, ~474 lines of dead CLI code)

- [ ] **Step 1: Remove archive directory**

```bash
cd /Users/sai/Downloads/TUI && rm -rf archive/
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

---

### Task 4: Add Type Annotations to `api.py`

**Files:**
- Modify: `toggl/api.py`

- [ ] **Step 1: Add annotations to all public functions**

Add return type annotations and parameter type annotations to every function in `api.py`:

```python
import sys
import os
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
import base64
from typing import Any

class TogglRateLimitError(Exception):
    def __init__(self, message: str = "", limit: Any = None, remaining: Any = None, resets_in: Any = None) -> None:
        ...

class TogglAPIError(Exception):
    def __init__(self, message: str = "", status_code: int | None = None) -> None:
        ...

def _reset_api_stats() -> None: ...
def _normalize_headers(headers: dict) -> dict: ...
def _header_value(headers: dict, *names: str) -> str | None: ...
def _parse_int(value: Any) -> int | None: ...
def _record_quota_headers(headers: dict) -> None: ...
def _format_reset_window(secs: int | None) -> str: ...
def _make_auth_request(url: str, token: str, method: str = "GET") -> tuple: ...
def toggl_request(endpoint: str, token: str) -> Any: ...
def get_api_token() -> str: ...
def get_projects_cache_age_days() -> float | None: ...
def is_projects_cache_stale(max_age_days: float = ...) -> bool: ...
def _confirm_sync_quota(token: str, estimated_requests: int, sync_label: str, prompt_on_warning: bool = True) -> bool: ...
def get_projects_map(token: str, use_cache: bool = False) -> dict: ...
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_api.py -x -q
```
Expected: All API tests pass.

---

### Task 5: Add Type Annotations to `neg.py`

**Files:**
- Modify: `toggl/neg.py`

- [ ] **Step 1: Add annotations**

```python
from typing import Literal

def log_activity_direct(name: str, mode: Literal["positive", "negative"]) -> tuple[bool, str]: ...
def log_positive_direct(pos_name: str) -> tuple[bool, str]: ...
def log_negative_direct(neg_name: str) -> tuple[bool, str]: ...
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_neg.py -x -q
```
Expected: All neg tests pass.

---

### Task 6: Add Type Annotations to `config.py`

**Files:**
- Modify: `toggl/config.py`

- [ ] **Step 1: Add annotations**

```python
from typing import Any

def load_config() -> dict[str, Any]: ...
def load_runtime_settings() -> None: ...
```

Read current file to determine exact signatures.

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

---

### Task 7: Add Type Annotations to `const.py`

**Files:**
- Modify: `toggl/const.py`

- [ ] **Step 1: Add annotations to all module-level constants and functions**

`const.py` is primarily constants (strings, ints, paths) — annotate any function or computed value.

- [ ] **Step 2: Run tests**

Expected: All tests pass.

---

### Task 8: Add Type Annotations to `calc.py`

**Files:**
- Modify: `toggl/calc.py`

- [ ] **Step 1: Add annotations**

Read current file, add annotations to all functions.

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_calc.py -x -q
```
Expected: All tests pass.

---

### Task 9: Add Type Annotations to `cache.py`

**Files:**
- Modify: `toggl/cache.py`

- [ ] **Step 1: Add annotations to all public methods**

Read current file, add annotations to `DataCache` class methods and module-level functions.

- [ ] **Step 2: Run tests**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/unit/test_cache.py -x -q
```
Expected: All tests pass.

---

### Task 10: Add Type Annotations to `graph.py`, `period.py`, `services/sync.py`, `screens/dialogs.py`, `formatters/*.py`

**Files:**
- Modify: `toggl/graph.py`, `toggl/period.py`, `toggl/services/sync.py`, `toggl/screens/dialogs.py`, `toggl/formatters/*.py`

- [ ] **Step 1: Add annotations to each file**

- [ ] **Step 2: Run tests after each**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All tests pass.

---

### Task 11: Add Type Annotations to `tui.py` and `command.py`

**Files:**
- Modify: `toggl/tui.py`, `toggl/command.py`

- [ ] **Step 1: Add annotations to all methods**

- [ ] **Step 2: Run full test suite**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -x -q
```
Expected: All 108+ tests pass.

---

### Final Verification

- [ ] **Run full suite and clean up**

```bash
cd /Users/sai/Downloads/TUI && python -m pytest tests/ -v
```
Expected: All tests pass, 0 warnings about missing annotations.

```bash
cd /Users/sai/Downloads/TUI && python -c "
import ast, glob
files = glob.glob('toggl/**/*.py', recursive=True)
total = annotated = 0
for f in sorted(files):
    if '__pycache__' in f: continue
    with open(f) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            total += 1
            if node.returns or all(a.arg not in ('self','cls','args','kwargs') and a.annotation for a in node.args.args):
                annotated += 1
print(f'{annotated}/{total} functions annotated ({annotated/total*100:.0f}%)')
"
```
Expected: 100% coverage or very close.
