"""Insights bundle — playbook + discoveries with disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from toggl.cache import DataCache
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
from toggl.services.discovery import Discovery, DiscoveryEngine
from toggl.services.metrics import MetricsService
from toggl.services.playbook import Playbook, PlaybookService, PlaybookStep

logger = logging.getLogger("TStat")


@dataclass
class InsightsBundle:
    playbook: Playbook = field(default_factory=lambda: Playbook(goal="", headline=""))
    positives: dict[str, int | float] = field(default_factory=dict)
    points: dict[str, int | float] = field(default_factory=dict)
    discoveries: list[Discovery] = field(default_factory=list)
    recovery_ignore: list[str] = field(default_factory=list)
    avoid_names: frozenset[str] = field(default_factory=frozenset)
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
            recovery_ignore=config.recovery_ignore,
            controllability_map=config.controllability,
            availability_overrides=config.availability_overrides,
            low_control_reasons=config.low_control_reasons,
            default_hours=config.default_hours,
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

        # Run discovery engine
        discoveries: list[Discovery] = []
        try:
            engine = DiscoveryEngine(
                cache=self._cache,
                metrics=self._metrics,
                config=self._config,
            )
            discoveries = engine.compute()
        except Exception:
            logger.exception("DiscoveryEngine failed")

        # Precompute avoid names for rendering filters
        avoid_names = frozenset(
            n for n in list(self._config.positives) + list(self._config.points)
            if not self._config.activity_rules.should_suggest(n)
        )

        return InsightsBundle(
            playbook=playbook,
            positives=dict(self._config.positives),
            points=dict(self._config.points),
            discoveries=discoveries,
            recovery_ignore=list(self._config.recovery_ignore),
            avoid_names=avoid_names,
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
                "positives": dict(bundle.positives),
                "points": {k: v for k, v in bundle.points.items()},
                "discoveries": [asdict(d) for d in bundle.discoveries],
                "recovery_ignore": bundle.recovery_ignore,
                "avoid_names": list(bundle.avoid_names),
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
        "blocked_today": pb.blocked_today,
        "low_control": pb.low_control,
        "gap_note": pb.gap_note,
        "lookback": pb.lookback,
        "focus_line": pb.focus_line,
        "context": pb.context,
        "generated_at": pb.generated_at,
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
    
    # Handle blocked_today format migration (old: list[str], new: list[tuple[str,str]])
    blocked_raw = pb_raw.get("blocked_today", [])
    blocked_today = []
    for item in blocked_raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            blocked_today.append(tuple(item))
        elif isinstance(item, str):
            blocked_today.append((item, "blocked"))
    
    # Handle low_control format migration
    low_control_raw = pb_raw.get("low_control", [])
    low_control = []
    for item in low_control_raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            low_control.append(tuple(item))
        elif isinstance(item, str):
            low_control.append((item, "low control"))
    
    playbook = Playbook(
        goal=pb_raw.get("goal", ""),
        headline=pb_raw.get("headline", ""),
        steps=steps,
        done_today=pb_raw.get("done_today", []),
        blocked_today=blocked_today,
        low_control=low_control,
        gap_note=pb_raw.get("gap_note", ""),
        lookback=pb_raw.get("lookback", []),
        focus_line=pb_raw.get("focus_line", ""),
        context=pb_raw.get("context", {}),
        generated_at=pb_raw.get("generated_at", ""),
    )
    return InsightsBundle(
        playbook=playbook,
        positives=data.get("positives", {}),
        points=data.get("points", {}),
        discoveries=[Discovery(**d) for d in data.get("discoveries", [])],
        recovery_ignore=data.get("recovery_ignore", []),
        avoid_names=frozenset(data.get("avoid_names", [])),
        generated_at=data.get("generated_at", ""),
    )
