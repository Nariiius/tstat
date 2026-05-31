"""Rate-based color grouping for project rows in table views."""


class RateColors:
    """Maps rate values (e.g. 3.0, 1.5) to hex color strings.

    Loaded from the optional ``"rate_colors"`` section of toggl_config.json.
    """

    def __init__(self, rate_colors_config: dict | None = None):
        self._map: dict[float, str] = {}
        if rate_colors_config:
            for key, value in rate_colors_config.items():
                try:
                    self._map[float(key)] = str(value)
                except (ValueError, TypeError):
                    pass

    def update(self, other: "RateColors") -> None:
        """Replace contents in-place with a copy of another RateColors."""
        self._map = dict(other._map)

    def get_color(self, rate: float | None) -> str | None:
        """Return the hex color for a rate value, or None if unmapped."""
        if rate is None:
            return None
        return self._map.get(rate)

    def __len__(self):
        return len(self._map)

    def __repr__(self):
        return f"RateColors({len(self._map)} mapping{'s' if len(self._map) != 1 else ''})"
