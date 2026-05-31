"""PeriodController — pure date-range navigation and zoom state.

No UI dependency. Operates on dates only. Used by the Command tab to
determine visible range, period labels, and calendar interactions.
"""

from datetime import date, timedelta


class PeriodMode:
    """Namespace enum for period modes."""
    DAY = "day"
    WEEK = "week"
    MONTH = "month"

    _LABELS = {DAY: "Day", WEEK: "Week", MONTH: "Month"}

    @staticmethod
    def values():
        return [PeriodMode.DAY, PeriodMode.WEEK, PeriodMode.MONTH]

    @staticmethod
    def label(mode: str) -> str:
        return PeriodMode._LABELS.get(mode, mode.capitalize())


def _get_sunday(d: date) -> date:
    """Return the Sunday on or before *d* (matching TStat's week system)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


class PeriodController:
    """Pure date-range controller for the Command tab graph.

    Owns:
      - mode (Day / Week / Month) — determines navigation step size
      - scale_index — selects from the current mode's scale list
      - offset — integer; 0 = current period, negative = past

    The visible range is always right-aligned: the anchor date (rightmost
    date of the visible window) is determined by offset from today, and
    the scale extends leftward.
    """

    DAY_SCALES   = [7, 30, 90, 365]
    WEEK_SCALES  = [4, 13, 26, 52]
    MONTH_SCALES = [3, 6, 12]

    _SCALE_LABELS = {
        "day":   {7: "7d",  30: "30d",  90: "90d",  365: "365d"},
        "week":  {4: "4w",  13: "13w",  26: "26w",   52: "52w"},
        "month": {3: "3m",  6: "6m",   12: "12m"},
    }

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
        if value not in (PeriodMode.DAY, PeriodMode.WEEK, PeriodMode.MONTH):
            raise ValueError(f"Invalid mode: {value}")
        self._mode = value
        self._scale_index = 0
        self._offset = 0

    @property
    def scale(self) -> int:
        return self._scales()[self._scale_index]

    @property
    def scale_label(self) -> str:
        return self._SCALE_LABELS.get(self._mode, {}).get(self.scale, str(self.scale))

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

    @property
    def scales(self) -> list[int]:
        return self._scales()

    def _scales(self) -> list[int]:
        if self._mode == PeriodMode.DAY:
            return self.DAY_SCALES
        elif self._mode == PeriodMode.WEEK:
            return self.WEEK_SCALES
        else:
            return self.MONTH_SCALES

    # ── Navigation ──────────────────────────────────────────────────

    def previous(self):
        self._offset -= 1

    def next(self):
        if self._offset < 0:
            self._offset += 1

    def zoom_in(self):
        if self._scale_index > 0:
            self._scale_index -= 1

    def zoom_out(self):
        if self._scale_index < self.scale_count - 1:
            self._scale_index += 1

    def set_scale(self, scale_value: int):
        """Set scale directly by value (e.g., 7, 30, 4, 13)."""
        scales = self._scales()
        try:
            self._scale_index = scales.index(scale_value)
        except ValueError:
            pass  # ignore invalid scales

    # ── Range computation ───────────────────────────────────────────

    def _add_months(self, d: date, months: int) -> date:
        """Add *months* to a date, clamping to month-end if needed."""
        total = d.month - 1 + months
        year = d.year + total // 12
        month = (total % 12) + 1
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day if month < 12 else 31
        day = min(d.day, last_day)
        return date(year, month, day)

    def get_visible_range(self) -> tuple[date, date]:
        """Return (start_date, end_date) for the graph's visible range."""
        today = date.today()

        if self._mode == PeriodMode.DAY:
            anchor = today + timedelta(days=self._offset)
            start = anchor - timedelta(days=self.scale - 1)
            return start, anchor

        elif self._mode == PeriodMode.WEEK:
            current_sunday = _get_sunday(today)
            anchor_sunday = current_sunday + timedelta(weeks=self._offset)
            start = anchor_sunday - timedelta(weeks=self.scale - 1)
            end = anchor_sunday + timedelta(days=6)
            return start, end

        else:  # MONTH
            # Anchor is the last day of the offset month
            anchor_month = self._add_months(today, self._offset)
            # End of that month
            next_month = self._add_months(anchor_month.replace(day=1), 1)
            anchor_end = next_month - timedelta(days=1)
            # Start = first day of (anchor_month - (scale-1) months)
            start_month = self._add_months(anchor_month.replace(day=1), -(self.scale - 1))
            start = start_month.replace(day=1)
            return start, anchor_end

    def get_anchor_date(self) -> date:
        """Return the rightmost (anchor) date of the visible range."""
        today = date.today()
        if self._mode == PeriodMode.DAY:
            return today + timedelta(days=self._offset)
        elif self._mode == PeriodMode.WEEK:
            current_sunday = _get_sunday(today)
            return current_sunday + timedelta(days=6, weeks=self._offset)
        else:  # MONTH
            anchor_month = self._add_months(today, self._offset)
            next_month = self._add_months(anchor_month.replace(day=1), 1)
            return next_month - timedelta(days=1)

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
            # Include scale context for larger scales
            return anchor.strftime("%b %d, %Y")

        elif self._mode == PeriodMode.WEEK:
            if self._offset == 0:
                return "This Week"
            if self._offset == -1:
                return "Last Week"
            anchor_sunday = _get_sunday(today) + timedelta(weeks=self._offset)
            return anchor_sunday.strftime("W%W, %Y")

        else:  # MONTH
            if self._offset == 0:
                return "This Month"
            if self._offset == -1:
                return "Last Month"
            anchor = self._add_months(today, self._offset)
            return anchor.strftime("%B %Y")

    # ── Calendar-set methods ────────────────────────────────────────

    def set_from_day(self, target_date: date):
        today = date.today()
        self._mode = PeriodMode.DAY
        self._scale_index = 0
        self._offset = (target_date - today).days

    def set_from_week(self, target_date: date):
        today = date.today()
        current_sunday = _get_sunday(today)
        target_sunday = _get_sunday(target_date)
        delta_days = (target_sunday - current_sunday).days
        self._mode = PeriodMode.WEEK
        self._scale_index = 0
        self._offset = delta_days // 7

    def set_from_month(self, target_date: date):
        today = date.today()
        self._mode = PeriodMode.MONTH
        self._scale_index = 0
        # Offset in months from current month
        offset = (target_date.year - today.year) * 12 + (target_date.month - today.month)
        self._offset = offset
