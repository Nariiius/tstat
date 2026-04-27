"""Toggl API helpers, quota management, rate limits."""

import sys
import os
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
import base64

from toggl.const import CONFIG_FILE, RED, RESET, GREEN, YELLOW, CYAN, BOLD, DIM
from toggl.const import PROJECTS_FILE, PROJECTS_CACHE_MAX_AGE_DAYS, LOW_QUOTA_WARNING
from toggl.config import load_config


# ──────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ──────────────────────────────────────────────
class TogglRateLimitError(Exception):
    """Raised when Toggl API returns 402/429 rate limit."""
    def __init__(self, message="", limit=None, remaining=None, resets_in=None):
        super().__init__(message)
        self.limit = limit
        self.remaining = remaining
        self.resets_in = resets_in


class TogglAPIError(Exception):
    """Raised on non-rate-limit API errors from Toggl."""
    def __init__(self, message="", status_code=None):
        super().__init__(message)
        self.status_code = status_code


# ──────────────────────────────────────────────
# API RUN STATS (thread-safe)
# ──────────────────────────────────────────────
API_RUN_STATS = {
    "requests_made": 0,
    "remaining": None,
    "limit": None,
    "resets_in": None,
}
_api_stats_lock = threading.Lock()


def _reset_api_stats():
    with _api_stats_lock:
        API_RUN_STATS["requests_made"] = 0
        API_RUN_STATS["remaining"] = None
        API_RUN_STATS["limit"] = None
        API_RUN_STATS["resets_in"] = None


def _normalize_headers(headers):
    return {k.lower(): v for k, v in headers.items()}


def _header_value(headers, *names):
    normalized = _normalize_headers(headers)
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_quota_headers(headers):
    remaining = _parse_int(_header_value(headers, "X-Toggl-Quota-Remaining"))
    limit = _parse_int(_header_value(headers, "X-Toggl-Quota-Limit"))
    resets_in = _parse_int(_header_value(headers, "X-Toggl-Quota-Resets-In"))
    with _api_stats_lock:
        if remaining is not None:
            API_RUN_STATS["remaining"] = remaining
        if limit is not None:
            API_RUN_STATS["limit"] = limit
        if resets_in is not None:
            API_RUN_STATS["resets_in"] = resets_in


def _format_reset_window(secs):
    if secs is None:
        return "Unknown"
    mins, s = divmod(secs, 60)
    return f"{mins}m {s:02d}s" if mins else f"{s}s"


def _print_api_usage_summary():
    print(f"\n  {BOLD}{CYAN}SYNC API USAGE{RESET}")
    print("  " + "─" * 35)
    print(f"  Requests used       {CYAN}{BOLD}{API_RUN_STATS['requests_made']}{RESET}")
    if API_RUN_STATS["remaining"] is not None:
        limit = API_RUN_STATS["limit"] if API_RUN_STATS["limit"] is not None else "?"
        print(
            f"  Quota remaining     {YELLOW}{BOLD}{API_RUN_STATS['remaining']}/{limit}{RESET}"
        )
    if API_RUN_STATS["resets_in"] is not None:
        wait = _format_reset_window(API_RUN_STATS["resets_in"])
        print(f"  Window resets in    {DIM}{wait}{RESET}")
    print()


def _make_auth_request(url, token, method="GET"):
    auth_string = f"{token}:api_token"
    b64_auth = base64.b64encode(auth_string.encode()).decode()
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Basic {b64_auth}")
    req.add_header("Content-Type", "application/json")
    with _api_stats_lock:
        API_RUN_STATS["requests_made"] += 1
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode() if method != "HEAD" else None
            headers = dict(response.headers)
            _record_quota_headers(headers)
            return body, headers, None
    except urllib.error.HTTPError as e:
        headers = dict(e.headers) if e.headers else {}
        _record_quota_headers(headers)
        return None, headers, e.code
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, {}, str(e)


