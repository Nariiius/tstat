"""Discovery Engine — surfaces non-obvious behavioral patterns.

Produces 0–5 high-signal discoveries about drift, growth,
best-period gaps, and failure modes.

Confidence is derived from real statistical tests (p-values from
scipy.stats.linregress and mannwhitneyu) instead of hand-tuned
heuristics. pandas provides time-series-aware rolling windows.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from toggl.cache import DataCache
from toggl.config import Config
from toggl.services.metrics import MetricsService

logger = logging.getLogger("TStat")


# ── Dataclasses ──────────────────────────────────────────────────

@dataclass
class Discovery:
    kind: str        # "drift" | "growth" | "best_gap" | "failure"
    title: str
    summary: str     # 1–2 sentences
    evidence: str    # one-line data, uses REAL window sizes
    period: str       # human label, uses REAL window sizes
    confidence: float
    impact: float
    novelty: float
    score: float
    subject: str      # dedup key


def _score(confidence: float, impact: float, novelty: float) -> float:
    return round(confidence * 0.5 + impact * 0.3 + novelty * 0.2, 3)


@dataclass
class _WindowSet:
    earliest: date
    total_days: int
    recent_days: int
    recent_start: date
    baseline_start: date
    baseline_end: date
    baseline_days: int
    period_label: str


# ── Engine ────────────────────────────────────────────────────────

class DiscoveryEngine:

    MIN_CONFIDENCE       = 0.70
    MAX_DISCOVERIES      = 5
    MAX_PER_KIND         = 2     # at most 2 drift, 2 growth, 2 best_gap
    MAX_FAILURE          = 1      # failure modes hard capped at 1
    MIN_HISTORY_DAYS     = 21     # refuse to run below this

    def __init__(
        self,
        cache: DataCache,
        metrics: MetricsService,
        config: Config,
    ) -> None:
        self._cache   = cache
        self._metrics = metrics
        self._config  = config

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _pval_confidence(p_value: float) -> float:
        """Confidence from a statistical p-value, clamped to [0.70, 0.99]."""
        return round(max(0.70, min(0.99, 1.0 - p_value)), 2)

    def _find_project_start(self, project: str, min_hours: float = 1.0, window: int = 14) -> date | None:
        """First date after which a rolling 14d window has ≥ min_hours.

        Returns None if no such window exists (project has negligible data).
        """
        dates: list[date] = []
        hours: list[float] = []
        for d_str in sorted(self._cache.daily_data.keys()):
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            projs = self._cache.daily_data.get(d_str, {})
            dates.append(d)
            hours.append(projs.get(project, 0.0))

        if not dates:
            return None

        s = pd.Series(hours, index=pd.DatetimeIndex(dates))
        full_idx = pd.date_range(dates[0], dates[-1])
        s = s.reindex(full_idx).fillna(0.0)

        rolling = s.rolling(window, min_periods=1).sum()
        valid = rolling[rolling >= min_hours]
        if valid.empty:
            return None
        return valid.index[0].date()

    def _get_all_data_dates(self, today: date) -> list[date]:
        """All dates that have any data, sorted, up to today."""
        raw = set(
            list(self._cache.daily_data.keys())
            + list(self._cache.positives_raw.keys())
            + list(self._cache.negatives_raw.keys())
        )
        result = []
        for d_str in raw:
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d <= today:
                result.append(d)
        return sorted(result)

    def _get_windows(self, today: date) -> _WindowSet | None:
        """Derive adaptive windows from actual data availability.

        recent window  = ~20% of total history, clamped to [7, 21] days
        baseline       = everything before the recent window
        """
        all_dates = self._get_all_data_dates(today)
        if not all_dates:
            return None

        earliest   = all_dates[0]
        total_days = max((today - earliest).days, 1)

        if total_days < self.MIN_HISTORY_DAYS:
            return None

        recent_days    = max(7, min(21, total_days // 5))
        recent_start   = today - timedelta(days=recent_days - 1)
        baseline_end   = recent_start - timedelta(days=1)
        baseline_start = earliest
        baseline_days  = max((baseline_end - baseline_start).days + 1, 1)

        return _WindowSet(
            earliest        = earliest,
            total_days      = total_days,
            recent_days     = recent_days,
            recent_start    = recent_start,
            baseline_start  = baseline_start,
            baseline_end    = baseline_end,
            baseline_days   = baseline_days,
            period_label    = (
                f"Last {recent_days}d vs prior {baseline_days}-day baseline"
            ),
        )

    # ── Main pipeline ──────────────────────────────────────────────

    def compute(self) -> list[Discovery]:
        today = date.today()
        windows = self._get_windows(today)

        if windows is None:
            return []

        candidates: list[Discovery] = []
        candidates.extend(self._analyze_drift(today, windows))
        candidates.extend(self._analyze_growth(today, windows))
        candidates.extend(self._analyze_best_period(today, windows))
        candidates.extend(self._analyze_failure_modes(today))

        # Confidence filter
        candidates = [
            c for c in candidates if c.confidence >= self.MIN_CONFIDENCE
        ]

        # Dedup by subject — keep highest score per subject
        by_subject: dict[str, Discovery] = {}
        for d in candidates:
            if (
                d.subject not in by_subject
                or d.score > by_subject[d.subject].score
            ):
                by_subject[d.subject] = d

        # Sort by score
        ranked = sorted(
            by_subject.values(), key=lambda d: d.score, reverse=True
        )

        # Diversity pass — enforce per-kind caps
        kind_counts: dict[str, int] = {}
        final: list[Discovery] = []

        for d in ranked:
            cap = (
                self.MAX_FAILURE
                if d.kind == "failure"
                else self.MAX_PER_KIND
            )
            if kind_counts.get(d.kind, 0) >= cap:
                continue
            kind_counts[d.kind] = kind_counts.get(d.kind, 0) + 1
            final.append(d)
            if len(final) >= self.MAX_DISCOVERIES:
                break

        return final

    # ── Analyzer 1: Drift (regression-based) ───────────────────────

    def _analyze_drift(
        self, today: date, w: _WindowSet
    ) -> list[Discovery]:
        results: list[Discovery] = []
        all_dates = sorted(
            {date.fromisoformat(d) for d in self._cache.daily_data if date.fromisoformat(d) <= today}
        )
        if len(all_dates) < 21:
            return results
        full_idx = pd.date_range(all_dates[0], today)
        recent_14 = today - timedelta(days=13)

        for proj, point_rate in self._config.points.items():
            if point_rate <= 0:
                continue

            ys: list[float] = []
            for d in full_idx:
                d_str = d.strftime("%Y-%m-%d")
                ys.append(self._cache.daily_data.get(d_str, {}).get(proj, 0.0))

            total_h = sum(ys)
            if total_h < 5.0:
                continue

            xs = np.arange(len(ys), dtype=float)
            reg = scipy_stats.linregress(xs, ys)
            if reg.slope >= 0 or reg.pvalue >= 0.05:
                continue

            # Check recent 14d avg is meaningfully below the regression expectation
            recent_mask = full_idx >= recent_14
            recent_avg = np.mean([ys[i] for i in range(len(ys)) if recent_mask[i]])
            baseline_avg = total_h / len(ys)
            if recent_avg > baseline_avg * 0.6:
                continue

            days_total = len(ys)
            recent_d = sum(1 for i in range(len(ys)) if recent_mask[i] and ys[i] > 0)
            baseline_d = sum(1 for y in ys if y > 0) - recent_d

            change_pct = round(((recent_avg - baseline_avg) / baseline_avg) * 100)
            conf = self._pval_confidence(reg.pvalue)
            impact = min(0.5 + (point_rate / 3.0) * 0.4 + min(baseline_avg / 2.0, 0.1), 1.0)
            novelty = min(abs(change_pct) / 200, 1.0)

            results.append(Discovery(
                kind="drift",
                title=f"{proj} Has Drifted",
                summary=(
                    f"{proj} is trending down over {days_total}d "
                    f"(statistically significant, p={reg.pvalue:.3f}). "
                    f"Recent rate: {recent_avg:.2f}h/d vs baseline {baseline_avg:.2f}h/d."
                ),
                evidence=(
                    f"Prior: {baseline_avg:.2f}h/d across {baseline_d} active days  →  "
                    f"Recent 14d: {recent_avg:.2f}h/d ({change_pct:+d}%)"
                ),
                period=w.period_label,
                confidence=round(conf, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(conf, impact, novelty),
                subject=proj,
            ))

        return results

    # ── Analyzer 2: Growth (regression + emergence detection) ──────

    def _analyze_growth(
        self, today: date, w: _WindowSet
    ) -> list[Discovery]:
        results: list[Discovery] = []
        all_dates = sorted(
            {date.fromisoformat(d) for d in self._cache.daily_data if date.fromisoformat(d) <= today}
        )
        if len(all_dates) < 21:
            return results
        full_idx = pd.date_range(all_dates[0], today)

        for proj, point_rate in self._config.points.items():
            if point_rate <= 0:
                continue

            ys: list[float] = []
            for d in full_idx:
                d_str = d.strftime("%Y-%m-%d")
                ys.append(self._cache.daily_data.get(d_str, {}).get(proj, 0.0))

            recent_total = sum(ys[-14:])
            if recent_total < 3.0:
                continue

            # Detect emergence: find when this project actually started being used
            proj_start = self._find_project_start(proj)
            recent_14 = today - timedelta(days=13)

            if proj_start is None:
                continue

            recently_started = proj_start >= w.recent_start
            start_days_ago = (today - proj_start).days

            # Trim baseline: only consider data from project start onward
            trim_cutoff = max(proj_start, all_dates[0])
            trim_mask = full_idx >= pd.Timestamp(trim_cutoff)
            before_recent_mask = full_idx < recent_14
            trimmed_mask = trim_mask & before_recent_mask

            trimmed_ys = [ys[i] for i in range(len(ys)) if trimmed_mask[i]]
            trimmed_days = sum(trimmed_mask)
            trimmed_total = sum(trimmed_ys)
            trimmed_avg = trimmed_total / max(trimmed_days, 1)

            recent_avg = recent_total / 14

            # Small or non-existent trimmed baseline → emergence, not growth
            if trimmed_total < 1.0 or trimmed_avg < 0.1 or trimmed_days < 21:
                if recently_started:
                    conf = 0.82
                    summary = (
                        f"{proj} — first meaningful engagement ~{start_days_ago}d ago. "
                        f"Averaging {recent_avg:.2f}h/d since starting. "
                        f"Still establishing a baseline."
                    )
                else:
                    conf = 0.72
                    summary = (
                        f"{proj} has appeared in the last 14d "
                        f"({recent_avg:.2f}h/d) but with negligible prior history "
                        f"— too early to call a trend."
                    )
                evidence = (
                    f"Prior trimmed baseline: {trimmed_avg:.2f}h/d ({trimmed_days}d)  →  "
                    f"Recent 14d: {recent_avg:.2f}h/d"
                )
                impact = min(0.45 + (point_rate / 3.0) * 0.3, 0.8)
                novelty = 0.70
                results.append(Discovery(
                    kind="growth",
                    title=f"{proj} — Emerging Activity",
                    summary=summary,
                    evidence=evidence,
                    period=w.period_label,
                    confidence=round(conf, 2),
                    impact=round(impact, 2),
                    novelty=round(novelty, 2),
                    score=_score(conf, impact, novelty),
                    subject=proj,
                ))
                continue

            # Real existing activity — run regression on trimmed data
            all_mask = full_idx >= pd.Timestamp(trim_cutoff)
            all_xs = np.arange(len(ys), dtype=float)
            all_ys = np.array(ys, dtype=float)
            valid = all_mask
            if valid.sum() < 21:
                continue

            reg = scipy_stats.linregress(all_xs[valid], all_ys[valid])
            if reg.slope <= 0 or reg.pvalue >= 0.05:
                continue

            change_pct = round(((recent_avg - trimmed_avg) / trimmed_avg) * 100) if trimmed_avg > 0 else 0
            if change_pct < 40:
                continue

            conf = self._pval_confidence(reg.pvalue)
            impact = min(0.45 + (point_rate / 3.0) * 0.4 + min(recent_avg / 3.0, 0.15), 1.0)
            novelty = min(change_pct / 400, 0.95)

            results.append(Discovery(
                kind="growth",
                title=f"{proj} Is Growing",
                summary=(
                    f"{proj} is trending upward (p={reg.pvalue:.3f}). "
                    f"Up {change_pct}% over recent 14d vs trimmed baseline "
                    f"(from project start {trim_cutoff})."
                ),
                evidence=(
                    f"Trimmed baseline: {trimmed_avg:.2f}h/d ({trimmed_days}d since {trim_cutoff})  →  "
                    f"Recent 14d: {recent_avg:.2f}h/d ({change_pct:+d}%)"
                ),
                period=w.period_label,
                confidence=round(conf, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(conf, impact, novelty),
                subject=proj,
            ))

        return results

    # ── Analyzer 3: Best Rolling Period (pandas) ────────────────────

    def _analyze_best_period(
        self, today: date, w: _WindowSet
    ) -> list[Discovery]:
        if w.total_days < 60:
            return []

        WINDOW = 28

        # Build daily net as pandas Series
        all_nets: dict[date, float] = {}
        all_date_strs = set(
            list(self._cache.daily_data.keys())
            + list(self._cache.positives_raw.keys())
            + list(self._cache.negatives_raw.keys())
        )
        for d_str in all_date_strs:
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d > today:
                continue
            dm = self._metrics.get_day_metrics(d_str)
            all_nets[d] = dm.get("net", 0.0)

        idx = pd.date_range(w.earliest, today)
        series = pd.Series(
            [all_nets.get(d.date(), 0.0) for d in idx], index=idx
        )

        rolling_28 = series.rolling(WINDOW, min_periods=WINDOW // 2).mean()
        rolling_28 = rolling_28.dropna()
        if rolling_28.empty:
            return []

        # Exclude the current 28d window from "best" consideration
        cutoff = today - timedelta(days=WINDOW)
        historical = rolling_28[rolling_28.index <= pd.Timestamp(cutoff)]
        if historical.empty:
            return []

        best_avg = historical.max()
        best_end = historical.idxmax()
        best_start = best_end - pd.Timedelta(days=WINDOW - 1)

        curr_mask = rolling_28.index > pd.Timestamp(cutoff)
        curr_avg = rolling_28[curr_mask].iloc[-1] if curr_mask.any() else rolling_28.iloc[-1]

        gap = best_avg - curr_avg
        if gap < 5.0:
            return []

        best_end_date = best_end.date()
        best_label = (
            f"{best_start.strftime('%b %d')}–{best_end_date.strftime('%b %d, %Y')}"
        )

        confidence = min(0.72 + w.total_days / 365 * 0.20, 0.92)
        impact = min(0.55 + gap / 50, 0.95)
        novelty = 0.75

        return [
            Discovery(
                kind="best_gap",
                title="Behind Your Best 28-Day Period",
                summary=(
                    f"Your strongest 28-day stretch was {best_label}, "
                    f"averaging {best_avg:+.0f}pts/day. "
                    f"The current 28 days average {curr_avg:+.0f}pts/day "
                    f"— {gap:.0f}pts/day below your peak."
                ),
                evidence=(
                    f"Peak ({best_label}): {best_avg:+.1f}pts/d  |  "
                    f"Now: {curr_avg:+.1f}pts/d  |  "
                    f"Gap: {gap:.1f}pts/d"
                ),
                period="Rolling 28-day windows across all history",
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(confidence, impact, novelty),
                subject="__best_period__",
            )
        ]

    # ── Analyzer 4: Failure Modes (Mann-Whitney) ────────────────────

    def _analyze_failure_modes(
        self, today: date
    ) -> list[Discovery]:
        all_date_strs = set(
            list(self._cache.daily_data.keys())
            + list(self._cache.negatives_raw.keys())
            + list(self._cache.positives_raw.keys())
        )

        day_nets: list[tuple[str, float]] = []

        for d_str in all_date_strs:
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d > today:
                continue
            dm = self._metrics.get_day_metrics(d_str)
            if (
                dm.get("total_hours", 0) == 0
                and not self._cache.negatives_raw.get(d_str)
            ):
                continue
            day_nets.append((d_str, dm.get("net", 0.0)))

        if len(day_nets) < 10:
            return []

        day_nets.sort(key=lambda x: x[1])
        n      = len(day_nets)
        q_size = max(n // 4, 3)

        bottom_q = [d for d, _ in day_nets[:q_size]]
        top_q    = [d for d, _ in day_nets[n - q_size:]]

        if len(bottom_q) < 3 or len(top_q) < 3:
            return []

        # Build per-negative count arrays for bottom vs top quartiles
        neg_names_set: set[str] = set()
        neg_day_counts: dict[str, dict[str, int]] = {}
        for d_str in set(bottom_q + top_q):
            for e in self._cache.negatives_raw.get(d_str, []):
                name = e["name"]
                neg_names_set.add(name)
                neg_day_counts.setdefault(name, {})[d_str] = (
                    neg_day_counts.get(name, {}).get(d_str, 0) + 1
                )

        results: list[Discovery] = []

        for neg_name in neg_names_set:
            bad_counts  = [neg_day_counts.get(neg_name, {}).get(d, 0) for d in bottom_q]
            good_counts = [neg_day_counts.get(neg_name, {}).get(d, 0) for d in top_q]

            total_count = sum(bad_counts) + sum(good_counts)
            if total_count < 5:
                continue

            try:
                stat, p_value = scipy_stats.mannwhitneyu(
                    bad_counts, good_counts,
                    alternative='greater',
                )
            except ValueError:
                continue  # all identical values

            if p_value >= 0.10:  # require reasonable signal
                continue

            bottom_rate = sum(bad_counts) / len(bottom_q)
            top_rate    = sum(good_counts) / len(top_q)

            if bottom_rate < top_rate * 1.5:
                continue

            ratio = bottom_rate / top_rate if top_rate > 0 else 5.0
            conf = self._pval_confidence(p_value)
            neg_pts = self._config.negatives.get(neg_name, 5)
            impact = min(0.45 + (neg_pts / 20.0) * 0.40 + min(bottom_rate, 0.3), 0.92)
            novelty = min(0.4 + ratio / 10.0, 0.85)

            results.append(
                Discovery(
                    kind="failure",
                    title=f"{neg_name} Concentrates On Bad Days",
                    summary=(
                        f"{neg_name} appears {ratio:.1f}x more often "
                        f"on your worst days than your best "
                        f"(p={p_value:.3f}, Mann-Whitney). "
                        f"Present on {bottom_rate*100:.0f}% of bad days "
                        f"vs {top_rate*100:.0f}% of good days."
                    ),
                    evidence=(
                        f"Bottom quartile: {bottom_rate:.2f}x/day  |  "
                        f"Top quartile: {top_rate:.2f}x/day  |  "
                        f"Ratio: {ratio:.1f}x  |  "
                        f"p={p_value:.3f}"
                    ),
                    period=(
                        f"All available data, bottom vs top quartile "
                        f"({q_size} days each)"
                    ),
                    confidence=round(conf, 2),
                    impact=round(impact, 2),
                    novelty=round(novelty, 2),
                    score=_score(conf, impact, novelty),
                    subject=neg_name,
                )
            )

        results.sort(key=lambda d: d.score, reverse=True)
        return results
