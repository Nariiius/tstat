"""Typed dataclass models for core metric data structures.

These models document the shapes returned by ``DataCache`` query methods.
They are gradually adopted — existing dict consumers continue to work during
the transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectResult:
    """A single project's scored result from ``calculate()``.

    Each row is a 4-tuple ``(name, hours, rate, points)`` where points may be
    ``None`` for unscored projects.
    """

    name: str
    hours: float
    rate: float | None
    points: float | None


@dataclass
class DayMetrics:
    """Day-level aggregate metrics returned by ``DataCache.get_day_metrics()``."""

    label: str                       # ISO date string (YYYY-MM-DD)
    projects: dict[str, float]       # project_name → hours
    results: list[ProjectResult]     # scored project results
    negative_results: list[dict[str, Any]]  # raw logged-negative rows
    positive_results: list[dict[str, Any]]  # raw logged-positive rows
    earned: float                    # positive tracked points
    tracked_negative: float          # negative tracked points (absolute)
    logged_negative: float           # negative logged points (absolute)
    logged_positive: float           # positive logged points
    total_hours: float
    net: float                       # earned - tracked_negative - logged_negative + logged_positive
    delta: float                     # net - daily_target


@dataclass
class WeekDashboardRow:
    """A single row in the week-overview dashboard."""

    day: str                         # abbreviated day name (Mon, Tue, …)
    date: str                        # ISO date (YYYY-MM-DD)
    date_short: str                  # "dd Mon" format
    hours: float
    earned: float
    tracked_negative: float
    logged_positive: float
    positive: float                  # earned + logged_positive (alias)
    positive_total: float            # earned + logged_positive
    logged_negative: float
    negative: float                  # tracked_negative + logged_negative (alias)
    negative_total: float            # tracked_negative + logged_negative
    goal: float                      # daily_target
    delta: float                     # net - goal
    net: float
    has_activity: bool
    is_today: bool


@dataclass
class WeekDashboard:
    """Full week dashboard including per-day rows and summary."""

    rows: list[WeekDashboardRow]
    summary: dict[str, float]        # keys: days_counted, expected, actual, delta


@dataclass
class ReportSections:
    """Sectioned report data returned by ``DataCache.get_report_sections()``."""

    results: list[ProjectResult]
    negative_results: list[dict[str, Any]]
    positive_results: list[dict[str, Any]]
    positive: list[ProjectResult]    # results with points >= 0
    negative: list[ProjectResult]    # results with points < 0
    unscored: list[ProjectResult]    # results with points == None
    total_points: float
    total_hours: float


@dataclass
class SyncStatus:
    """Current sync/quota status returned by ``get_sync_status_data()``."""

    last_updated: str
    projects_cache_age_days: float | None
    current_week: str
    synced_weeks: int
    synced_days: int
    quota_remaining: int | None
    quota_limit: int | None
    quota_resets_in: int | None