def toggl_request(endpoint, token):
    url = "https://api.track.toggl.com/api/v9/" + endpoint
    body, headers, err = _make_auth_request(url, token)
    if err is None:
        if body is None:
            raise TogglAPIError("API returned empty response", status_code=None)
        return json.loads(body)
    if err in (402, 429):
        resets_in = headers.get("X-Toggl-Quota-Resets-In") or headers.get(
            "x-toggl-quota-resets-in"
        )
        remaining = headers.get("X-Toggl-Quota-Remaining") or headers.get(
            "x-toggl-quota-remaining", "0"
        )
        limit = headers.get("X-Toggl-Quota-Limit") or headers.get(
            "x-toggl-quota-limit", "30"
        )
        msg = f"Rate limit reached ({limit} req/hr)"
        if resets_in:
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            msg += f" — resets in {wait}"
        msg += f" (Remaining: {remaining}/{limit})"
        raise TogglRateLimitError(msg, limit=limit, remaining=remaining, resets_in=resets_in)
    raise TogglAPIError(f"API Error: {err} for endpoint {endpoint}", status_code=err)


def check_quota(token):
    url = "https://api.track.toggl.com/api/v9/me"
    print(f"\n  {BOLD}{CYAN}API QUOTA STATUS{RESET}")
    print("  " + "─" * 35)
    body, headers, err = _make_auth_request(url, token)
    if err is None:
        remaining = headers.get("X-Toggl-Quota-Remaining") or headers.get("x-toggl-quota-remaining", "Unknown")
        resets_in = headers.get("X-Toggl-Quota-Resets-In") or headers.get("x-toggl-quota-resets-in", "Unknown")
        print(f"  {GREEN}✓ Request successful{RESET}")
        print(f"  Requests remaining  {CYAN}{BOLD}{remaining}{RESET}")
        if resets_in != "Unknown":
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            print(f"  Window resets in    {YELLOW}{BOLD}{wait}{RESET}")
        else:
            print(f"  Window resets in    {DIM}Unknown{RESET}")
    elif err == 429:
        print(f"  {RED}✗ HTTP 429 — Rate limit exceeded.{RESET}")
        print(f"  {DIM}Making requests too fast. Safe limit is ~1 req/sec.{RESET}")
    elif err == 402:
        resets_in = headers.get("X-Toggl-Quota-Resets-In") or headers.get("x-toggl-quota-resets-in", "Unknown")
        print(f"  {RED}✗ HTTP 402 — Hourly quota exhausted.{RESET}")
        if resets_in != "Unknown":
            secs = int(resets_in)
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            print(f"  Window resets in    {YELLOW}{BOLD}{wait}{RESET}")
    else:
        print(f"  {RED}✗ HTTP {err}{RESET}")
    print()


def get_api_token():
    if os.environ.get("TOGGL_API_TOKEN"):
        return os.environ.get("TOGGL_API_TOKEN")
    data = load_config()
    if data.get("api_token"):
        return data["api_token"]
    print(f"{YELLOW}Toggl API Token not found.{RESET}")
    print(f"Find it here: {CYAN}https://track.toggl.com/profile{RESET}")
    token = input("Enter your Toggl API Token: ").strip()
    if not token:
        print(f"{RED}Error: API Token is required.{RESET}")
        sys.exit(1)
    data["api_token"] = token
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)
    print(f"{DIM}Token saved to {CONFIG_FILE}{RESET}\n")
    return token


def _prompt_yes_no(prompt):
    while True:
        ans = input(prompt).strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print(f"{YELLOW}Please enter 'y' or 'n'.{RESET}")


def get_projects_cache_age_days():
    if not os.path.exists(PROJECTS_FILE):
        return None
    from datetime import datetime
    age_secs = datetime.now().timestamp() - os.path.getmtime(PROJECTS_FILE)
    return age_secs / 86400.0


def is_projects_cache_stale(max_age_days=PROJECTS_CACHE_MAX_AGE_DAYS):
    age_days = get_projects_cache_age_days()
    return age_days is None or age_days > max_age_days


def _confirm_sync_quota(token, estimated_requests, sync_label, prompt_on_warning=True):
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
    return _prompt_yes_no(f"{YELLOW}Continue sync anyway? (y/n): {RESET}")


def get_projects_map(token, use_cache=False):
    if use_cache and os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
    projects_data = toggl_request("me/projects", token)
    result = {p["id"]: p["name"] for p in projects_data if p.get("active")}
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in result.items()}, f, indent=2)
    return result
