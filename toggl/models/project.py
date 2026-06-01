"""Dataclass models for project data structures.

These replace raw ``dict[str, Any]`` returns from ``MetricsService`` methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProjectHours:
    """A single project's accumulated hours within a date range.

    Returned by ``MetricsService.get_range_aggregate()`` and used in category tables.
    """

    name: str
    hours: float
    rate: float | None
    points: float | None


@dataclass
class RangeAggregate:
    """Aggregated data across a date range.

    Replaces the raw dict returned by ``MetricsService.get_range_aggregate()``.
    """

    results: list[ProjectHours]
    positive: list[ProjectHours]
    negative: list[ProjectHours]
    unscored: list[ProjectHours]
    positive_results: list[tuple[str, int, float, float]]
    negative_results: list[tuple[str, int, float, float]]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RangeAggregate:
        return cls(
            results=[ProjectHours(*r) for r in d["results"]],
            positive=[ProjectHours(*r) for r in d.get("positive", [])],
            negative=[ProjectHours(*r) for r in d.get("negative", [])],
            unscored=[ProjectHours(*r) for r in d.get("unscored", [])],
            positive_results=list(d.get("positive_results", [])),
            negative_results=list(d.get("negative_results", [])),
        )


@dataclass
class DailyDataPoint:
    """A single day's aggregate metrics from ``MetricsService.get_daily_data_for_range()``."""

    date: str
    net: float
    positive: float
    negative: float
    earned: float
    tracked_neg: float
    logged_pos: float
    logged_neg: float
    total_hours: float
    has_data: bool
