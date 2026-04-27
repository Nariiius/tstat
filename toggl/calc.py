"""Calculation engine and format helpers."""

from toggl.config import POINTS, NEGATIVES, POSITIVES, DAILY_TARGET


def calculate(projects):
    results = []
    for name, hours in projects.items():
        rate = POINTS.get(name)
        pts = round(hours * rate, 2) if rate is not None else None
        results.append((name, hours, rate, pts))

    def sort_key(r):
        if r[2] is None:
            return (1, 0, 0)
        return (0, -r[2], -(r[3] or 0))

    results.sort(key=sort_key)
    return results


def get_negative_catalog_rows():
    return [(name, NEGATIVES[name]) for name in NEGATIVES]


def get_positive_catalog_rows():
    return [(name, POSITIVES[name]) for name in POSITIVES]


def format_signed(value):
    if abs(value) < 0.05:
        value = 0.0
    return f"+{value:.1f}" if value > 0 else (f"{value:.1f}" if value < 0 else "0.0")
