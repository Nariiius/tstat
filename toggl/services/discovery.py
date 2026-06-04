"""
Discovery Engine — answers decision-relevant questions only.

A discovery is valid ONLY if it helps answer:
  - What is hurting me?
  - What is helping me?
  - What changed my trajectory?
  - What am I neglecting?

If it cannot answer one of those questions, it should not be shown.

Analyzers: failure_mode, positive_driver, neglect, trajectory_change, best_period_gap.
Ranking: confidence*0.3 + impact*0.3 + actionability*0.4
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


@dataclass
class Discovery:
    kind: str  # failure_mode | positive_driver | neglect | trajectory_change | best_period_gap
    title: str
    summary: str
    evidence: str
    period: str
    confidence: float
    impact: float
    novelty: float
    actionability: float
    score: float
    subject: str
    importance: float = 0.0


def _discovery_score(
    confidence: float, impact: float, actionability: float,
) -> float:
    return round(confidence * 0.3 + impact * 0.3 + actionability * 0.4, 3)


class DiscoveryEngine:

    MAX_DISCOVERIES = 4       # hard cap
    MAX_PER_KIND    = 1       # one per type
    MIN_CONFIDENCE  = 0.70
    PVALUE_THRESHOLD = 0.10   # relaxed for small datasets

    def __init__(
        self,
        cache: DataCache,
        metrics: MetricsService,
        config: Config,
    ) -> None:
        self._cache = cache
        self._metrics = metrics
        self._config = config
        self._lookback = {
            "drift": 60,
            "failure": 90,
            "best_period": 90,
            **config.discovery_lookback,
        }
        self._discovery_ignore = config.discovery_ignore

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _pval_confidence(p_value: float) -> float:
        return round(max(0.70, min(0.99, 1.0 - p_value)), 2)

    def _get_data_dates_within(
        self, today: date, lookback_days: int
    ) -> list[date]:
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

    def _compute_importance(
        self, name: str, total_hours: float
    ) -> float:
        rate = self._config.points.get(name, 0)
        return total_hours * float(rate) if rate else 0.0

    def _is_project_ignored(self, name: str) -> bool:
        return name in self._discovery_ignore or self._config.points.get(name, 0) <= 0

    def _is_decision_relevant(self, d: Discovery) -> bool:
        """Gate: only discoveries that answer a decision question."""
        if d.kind == "failure_mode" or d.kind == "positive_driver":
            return d.confidence >= 0.70
        if d.kind == "neglect":
            return d.importance > 0
        if d.kind == "trajectory_change":
            return d.importance > 0 and d.impact >= 0.30
        if d.kind == "best_period_gap":
            return d.impact >= 0.30
        return True

    # ── Main pipeline ───────────────────────────────────────────────────

    def compute(self) -> list[Discovery]:
        logger.debug("DiscoveryEngine.compute starting")
        today = date.today()

        candidates: list[Discovery] = []
        candidates.extend(self._analyze_failure_modes(today))
        candidates.extend(self._analyze_positive_drivers(today))
        candidates.extend(self._analyze_neglect(today))
        candidates.extend(self._analyze_trajectory_change(today))
        candidates.extend(self._analyze_best_period(today))

        # Discovery ignore filter
        candidates = [
            c for c in candidates
            if c.subject not in self._discovery_ignore
        ]

        # Confidence filter
        candidates = [
            c for c in candidates if c.confidence >= self.MIN_CONFIDENCE
        ]

        # Decision relevance filter
        candidates = [c for c in candidates if self._is_decision_relevant(c)]

        # Dedup by subject — keep highest actionability per subject
        by_subject: dict[str, Discovery] = {}
        for d in candidates:
            key = d.subject
            if key not in by_subject or d.actionability > by_subject[key].actionability:
                by_subject[key] = d

        ranked = sorted(
            by_subject.values(), key=lambda d: d.score, reverse=True
        )

        # One per kind
        kinds_seen: set[str] = set()
        final: list[Discovery] = []
        for d in ranked:
            if d.kind in kinds_seen:
                continue
            kinds_seen.add(d.kind)
            final.append(d)
            if len(final) >= self.MAX_DISCOVERIES:
                break

        return final

    # ── Analyzer 1: Failure Modes ──────────────────────────────────────

    def _analyze_failure_modes(self, today: date) -> list[Discovery]:
        lookback = self._lookback["failure"]
        cutoff = today - timedelta(days=lookback)

        day_nets: list[tuple[str, float]] = []
        for d_str in set(
            list(self._cache.daily_data.keys())
            + list(self._cache.negatives_raw.keys())
            + list(self._cache.positives_raw.keys())
        ):
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

        neg_day_counts: dict[str, dict[str, int]] = {}
        for d_str in set(bottom_q + top_q):
            for e in self._cache.negatives_raw.get(d_str, []):
                neg_day_counts.setdefault(e["name"], {}).setdefault(d_str, 0)
                neg_day_counts[e["name"]][d_str] += 1

        neg_on_bad_total: dict[str, int] = {}
        neg_on_good_total: dict[str, int] = {}
        all_negative_days = sum(1 for _, net in day_nets if net < 0)
        all_positive_days = sum(1 for _, net in day_nets if net >= 0)
        for d_str, net in day_nets:
            for e in self._cache.negatives_raw.get(d_str, []):
                name = e["name"]
                if net < 0:
                    neg_on_bad_total[name] = neg_on_bad_total.get(name, 0) + 1
                else:
                    neg_on_good_total[name] = neg_on_good_total.get(name, 0) + 1

        results: list[Discovery] = []

        for neg_name in neg_day_counts:
            bad_counts = [neg_day_counts[neg_name].get(d, 0) for d in bottom_q]
            good_counts = [neg_day_counts[neg_name].get(d, 0) for d in top_q]
            total_q_count = sum(bad_counts) + sum(good_counts)
            if total_q_count < 5:
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
            confidence = self._pval_confidence(p_value)
            neg_pts = self._config.negatives.get(neg_name, 5)
            impact = min(0.45 + (neg_pts / 20.0) * 0.40 + min(bottom_rate, 0.3), 0.92)
            novelty = min(0.4 + ratio / 10.0, 0.85)
            actionability = 1.0  # failure modes are always actionable
            importance = (neg_on_bad_total.get(neg_name, 0) + neg_on_good_total.get(neg_name, 0)) * float(neg_pts)
            pct_bad = (neg_on_bad_total.get(neg_name, 0) / max(all_negative_days, 1)) * 100
            pct_good = (neg_on_good_total.get(neg_name, 0) / max(all_positive_days, 1)) * 100

            results.append(Discovery(
                kind="failure_mode",
                title=f"{neg_name} Concentrates On Bad Days",
                summary=(
                    f"{neg_name} appears {ratio:.1f}× more often on your "
                    f"worst days than your best. Present on {pct_bad:.0f}% of "
                    f"negative days vs {pct_good:.0f}% of positive days."
                ),
                evidence=(
                    f"Ratio: {ratio:.1f}×  |  p={p_value:.3f}  |  "
                    f"{total_q_count} occurrences"
                ),
                period=f"Last {lookback}d",
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                actionability=round(actionability, 2),
                score=_discovery_score(confidence, impact, actionability),
                subject=neg_name,
                importance=round(importance, 2),
            ))

        results.sort(key=lambda d: d.score, reverse=True)
        return results

    # ── Analyzer 2: Positive Drivers ────────────────────────────────────
    # Mirror of Failure Mode: habits that appear much more often on good days

    def _analyze_positive_drivers(self, today: date) -> list[Discovery]:
        lookback = self._lookback["failure"]
        cutoff = today - timedelta(days=lookback)

        day_nets: list[tuple[str, float]] = []
        for d_str in set(
            list(self._cache.daily_data.keys())
            + list(self._cache.positives_raw.keys())
        ):
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d < cutoff or d > today:
                continue
            dm = self._metrics.get_day_metrics(d_str)
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

        pos_day_counts: dict[str, dict[str, int]] = {}
        for d_str in set(bottom_q + top_q):
            for e in self._cache.positives_raw.get(d_str, []):
                pos_day_counts.setdefault(e["name"], {}).setdefault(d_str, 0)
                pos_day_counts[e["name"]][d_str] += 1

        results: list[Discovery] = []

        for pos_name in self._config.positives:
            if pos_name not in pos_day_counts:
                continue
            top_counts = [pos_day_counts[pos_name].get(d, 0) for d in top_q]
            bottom_counts = [pos_day_counts[pos_name].get(d, 0) for d in bottom_q]
            total_count = sum(top_counts) + sum(bottom_counts)
            if total_count < 5:
                continue

            top_rate = sum(top_counts) / len(top_q) if top_q else 0.0
            bottom_rate = sum(bottom_counts) / len(bottom_q) if bottom_q else 0.0
            if top_rate <= bottom_rate * 2.0 or top_rate < 0.3:
                continue

            ratio = top_rate / bottom_rate if bottom_rate > 0 else 5.0
            confidence = min(0.75 + (total_count - 5) / 25 * 0.20, 0.95)
            pts = self._config.positives.get(pos_name, 3)
            impact = min(0.45 + (pts / 8.0) * 0.40 + min(top_rate, 0.3), 0.92)
            novelty = min(0.4 + ratio / 10.0, 0.85)
            actionability = 0.80  # "keep doing this" is actionable but less urgent
            importance = total_count * float(pts)

            results.append(Discovery(
                kind="positive_driver",
                title=f"{pos_name} Correlates With Good Days",
                summary=(
                    f"{pos_name} appears on {top_rate*100:.0f}% of your best "
                    f"days vs {bottom_rate*100:.0f}% of your worst days "
                    f"({ratio:.1f}× more often on good days)."
                ),
                evidence=(
                    f"Top quartile: {top_rate:.2f}/d  |  "
                    f"Bottom: {bottom_rate:.2f}/d  |  Ratio: {ratio:.1f}×"
                ),
                period=f"Last {lookback}d",
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                actionability=round(actionability, 2),
                score=_discovery_score(confidence, impact, actionability),
                subject=pos_name,
                importance=round(importance, 2),
            ))

        results.sort(key=lambda d: d.score, reverse=True)
        return results

    # ── Analyzer 3: Neglect ─────────────────────────────────────────────
    # Activities that were important but have disappeared

    def _analyze_neglect(self, today: date) -> list[Discovery]:
        results: list[Discovery] = []
        all_dates = self._get_all_data_dates(today)
        if len(all_dates) < 14:
            return results

        # Compute per-project importance and days since last activity
        proj_meta: dict[str, tuple[float, float, int]] = {}  # total_h, point_rate, days_since
        for d_str, projs in self._cache.daily_data.items():
            d = date.fromisoformat(d_str)
            for proj, hrs in projs.items():
                if d > today:
                    continue
                total_h, rate, _ = proj_meta.get(proj, (0.0, 0.0, 0))
                proj_meta[proj] = (total_h + hrs, self._config.points.get(proj, 0), 0)

        for proj, (total_h, rate, _) in proj_meta.items():
            if rate <= 0 or self._is_project_ignored(proj):
                continue
            importance = total_h * rate
            # Find days since last activity
            days_since = 999
            for d in range(0, 365):
                d_str = (today - timedelta(days=d)).strftime("%Y-%m-%d")
                if d_str in self._cache.daily_data and self._cache.daily_data[d_str].get(proj, 0) > 0:
                    days_since = d
                    break

            if days_since < 21:
                continue

            # Need median-ish importance to trigger (otherwise every tiny project fires)
            if importance < 10.0:
                continue

            historical_rate = total_h / max((today - all_dates[0]).days, 1)
            confidence = min(0.75 + (days_since - 21) / 60 * 0.20, 0.95)
            impact = min(0.55 + (rate / 3.0) * 0.35, 0.90)
            novelty = min(days_since / 60, 0.85)
            actionability = 0.90  # "resume doing this" is highly actionable

            results.append(Discovery(
                kind="neglect",
                title=f"{proj} Has Been Neglected",
                summary=(
                    f"{proj} previously averaged {historical_rate:.1f}h/day. "
                    f"No activity for {days_since} days."
                ),
                evidence=(
                    f"Historical: {historical_rate:.2f}h/d  |  "
                    f"Days since last: {days_since}"
                ),
                period="All available history",
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                actionability=round(actionability, 2),
                score=_discovery_score(confidence, impact, actionability),
                subject=proj,
                importance=round(importance, 2),
            ))

        results.sort(key=lambda d: d.score, reverse=True)
        return results

    # ── Analyzer 4: Trajectory Change ───────────────────────────────────
    # Replaces generic growth: explain WHAT changed

    def _analyze_trajectory_change(self, today: date) -> list[Discovery]:
        lookback = self._lookback["drift"]
        all_dates = self._get_data_dates_within(today, lookback)
        if len(all_dates) < 21:
            return []

        results: list[Discovery] = []
        full_idx = pd.date_range(all_dates[0], today)
        recent_14 = today - timedelta(days=13)

        # Track which projects gained and lost time
        for proj, point_rate in self._config.points.items():
            if point_rate <= 0 or self._is_project_ignored(proj):
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
            if reg.pvalue >= self.PVALUE_THRESHOLD:
                continue

            before_mask = full_idx < pd.Timestamp(recent_14)
            after_mask = full_idx >= pd.Timestamp(recent_14)
            before_avg = np.mean([ys[i] for i in range(len(ys)) if before_mask[i]]) if before_mask.any() else 0
            after_avg = np.mean([ys[i] for i in range(len(ys)) if after_mask[i]]) if after_mask.any() else 0

            if before_avg < 0.05 and after_avg < 0.05:
                continue

            change_pct = round(((after_avg - before_avg) / max(before_avg, 0.01)) * 100)
            if abs(change_pct) < 30:
                continue

            direction = "up" if change_pct > 0 else "down"
            confidence = self._pval_confidence(reg.pvalue)
            impact = min(0.45 + (point_rate / 3.0) * 0.4 + min(after_avg / 2.0, 0.15), 1.0)
            novelty = min(abs(change_pct) / 400, 0.95)
            actionability = 0.60 if abs(change_pct) > 50 else 0.40
            importance = self._compute_importance(proj, total_h)

            # For downward trends, try to find what's displacing it
            what_displaced = ""
            if direction == "down" and before_avg > 0.2:
                gainers = []
                for other_proj, other_rate in self._config.points.items():
                    if other_rate <= 0 or other_proj == proj:
                        continue
                    other_ys = [self._cache.daily_data.get(d.strftime("%Y-%m-%d"), {}).get(other_proj, 0.0) for d in full_idx]
                    other_before = np.mean([other_ys[i] for i in range(len(other_ys)) if before_mask[i]]) if before_mask.any() else 0
                    other_after = np.mean([other_ys[i] for i in range(len(other_ys)) if after_mask[i]]) if after_mask.any() else 0
                    other_delta = other_after - other_before
                    if other_delta > 0.2:
                        gainers.append((other_proj, other_delta))
                gainers.sort(key=lambda x: -x[1])
                if gainers:
                    what_displaced = f" Displaced by: {', '.join(p for p, _ in gainers[:2])}."

            summary = (
                f"{proj} is trending {direction} over {len(ys)}d "
                f"({before_avg:.1f}h/d → {after_avg:.1f}h/d, {change_pct:+d}%)."
            )
            if what_displaced:
                summary += what_displaced

            results.append(Discovery(
                kind="trajectory_change",
                title=f"{proj} Trajectory Changed",
                summary=summary,
                evidence=(
                    f"{before_avg:.1f}h/d → {after_avg:.1f}h/d "
                    f"({change_pct:+d}%)  |  p={reg.pvalue:.3f}"
                ),
                period=f"Last {lookback}d",
                confidence=round(confidence, 2),
                impact=round(impact, 2),
                novelty=round(novelty, 2),
                actionability=round(actionability, 2),
                score=_discovery_score(confidence, impact, actionability),
                subject=proj,
                importance=round(importance, 2),
            ))

        results.sort(key=lambda d: d.score, reverse=True)
        return results

    # ── Analyzer 5: Best Period Gap ─────────────────────────────────────
    # Explain WHAT CHANGED since the best 28-day window

    def _analyze_best_period(self, today: date) -> list[Discovery]:
        lookback = self._lookback["best_period"]
        all_dates = self._get_data_dates_within(today, lookback)
        total_days = (today - all_dates[0]).days if all_dates else 0
        if total_days < 42:
            return []

        WINDOW = 28

        all_nets: dict[date, float] = {}
        for d_str in set(
            list(self._cache.daily_data.keys())
            + list(self._cache.positives_raw.keys())
            + list(self._cache.negatives_raw.keys())
        ):
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            cutoff = today - timedelta(days=lookback)
            if d < cutoff or d > today:
                continue
            all_nets[d] = self._metrics.get_day_metrics(d_str).get("net", 0.0)

        idx = pd.date_range(all_dates[0], today)
        series = pd.Series(
            [all_nets.get(d.date(), 0.0) for d in idx], index=idx
        )

        rolling_28 = series.rolling(WINDOW, min_periods=WINDOW // 2).mean().dropna()
        if rolling_28.empty:
            return []

        cutoff_dt = today - timedelta(days=WINDOW)
        historical = rolling_28[rolling_28.index <= pd.Timestamp(cutoff_dt)]
        if historical.empty:
            return []

        best_avg = historical.max()
        best_end = historical.idxmax()
        best_start = best_end - pd.Timedelta(days=WINDOW - 1)
        curr_avg = rolling_28.iloc[-1]
        gap = best_avg - curr_avg
        if gap < 5.0:
            return []

        best_label = (
            f"{best_start.strftime('%b %d')}–{best_end.strftime('%b %d, %Y')}"
        )

        # Find top activity differences
        best_start_d = best_start.date()
        best_end_d = best_end.date()

        diff_scores: list[tuple[str, float, float, float, float]] = []  # (name, best_rate, curr_rate, drop_pct, importance)

        for proj, point_rate in self._config.points.items():
            if point_rate <= 0:
                continue
            # Hours in best period
            best_hours = 0.0
            best_days_total = 0
            sd = best_start_d
            while sd <= best_end_d:
                ds = sd.strftime("%Y-%m-%d")
                best_hours += self._cache.daily_data.get(ds, {}).get(proj, 0.0)
                best_days_total += 1
                sd += timedelta(days=1)

            # Hours in current 28d
            curr_hours = 0.0
            curr_days = 0
            c_d = cutoff_dt
            while c_d <= today:
                ds = c_d.strftime("%Y-%m-%d")
                curr_hours += self._cache.daily_data.get(ds, {}).get(proj, 0.0)
                curr_days += 1
                c_d += timedelta(days=1)

            best_rate = best_hours / max(best_days_total, 1)
            curr_rate = curr_hours / max(curr_days, 1)
            if best_rate < 0.05 and curr_rate < 0.05:
                continue

            delta = best_rate - curr_rate
            if abs(delta) < 0.05:
                continue

            drop_pct = (abs(delta) / max(best_rate, 0.01)) * 100
            importance = (best_hours + curr_hours) * float(point_rate)
            diff_scores.append((proj, best_rate, curr_rate, drop_pct, importance))

        diff_scores.sort(key=lambda x: -(x[3] * x[4]))
        top_diffs = diff_scores[:3]

        confidence = min(0.72 + total_days / 365 * 0.20, 0.92)
        impact = min(0.55 + gap / 50, 0.95)
        novelty = 0.75
        actionability = 0.60  # moderately actionable — tells you what's different
        importance = gap * 10

        summary = (
            f"Best 28-day period: {best_label} ({best_avg:+.0f}/day). "
            f"Current: {curr_avg:+.0f}/day ({gap:.0f}/day gap)."
        )
        if top_diffs:
            diff_lines = "\n    ".join(
                f"- {name}: {best_r:.1f}h/d → {curr_r:.1f}h/d" 
                for name, best_r, curr_r, _, _ in top_diffs
            )
            summary += f"\n    {diff_lines}"

        return [
            Discovery(
                kind="best_period_gap",
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
                actionability=round(actionability, 2),
                score=_discovery_score(confidence, impact, actionability),
                subject="__best_period__",
                importance=round(importance, 2),
            )
        ]
