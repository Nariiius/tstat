"""PeriodController — pure date-range navigation and zoom state.

No UI dependency. Operates on dates only. Used by the Command tab to
determine visible range, period labels, and calendar interactions.
"""

from datetime import date, timedelta


class PeriodMode:
    """Namespace enum for period modes."""
    DAY = "day"
    WEEK = "week"

    @staticmethod
    def values():
        return [PeriodMode.DAY, PeriodMode.WEEK]


def _get_sunday(d: date) -> date:
    """Return the Sunday on or before *d* (matching TStat's week system)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


class PeriodController:
    """Pure date-range controller for the Command tab graph.

    Owns:
      - mode (Day or Week) — determines the navigation step size
      - scale_index — selects from the current mode's scale list
      - offset — integer; 0 = current period, negative = past

    The visible range is always right-aligned: the anchor date (rightmost
    date of the visible window) is determined by offset from today, and
    the scale extends leftward.
    """

    DAY_SCALES = [7, 30, 60, 90]
    WEEK_SCALES = [4, 13, 26, 52]

    def __init__(self):
        self._mode = PeriodMode.DAY
        self._scale_index = 0
        self._offset = 0

    # ── Properties ──────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value not in (PeriodMode.DAY, PeriodMode.WEEK):
            raise ValueError(f"Invalid mode: {value}")
        self._mode = value
        self._scale_index = 0
        self._offset = 0

    @property
    def scale(self) -> int:
        """Return the current scale value (number of mode-units visible)."""
        return self._scales()[self._scale_index]

    @property
    def scale_label(self) -> str:
        """Return '7d', '30d', '4w', etc."""
        s = self.scale
        unit = "d" if self._mode == PeriodMode.DAY else "w"
        return f"{s}{unit}"

    @property
    def scale_index(self) -> int:
        return self._scale_index

    @scale_index.setter
    def scale_index(self, value: int):
        max_i = len(self._scales()) - 1
        self._scale_index = max(0, min(value, max_i))

    @property
    def scale_count(self) -> int:
        return len(self._scales())

    def _scales(self) -> list[int]:
        return self.DAY_SCALES if self._mode == PeriodMode.DAY else self.WEEK_SCALES

    # ── Navigation ──────────────────────────────────────────────────

    def previous(self):
        """Move one period into the past."""
        self._offset -= 1

    def next(self):
        """Move one period toward the present (capped at 0 — no future)."""
        if self._offset < 0:
            self._offset += 1

    def zoom_in(self):
        """Decrease scale (fewer units visible)."""
        if self._scale_index > 0:
            self._scale_index -= 1

    def zoom_out(self):
        """Increase scale (more units visible)."""
        if self._scale_index < self.scale_count - 1:
            self._scale_index += 1

    # ── Range computation ───────────────────────────────────────────

    def get_visible_range(self) -> tuple[date, date]:
        """Return (start_date, end_date) for the graph's visible range.

        Range is right-aligned: the anchor (rightmost date) is at
        today + offset*mode_units, and the window extends scale units
        leftward.
        """
        today = date.today()

        if self._mode == PeriodMode.DAY:
            anchor = today + timedelta(days=self._offset)
            start = anchor - timedelta(days=self.scale - 1)
            return start, anchor

        else:  # WEEK
            current_sunday = _get_sunday(today)
            anchor_sunday = current_sunday + timedelta(weeks=self._offset)
            start = anchor_sunday - timedelta(weeks=self.scale - 1)
            end = anchor_sunday + timedelta(days=6)
            return start, end

    def get_anchor_date(self) -> date:
        """Return the rightmost (anchor) date of the visible range."""
        today = date.today()
        if self._mode == PeriodMode.DAY:
            return today + timedelta(days=self._offset)
        else:
            current_sunday = _get_sunday(today)
            return current_sunday + timedelta(days=6, weeks=self._offset)

    # ── Labels ──────────────────────────────────────────────────────

    def get_period_label(self) -> str:
        """Return a human-readable label for the current period."""
        today = date.today()

        if self._mode == PeriodMode.DAY:
            if self._offset == 0:
                return "Today"
            if self._offset == -1:
                return "Yesterday"
            anchor = today + timedelta(days=self._offset)
            return anchor.strftime("%b %d, %Y")
        else:
            if self._offset == 0:
                return "This Week"
            if self._offset == -1:
                return "Last Week"
            anchor_sunday = _get_sunday(today) + timedelta(weeks=self._offset)
            return anchor_sunday.strftime("W%W, %Y")

    # ── Calendar-set methods ────────────────────────────────────────

    def set_from_day(self, target_date: date):
        """Set offset so that the visible range ends on target_date (Day mode)."""
        today = date.today()
        self._mode = PeriodMode.DAY
        self._scale_index = 0
        self._offset = (target_date - today).days

    def set_from_week(self, target_date: date):
        """Set offset to the week containing target_date (Week mode)."""
        today = date.today()
        current_sunday = _get_sunday(today)
        target_sunday = _get_sunday(target_date)
        delta_days = (target_sunday - current_sunday).days
        self._mode = PeriodMode.WEEK
        self._scale_index = 0
        self._offset = delta_days // 7
