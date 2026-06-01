"""Dataclass models for logged activity (negative/positive) data structures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActivityEntry:
    """A single logged action row from the negatives or positives CSV."""

    date: str
    name: str
    points: float


@dataclass
class ActivityTotals:
    """Aggregated totals for a logged action across a date range.

    Produced by ``calculate_logged_activity_totals()``: (name, count, points_per_event, total).
    """

    name: str
    count: int
    points_per_event: float
    total: float


@dataclass
class MonthlyAggregate:
    """Aggregate metrics for a single calendar month."""

    month: str
    hours: float
    net: float
