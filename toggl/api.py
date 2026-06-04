"""Toggl API helpers, quota management, rate limits."""

import sys
import os
import json
import logging
import threading
import urllib.request
import urllib.parse
import urllib.error
import base64

from typing import Any

from toggl.const import CONFIG_FILE, RED, RESET, YELLOW, CYAN, BOLD, DIM
from toggl.const import PROJECTS_FILE, PROJECTS_CACHE_MAX_AGE_DAYS, LOW_QUOTA_WARNING
from toggl.config import load_config

logger = logging.getLogger("TStat")


# ──────────────────────────────────────────────
# CUSTOM EXCEPTIONS
# ──────────────────────────────────────────────
class TogglRateLimitError(Exception):
    """Raised when Toggl API returns 402/429 rate limit."""
    def __init__(self, message: str = "", limit: int | None = None, remaining: int | None = None, resets_in: int | None = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.remaining = remaining
        self.resets_in = resets_in


class TogglAPIError(Exception):
    """Raised on non-rate-limit API errors from Toggl."""
    def __init__(self, message: str = "", status_code: int | None = None) -> None:
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


def _reset_api_stats() -> None:
    with _api_stats_lock:
        API_RUN_STATS["requests_made"] = 0
        API_RUN_STATS["remaining"] = None
        API_RUN_STATS["limit"] = None
        API_RUN_STATS["resets_in"] = None


def _normalize_headers(headers: dict) -> dict:
    return {k.lower(): v for k, v in headers.items()}


def _header_value(headers: dict, *names: str) -> str | None:
    normalized = _normalize_headers(headers)
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_quota_headers(headers: dict) -> None:
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


def _format_reset_window(secs: int | None) -> str:
    if secs is None:
        return "Unknown"
    mins, s = divmod(secs, 60)
    return f"{mins}m {s:02d}s" if mins else f"{s}s"


def _make_auth_request(url: str, token: str, method: str = "GET") -> tuple[Any, Any, Any]:
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
        # Capture error response body for debugging
        error_body = None
        try:
            error_body = e.read().decode() if hasattr(e, 'read') else None
        except:
            pass
        return error_body, headers, e.code
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return None, {}, str(e)


def toggl_request(endpoint: str, token: str) -> Any:
    url = "https://api.track.toggl.com/api/v9/" + endpoint
    logger.debug("API request: %s", endpoint)
    body, headers, err = _make_auth_request(url, token)
    if err is None:
        if body is None:
            raise TogglAPIError("API returned empty response", status_code=None)
        logger.debug("API response: %s — %d bytes", endpoint, len(body))
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
        secs = _parse_int(resets_in)
        if secs is not None:
            mins, s = divmod(secs, 60)
            wait = f"{mins}m {s:02d}s" if mins else f"{s}s"
            msg += f" — resets in {wait}"
        msg += f" (Remaining: {remaining}/{limit})"
        logger.warning("API rate limit: %s %s (%s/%s remaining)", endpoint, err, remaining, limit)
        raise TogglRateLimitError(msg, limit=limit, remaining=remaining, resets_in=resets_in)
    # Include error body in message for debugging
    error_detail = f" (body: {body})" if body else ""
    logger.error("API error: %s -> HTTP %s%s", endpoint, err, error_detail)
    raise TogglAPIError(f"API Error: {err} for endpoint {endpoint}{error_detail}", status_code=err)


def get_api_token() -> str:
    if os.environ.get("TOGGL_API_TOKEN"):
        logger.debug("Using API token from TOGGL_API_TOKEN environment variable")
        return os.environ.get("TOGGL_API_TOKEN")
    data = load_config()
    if data.get("api_token"):
        logger.debug("Using API token from config file")
        return data["api_token"]
    logger.error("API token not found in env var or config")
    raise TogglAPIError(
        "Toggl API Token not found. Please set the TOGGL_API_TOKEN environment variable "
        "or define 'api_token' in toggl_config.json."
    )



def get_projects_cache_age_days() -> float | None:
    if not os.path.exists(PROJECTS_FILE):
        return None
    from datetime import datetime
    age_secs = datetime.now().timestamp() - os.path.getmtime(PROJECTS_FILE)
    return age_secs / 86400.0


def is_projects_cache_stale(max_age_days: float = PROJECTS_CACHE_MAX_AGE_DAYS) -> bool:
    age_days = get_projects_cache_age_days()
    return age_days is None or age_days > max_age_days


def _confirm_sync_quota(token: str, estimated_requests: int, sync_label: str, prompt_on_warning: bool = True) -> bool:
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


def get_projects_map(token: str, use_cache: bool = False) -> dict:
    if use_cache and os.path.exists(PROJECTS_FILE):
        logger.debug("Using cached projects map from disk")
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): v for k, v in raw.items()}
    logger.debug("Fetching projects map from API")
    projects_data = toggl_request("me/projects?active=both", token)
    result = {p["id"]: p["name"] for p in projects_data}
    logger.debug("Projects map: %d projects fetched", len(result))
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in result.items()}, f, indent=2)
    return result
