"""Discovery Engine — surfaces non-obvious behavioral patterns.

Produces 0–4 high-signal discoveries about drift, growth,
best-period gaps, and failure modes.

Per-analyzer lookback windows are configurable. Confidence is derived
from real statistical tests (p-values from scipy.stats.linregress and
mannwhitneyu). pandas provides time-series-aware rolling windows.
"""

from __future__ import annotations

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
    evidence: str    # one-line data
    period: str      # human label
    confidence: float
    impact: float
    novelty: float
    score: float
    subject: str     # dedup key
    importance: float = 0.0  # historical_hours × point_rate


def _score(confidence: float, impact: float, novelty: float) -> float:
    return round(confidence * 0.5 + impact * 0.3 + novelty * 0.2, 3)


# ── Engine ────────────────────────────────────────────────────────

class DiscoveryEngine:

    MIN_CONFIDENCE       = 0.70
    MIN_SIGNIFICANCE     = 0.72   # empty if top score below this
    MAX_DISCOVERIES      = 8
    MAX_PER_KIND         = 2      # at most 2 per kind
    MAX_FAILURE          = 2      # at most 2 failure-mode findings
    MAX_FAILURE          = 1
    PVALUE_THRESHOLD     = 0.10

    # Default lookback windows (overridden by config)
    DEFAULT_LOOKBACK = {
        "drift": 60,
        "growth": 60,
        "failure": 90,
        "best_period": 120,
    }

    def __init__(
        self,
        cache: DataCache,
        metrics: MetricsService,
        config: Config,
    ) -> None:
        self._cache = cache
        self._metrics = metrics
        self._config = config
        self._lookback = {**self.DEFAULT_LOOKBACK, **config.discovery_lookback}
        self._discovery_ignore = config.discovery_ignore

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _pval_confidence(p_value: float) -> float:
        """Confidence from a statistical p-value, clamped to [0.70, 0.99]."""
        return round(max(0.70, min(0.99, 1.0 - p_value)), 2)

    def _get_data_dates_within(self, today: date, lookback_days: int) -> list[date]:
        """All dates with data, within lookback_days of today."""
        cutoff = today - timedelta(days=lookback_days)
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
            if cutoff <= d <= today:
                result.append(d)
        return sorted(result)

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

    def _compute_importance(self, name: str, total_hours: float) -> float:
        """Importance = historical_hours × point_rate."""
        rate = self._config.points.get(name, 0)
        return total_hours * float(rate) if rate else 0.0

    # ── Main pipeline ──────────────────────────────────────────────

    def compute(self) -> list[Discovery]:
        today = date.today()

        candidates: list[Discovery] = []
        candidates.extend(self._analyze_drift(today))
        candidates.extend(self._analyze_growth(today))
        candidates.extend(self._analyze_best_period(today))
        candidates.extend(self._analyze_failure_modes(today))

        # Discovery ignore filter
        candidates = [c for c in candidates if c.subject not in self._discovery_ignore]

        # Confidence filter
        candidates = [c for c in candidates if c.confidence >= self.MIN_CONFIDENCE]

        # Dedup by subject — keep highest score per subject
        by_subject: dict[str, Discovery] = {}
        for d in candidates:
            if d.subject not in by_subject or d.score > by_subject[d.subject].score:
                by_subject[d.subject] = d

        ranked = sorted(by_subject.values(), key=lambda d: d.score, reverse=True)

        # Importance weighting — blend score with normalized importance
        if ranked:
            max_imp = max(d.importance for d in ranked) or 1.0
            for d in ranked:
                norm_imp = d.importance / max_imp
                d.score = round(d.score * 0.6 + norm_imp * 0.4, 3)
            ranked.sort(key=lambda d: d.score, reverse=True)

        # Diversity pass — enforce per-kind caps
        kind_counts: dict[str, int] = {}
        final: list[Discovery] = []

        for d in ranked:
            cap = self.MAX_FAILURE if d.kind == "failure" else self.MAX_PER_KIND
            if kind_counts.get(d.kind, 0) >= cap:
                continue
            kind_counts[d.kind] = kind_counts.get(d.kind, 0) + 1
            final.append(d)
            if len(final) >= self.MAX_DISCOVERIES:
                break

        # Minimum significance gate
        if final and final[0].score < self.MIN_SIGNIFICANCE:
            return []

        return final

    # ── Analyzer 1: Drift (regression-based, 60d window) ──────────

    def _analyze_drift(self, today: date) -> list[Discovery]:
        lookback = self._lookback["drift"]
        all_dates = self._get_data_dates_within(today, lookback)
        if len(all_dates) < 21:
            return []

        results: list[Discovery] = []
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
            if total_h < 3.0:
                continue

            xs = np.arange(len(ys), dtype=float)
            reg = scipy_stats.linregress(xs, ys)
            if reg.slope >= 0 or reg.pvalue >= self.PVALUE_THRESHOLD:
                continue

            recent_mask = full_idx >= pd.Timestamp(recent_14)
            recent_avg = np.mean([ys[i] for i in range(len(ys)) if recent_mask[i]])
            baseline_avg = total_h / len(ys)
            if recent_avg > baseline_avg * 0.65:
                continue

            days_total = len(ys)
            change_pct = round(((recent_avg - baseline_avg) / baseline_avg) * 100) if baseline_avg > 0 else 0
            conf = self._pval_confidence(reg.pvalue)
            impact = min(0.5 + (point_rate / 3.0) * 0.4 + min(baseline_avg / 2.0, 0.1), 1.0)
            novelty = min(abs(change_pct) / 200, 1.0)
            importance = self._compute_importance(proj, total_h)

            results.append(Discovery(
                kind="drift",
                title=f"{proj} Has Drifted",
                summary=(
                    f"{proj} is trending down over {days_total}d. "
                    f"Recent: {recent_avg:.1f}h/d vs baseline {baseline_avg:.1f}h/d "
                    f"({change_pct:+d}%)."
                ),
                evidence=(
                    f"{baseline_avg:.1f}h/d → {recent_avg:.1f}h/d ({change_pct:+d}%)"
                ),
                period=f"Last {lookback}d",
                confidence=round(conf, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(conf, impact, novelty),
                subject=proj,
                importance=round(importance, 2),
            ))

        return results

    # ── Analyzer 2: Growth (regression only, no emergence) ────────

    def _analyze_growth(self, today: date) -> list[Discovery]:
        lookback = self._lookback["growth"]
        all_dates = self._get_data_dates_within(today, lookback)
        if len(all_dates) < 21:
            return []

        results: list[Discovery] = []
        full_idx = pd.date_range(all_dates[0], today)
        recent_14 = today - timedelta(days=13)

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

            # Only report statistically significant upward trends
            xs = np.arange(len(ys), dtype=float)
            reg = scipy_stats.linregress(xs, ys)
            if reg.slope <= 0 or reg.pvalue >= self.PVALUE_THRESHOLD:
                continue

            before_mask = full_idx < pd.Timestamp(recent_14)
            before_avg = np.mean([ys[i] for i in range(len(ys)) if before_mask[i]]) if before_mask.any() else 0
            recent_avg = recent_total / 14

            if before_avg < 0.1:
                continue  # Skip if no meaningful baseline

            change_pct = round(((recent_avg - before_avg) / before_avg) * 100) if before_avg > 0 else 0
            if change_pct < 25:
                continue

            total_h = sum(ys)
            conf = self._pval_confidence(reg.pvalue)
            impact = min(0.45 + (point_rate / 3.0) * 0.4 + min(recent_avg / 3.0, 0.15), 1.0)
            novelty = min(change_pct / 400, 0.95)
            importance = self._compute_importance(proj, total_h)

            results.append(Discovery(
                kind="growth",
                title=f"{proj} Is Growing",
                summary=(
                    f"{proj} is trending upward. "
                    f"Up {change_pct}% over recent 14d vs prior baseline."
                ),
                evidence=(
                    f"{before_avg:.1f}h/d → {recent_avg:.1f}h/d ({change_pct:+d}%)"
                ),
                period=f"Last {lookback}d",
                confidence=round(conf, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(conf, impact, novelty),
                subject=proj,
                importance=round(importance, 2),
            ))

        return results

    # ── Analyzer 3: Best Period (120d window, importance-weighted diffs) ──

    def _analyze_best_period(self, today: date) -> list[Discovery]:
        lookback = self._lookback["best_period"]
        all_dates = self._get_data_dates_within(today, lookback)
        total_days = (today - all_dates[0]).days if all_dates else 0
        if total_days < 42:
            return []

        WINDOW = 28

        # Build daily net series
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
            cutoff = today - timedelta(days=lookback)
            if d < cutoff or d > today:
                continue
            dm = self._metrics.get_day_metrics(d_str)
            all_nets[d] = dm.get("net", 0.0)

        idx = pd.date_range(all_dates[0], today)
        series = pd.Series(
            [all_nets.get(d.date(), 0.0) for d in idx], index=idx
        )

        rolling_28 = series.rolling(WINDOW, min_periods=WINDOW // 2).mean().dropna()
        if rolling_28.empty:
            return []

        # Exclude current 28d from "best" consideration
        cutoff_date = today - timedelta(days=WINDOW)
        historical = rolling_28[rolling_28.index <= pd.Timestamp(cutoff_date)]
        if historical.empty:
            return []

        best_avg = historical.max()
        best_end = historical.idxmax()
        best_start = best_end - pd.Timedelta(days=WINDOW - 1)

        curr_avg = rolling_28.iloc[-1]
        gap = best_avg - curr_avg
        if gap < 5.0:
            return []

        best_end_date = best_end.date()
        best_label = f"{best_start.strftime('%b %d')}–{best_end_date.strftime('%b %d, %Y')}"

        # Compute activity-level differences weighted by importance
        best_start_date = best_start.date()
        diff_scores: list[tuple[str, float]] = []

        for proj, point_rate in self._config.points.items():
            if point_rate <= 0:
                continue
            # Hours in best period
            best_hours = 0.0
            best_days = 0
            d = best_start_date
            while d <= best_end_date:
                d_str = d.strftime("%Y-%m-%d")
                best_hours += self._cache.daily_data.get(d_str, {}).get(proj, 0.0)
                best_days += 1
                d += timedelta(days=1)

            # Hours in current 28d
            curr_hours = 0.0
            curr_days = 0
            d = cutoff_date.date() if hasattr(cutoff_date, 'date') else today - timedelta(days=WINDOW)
            while d <= today:
                d_str = d.strftime("%Y-%m-%d")
                curr_hours += self._cache.daily_data.get(d_str, {}).get(proj, 0.0)
                curr_days += 1
                d += timedelta(days=1)

            best_rate = best_hours / max(best_days, 1)
            curr_rate = curr_hours / max(curr_days, 1)
            if best_rate < 0.1:
                continue

            drop_pct = ((best_rate - curr_rate) / best_rate) * 100 if best_rate > 0 else 0
            if drop_pct < 10:
                continue

            total_h = best_hours + curr_hours
            importance = total_h * float(point_rate)
            diff_score = drop_pct * importance / 100.0
            diff_scores.append((proj, diff_score))

        diff_scores.sort(key=lambda x: -x[1])
        top_diffs = diff_scores[:6]

        diff_lines = "\n".join(f"  - {name}" for name, _ in top_diffs) if top_diffs else ""

        confidence = min(0.72 + total_days / 365 * 0.20, 0.92)
        impact = min(0.55 + gap / 50, 0.95)
        novelty = 0.75

        summary = (
            f"Best 28-day period: {best_label} ({best_avg:+.0f}/day). "
            f"Current: {curr_avg:+.0f}/day."
        )
        if top_diffs:
            summary += f" Largest differences:\n{diff_lines}"

        return [
            Discovery(
                kind="best_gap",
                title="What Changed Since Your Best Period",
                summary=summary,
                evidence=(
                    f"Peak ({best_label}): {best_avg:+.1f}/d  |  "
                    f"Now: {curr_avg:+.1f}/d  |  Gap: {gap:.1f}/d"
                ),
                period=f"Last {lookback}d",
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(confidence, impact, novelty),
                subject="__best_period__",
                importance=round(gap * 10, 2),
            )
        ]

    # ── Analyzer 4: Failure Modes (Mann-Whitney + presence ratio) ──

    def _analyze_failure_modes(self, today: date) -> list[Discovery]:
        lookback = self._lookback["failure"]
        cutoff = today - timedelta(days=lookback)

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
            if d < cutoff or d > today:
                continue
            dm = self._metrics.get_day_metrics(d_str)
            if dm.get("total_hours", 0) == 0 and not self._cache.negatives_raw.get(d_str):
                continue
            day_nets.append((d_str, dm.get("net", 0.0)))

        if len(day_nets) < 10:
            return []

        day_nets.sort(key=lambda x: x[1])
        n = len(day_nets)
        q_size = max(n // 4, 3)

        bottom_q = [d for d, _ in day_nets[:q_size]]
        top_q = [d for d, _ in day_nets[n - q_size:]]

        if len(bottom_q) < 3 or len(top_q) < 3:
            return []

        # Build per-negative count arrays
        neg_names_set: set[str] = set()
        neg_day_counts: dict[str, dict[str, int]] = {}
        for d_str in set(bottom_q + top_q):
            for e in self._cache.negatives_raw.get(d_str, []):
                name = e["name"]
                neg_names_set.add(name)
                neg_day_counts.setdefault(name, {})[d_str] = (
                    neg_day_counts.get(name, {}).get(d_str, 0) + 1
                )

        # Also compute presence ratio across ALL days (coach-style)
        all_neg_days: dict[str, int] = {}
        all_positive_days = 0
        all_negative_days = 0
        for d_str, net in day_nets:
            if net < 0:
                all_negative_days += 1
            else:
                all_positive_days += 1
            for e in self._cache.negatives_raw.get(d_str, []):
                all_neg_days[e["name"]] = all_neg_days.get(e["name"], 0) + 1

        results: list[Discovery] = []

        for neg_name in neg_names_set:
            bad_counts = [neg_day_counts.get(neg_name, {}).get(d, 0) for d in bottom_q]
            good_counts = [neg_day_counts.get(neg_name, {}).get(d, 0) for d in top_q]

            total_count = sum(bad_counts) + sum(good_counts)
            if total_count < 5:
                continue

            try:
                stat, p_value = scipy_stats.mannwhitneyu(
                    bad_counts, good_counts, alternative='greater',
                )
            except ValueError:
                continue

            if p_value >= self.PVALUE_THRESHOLD:
                continue

            bottom_rate = sum(bad_counts) / len(bottom_q)
            top_rate = sum(good_counts) / len(top_q)

            if bottom_rate < top_rate * 1.5:
                continue

            ratio = bottom_rate / top_rate if top_rate > 0 else 5.0
            conf = self._pval_confidence(p_value)
            neg_pts = self._config.negatives.get(neg_name, 5)
            impact = min(0.45 + (neg_pts / 20.0) * 0.40 + min(bottom_rate, 0.3), 0.92)
            novelty = min(0.4 + ratio / 10.0, 0.85)

            # Presence ratio (absorbed from coach)
            neg_on_bad = sum(1 for d_str, net in day_nets if net < 0 and any(
                e["name"] == neg_name for e in self._cache.negatives_raw.get(d_str, [])
            ))
            neg_on_good = sum(1 for d_str, net in day_nets if net >= 0 and any(
                e["name"] == neg_name for e in self._cache.negatives_raw.get(d_str, [])
            ))
            pct_bad = (neg_on_bad / max(all_negative_days, 1)) * 100
            pct_good = (neg_on_good / max(all_positive_days, 1)) * 100

            total_occurrences = neg_on_bad + neg_on_good
            importance = total_occurrences * float(neg_pts)

            results.append(Discovery(
                kind="failure",
                title=f"{neg_name} Concentrates On Bad Days",
                summary=(
                    f"{neg_name} appears {ratio:.1f}× more often on bad days. "
                    f"Present on {pct_bad:.0f}% of negative days vs {pct_good:.0f}% of positive days."
                ),
                evidence=(
                    f"Bottom quartile: {bottom_rate:.2f}x/day  |  "
                    f"Top quartile: {top_rate:.2f}x/day  |  "
                    f"Ratio: {ratio:.1f}×"
                ),
                period=f"Last {lookback}d",
                confidence=round(conf, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                score=_score(conf, impact, novelty),
                subject=neg_name,
                importance=round(importance, 2),
            ))

        results.sort(key=lambda d: d.score, reverse=True)
        return results
