"""Calculation engine and format helpers."""

from toggl.config import POINTS, NEGATIVES, POSITIVES, get_daily_target


def calculate_logged_activity_totals(
    entries: list[dict[str, str | float]],
    config_points: dict[str, int | float],
    sign: int = 1,
) -> list[tuple[str, int, float, float]]:
    """Aggregate logged activity entries into (name, count, points_per_event, total_points).

    Args:
        entries: List of {"name": str, "points": float} — one dict per logged occurrence
                 (already filtered to the selected timeframe).  CSV stores absolute
                 (positive) point values for both positives and negatives.
        config_points: Dict of activity name → configured points_per_event value
                       (absolute, positive).
        sign: 1 for positives, -1 for negatives.  Applied to points_per_event and
              total_points so the UI receives signed values.

    Returns:
        List of (name, count, points_per_event, total_points) tuples, sorted by name.
        total_points = count × points_per_event (signed).
    """
    counts: dict[str, int] = {}
    totals: dict[str, float] = {}
    per_event: dict[str, float] = {}

    for entry in entries:
        name = entry["name"]
        counts[name] = counts.get(name, 0) + 1
        totals[name] = totals.get(name, 0.0) + entry["points"]
        if name not in per_event:
            # Config stores absolute values — apply sign for display.
            per_event[name] = sign * abs(config_points.get(name, 0.0))

    results = []
    for name in sorted(counts.keys()):
        count = counts[name]
        points_per_event = per_event[name]
        total_points = round(sign * abs(totals[name]), 1)
        results.append((name, count, points_per_event, total_points))

    return results


def calculate(projects: dict[str, float]) -> list[tuple[str, float, float | None, float | None]]:
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


def get_negative_catalog_rows() -> list[tuple[str, float]]:
    return [(name, NEGATIVES[name]) for name in NEGATIVES]


def get_positive_catalog_rows() -> list[tuple[str, float]]:
    return [(name, POSITIVES[name]) for name in POSITIVES]


def format_signed(value: float) -> str:
    if abs(value) < 0.05:
        value = 0.0
    return f"+{value:.1f}" if value > 0 else (f"{value:.1f}" if value < 0 else "0.0")
