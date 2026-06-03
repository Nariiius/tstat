"""Recent-day context for playbook and coach — concrete lookback, not lifetime stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from toggl.cache import DataCache
from toggl.services.metrics import MetricsService


@dataclass
class DaySnapshot:
    date_str: str
    label: str
    net: float
    positives: list[str]
    negatives: list[str]
    top_project: str | None
    top_project_hours: float


@dataclass
class RecentContext:
    days: list[DaySnapshot] = field(default_factory=list)
    yesterday: DaySnapshot | None = None
    best_recent: DaySnapshot | None = None
    worst_recent: DaySnapshot | None = None
    neg_counts_7d: dict[str, int] = field(default_factory=dict)
    pos_counts_7d: dict[str, int] = field(default_factory=dict)
    positive_lift: dict[str, float] = field(default_factory=dict)


def build_recent_context(
    metrics: MetricsService,
    cache: DataCache,
    *,
    lookback_days: int = 14,
) -> RecentContext:
    today = date.today()
    start = today - timedelta(days=lookback_days)
    raw = metrics.get_daily_data_for_range(start, today)
    active = [d for d in raw if d.get("has_data")]

    snapshots: list[DaySnapshot] = []
    for d in active:
        d_str = d["date"]
        try:
            dd = date.fromisoformat(d_str)
        except ValueError:
            continue
        if dd >= today:
            continue
        pos_names = [e["name"] for e in cache.positives_raw.get(d_str, [])]
        neg_names = [e["name"] for e in cache.negatives_raw.get(d_str, [])]
        projs = cache.daily_data.get(d_str, {}) or {}
        top_p, top_h = None, 0.0
        if projs:
            top_p = max(projs.items(), key=lambda x: x[1])[0]
            top_h = projs[top_p]
        snapshots.append(
            DaySnapshot(
                date_str=d_str,
                label=dd.strftime("%a %d %b"),
                net=d["net"],
                positives=pos_names,
                negatives=neg_names,
                top_project=top_p,
                top_project_hours=top_h,
            )
        )

    snapshots.sort(key=lambda s: s.date_str)
    ctx = RecentContext(days=snapshots[-7:])

    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    for s in snapshots:
        if s.date_str == yesterday_str:
            ctx.yesterday = s
            break

    if snapshots:
        ctx.best_recent = max(snapshots, key=lambda s: s.net)
        ctx.worst_recent = min(snapshots, key=lambda s: s.net)

    last_7 = snapshots[-7:]
    for s in last_7:
        for n in s.negatives:
            ctx.neg_counts_7d[n] = ctx.neg_counts_7d.get(n, 0) + 1
        for n in s.positives:
            ctx.pos_counts_7d[n] = ctx.pos_counts_7d.get(n, 0) + 1

    for name in set(ctx.pos_counts_7d) | set(ctx.neg_counts_7d):
        with_net: list[float] = []
        without_net: list[float] = []
        for s in last_7:
            has = name in s.positives or name in s.negatives
            if has:
                with_net.append(s.net)
            else:
                without_net.append(s.net)
        if len(with_net) >= 2 and len(without_net) >= 2:
            ctx.positive_lift[name] = (
                sum(with_net) / len(with_net) - sum(without_net) / len(without_net)
            )

    return ctx


def format_day_net(net: float) -> str:
    if net >= 0:
        return f"+{net:.1f}"
    return f"{net:.1f}"
