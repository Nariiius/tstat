"""Insights bundle — playbook + coach with disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from toggl.cache import DataCache
from toggl.category import CategoryRegistry
from toggl.config import Config
from toggl.const import (
    CSV_FILE,
    DAILY_CSV_FILE,
    HISTORY_FILE,
    NEGATIVES_CSV_FILE,
    PLAYBOOK_CACHE_FILE,
    POSITIVES_CSV_FILE,
    PROJECTS_FILE,
)
from toggl.services.coach import CoachReport, CoachService, CoachFinding
from toggl.services.metrics import MetricsService
from toggl.services.playbook import Playbook, PlaybookService, PlaybookStep

logger = logging.getLogger("TStat")


@dataclass
class InsightsBundle:
    playbook: Playbook = field(default_factory=lambda: Playbook(goal="", headline=""))
    coach: CoachReport = field(default_factory=CoachReport)
    generated_at: str = ""


def _stable_config_hash(
    points: dict[str, int | float],
    positives: dict[str, int | float],
    negatives: dict[str, int | float],
    daily_target: float,
    recovery_ignore: list[str],
) -> str:
    payload = json.dumps(
        {
            "points": sorted(points.items()),
            "positives": sorted(positives.items()),
            "negatives": sorted(negatives.items()),
            "daily_target": daily_target,
            "recovery_ignore": sorted(recovery_ignore),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _file_fingerprint(paths: list[str]) -> dict[str, tuple[float, int]]:
    out: dict[str, tuple[float, int]] = {}
    for path in paths:
        try:
            st = os.stat(path)
            out[path] = (st.st_mtime, st.st_size)
        except OSError:
            out[path] = (0.0, 0)
    return out


class InsightsBundleService:
    def __init__(
        self,
        metrics: MetricsService,
        cache: DataCache,
        config: Config,
        get_daily_target: Callable[[], float],
        cache_path: str | None = None,
    ) -> None:
        self._metrics = metrics
        self._cache = cache
        self._config = config
        self._get_daily_target = get_daily_target
        self._cache_path = cache_path or PLAYBOOK_CACHE_FILE
        self._playbook_svc = PlaybookService(
            metrics,
            cache,
            dict(config.points),
            dict(config.positives),
            config.activity_rules,
            get_daily_target,
        )
        self._coach_svc = CoachService(
            metrics,
            cache,
            dict(config.points),
            dict(config.positives),
            config.category_registry,
            config.activity_rules,
        )

    def compute_fingerprint(self) -> dict[str, Any]:
        return {
            "config_hash": _stable_config_hash(
                self._config.points,
                self._config.positives,
                self._config.negatives,
                float(self._config.daily_target),
                self._config.recovery_ignore,
            ),
            "files": _file_fingerprint([
                CSV_FILE,
                DAILY_CSV_FILE,
                NEGATIVES_CSV_FILE,
                POSITIVES_CSV_FILE,
                HISTORY_FILE,
                PROJECTS_FILE,
            ]),
        }

    def compute(
        self,
        on_progress: Callable[[str], None] | None = None,
    ) -> InsightsBundle:
        if on_progress:
            on_progress("playbook")
        playbook = self._playbook_svc.compute()
        if on_progress:
            on_progress("coach")
        coach = self._coach_svc.compute()
        return InsightsBundle(
            playbook=playbook,
            coach=coach,
            generated_at=datetime.now().isoformat(timespec="seconds"),
        )

    def try_load_cache(self) -> InsightsBundle | None:
        if not os.path.exists(self._cache_path):
            return None
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        if not _fingerprints_match(data.get("fingerprint"), self.compute_fingerprint()):
            return None
        return _bundle_from_dict(data)

    def save_cache(self, bundle: InsightsBundle) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            payload = {
                "fingerprint": self.compute_fingerprint(),
                "generated_at": bundle.generated_at,
                "playbook": _playbook_to_dict(bundle.playbook),
                "coach": _coach_to_dict(bundle.coach),
            }
            tmp = self._cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self._cache_path)
        except Exception:
            logger.exception("Failed to save insights bundle cache")


def _playbook_to_dict(pb: Playbook) -> dict[str, Any]:
    return {
        "goal": pb.goal,
        "headline": pb.headline,
        "steps": [asdict(s) for s in pb.steps],
        "done_today": pb.done_today,
        "gap_note": pb.gap_note,
        "lookback": pb.lookback,
        "focus_line": pb.focus_line,
        "context": pb.context,
        "generated_at": pb.generated_at,
    }


def _coach_to_dict(coach: CoachReport) -> dict[str, Any]:
    return {
        "findings": [asdict(f) for f in coach.findings],
    }


def _fingerprints_match(
    stored: dict[str, Any] | None, current: dict[str, Any] | None
) -> bool:
    if not stored or not current:
        return False
    if stored.get("config_hash") != current.get("config_hash"):
        return False
    stored_files = stored.get("files", {})
    current_files = current.get("files", {})
    for path, cur in current_files.items():
        st = stored_files.get(path)
        if st is None:
            return False
        if tuple(st) != tuple(cur):
            return False
    return True


def _bundle_from_dict(data: dict[str, Any]) -> InsightsBundle:
    pb_raw = data.get("playbook", {})
    steps = [PlaybookStep(**s) for s in pb_raw.get("steps", [])]
    playbook = Playbook(
        goal=pb_raw.get("goal", ""),
        headline=pb_raw.get("headline", ""),
        steps=steps,
        done_today=pb_raw.get("done_today", []),
        gap_note=pb_raw.get("gap_note", ""),
        lookback=pb_raw.get("lookback", []),
        focus_line=pb_raw.get("focus_line", ""),
        context=pb_raw.get("context", {}),
        generated_at=pb_raw.get("generated_at", ""),
    )
    findings = [
        CoachFinding(**f) for f in data.get("coach", {}).get("findings", [])
    ]
    return InsightsBundle(
        playbook=playbook,
        coach=CoachReport(findings=findings),
        generated_at=data.get("generated_at", ""),
    )
