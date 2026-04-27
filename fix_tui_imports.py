import re

with open("toggl/tui.py", "r") as f:
    content = f.read()

# Replace CLI imports with their implementation just like before
old_imports = """from toggl.cli import (
    get_sync_status_data, get_negatives_for_context, get_positives_for_context,
    get_all_time_data, get_data_for_week, get_week_neg_breakdown, get_week_pos_breakdown,
)"""

new_helpers = """def get_sync_status_data():
    history = _load_history()
    from toggl.api import get_projects_cache_age_days, API_RUN_STATS
    return {
        "last_updated": get_last_updated_str(),
        "projects_cache_age_days": get_projects_cache_age_days(),
        "current_week": get_current_week(),
        "synced_weeks": history.get("synced_weeks", {}),
        "synced_days": history.get("synced_days", {}),
        "quota_remaining": API_RUN_STATS["remaining"],
        "quota_limit": API_RUN_STATS["limit"],
        "quota_resets_in": API_RUN_STATS["resets_in"],
    }

def time_left_in_week():
    from datetime import datetime, timedelta
    now = datetime.now()
    sunday = now + timedelta(days=(6 - now.weekday()))
    end = sunday.replace(hour=23, minute=59, second=59)
    diff = end - now
    if diff.total_seconds() < 0:
        return ""
    days, sec = diff.days, diff.seconds
    hr = sec // 3600
    mn = (sec % 3600) // 60
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hr > 0: parts.append(f"{hr}h")
    parts.append(f"{mn}m")
    return " ".join(parts)"""

content = content.replace(old_imports, new_helpers)

# Replace cache method calls
content = content.replace("get_negatives_for_context", "cache.get_negatives_for_context")
content = content.replace("get_positives_for_context", "cache.get_positives_for_context")
content = content.replace("get_all_time_data", "cache.get_all_time_projects")
content = content.replace("get_data_for_week", "cache.get_week_projects")
content = content.replace("get_week_neg_breakdown", "cache.get_week_neg_breakdown")
content = content.replace("get_week_pos_breakdown", "cache.get_week_pos_breakdown")

# Fix time_left_in_week local import inside refresh_recovery_view
content = content.replace("from toggl.cli import time_left_in_week\n", "")

# We accidentally duplicated cache.cache.get... since we globally replaced it above. Let's fix that
content = content.replace("cache.cache.", "cache.")
content = content.replace("self._data_cache.cache.", "self._data_cache.")
# get_sync_status_data was also incorrectly prefixed
content = content.replace("cache.get_sync_status_data", "get_sync_status_data")

with open("toggl/tui.py", "w") as f:
    f.write(content)
