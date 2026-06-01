"""AutoWidthDataTable — DataTable subclass that stretches/compresses columns to fill available width.

The first column (typically a name/label column) acts as the "flex" column:
  - When there is surplus space, it expands to absorb it.
  - When space is tight, it shrinks so the other columns can still show fully.

All trailing columns always keep their content-sized (auto) widths.
"""

from __future__ import annotations

from textual.geometry import Size
from textual.widgets import DataTable

# Minimum visible characters for the flex column before it gives up and
# just lets the table scroll horizontally.
_FLEX_MIN_WIDTH = 4


class AutoWidthDataTable(DataTable):
    """DataTable that automatically fits columns to the widget's available width.

    Behaviour:
    - **Surplus space**: the first column (flex column) expands to fill the gap.
    - **Tight space**: trailing columns keep their natural widths; the flex
      column is compressed down to ``_FLEX_MIN_WIDTH`` before the table is
      allowed to overflow.
    - **On resize**: column widths are redistributed immediately.
    """

    def _update_dimensions(self, new_rows):
        """Override to distribute space after Textual computes content widths."""
        super()._update_dimensions(new_rows)
        self._distribute_column_widths()

    def _distribute_column_widths(self) -> None:
        """Fit columns into the available horizontal space."""
        ordered_cols = self.ordered_columns
        if not ordered_cols:
            return

        # self.size is already the inner content area (border/padding excluded)
        available = self.size.width
        if available <= 0:
            return

        # Subtract row-label column if present
        available -= self._row_label_column_width

        padding = self.cell_padding  # cells added on each side of every column

        flex_col = ordered_cols[0]
        other_cols = ordered_cols[1:]

        # Width each trailing column naturally wants (content + both paddings)
        other_natural = [col.content_width + 2 * padding for col in other_cols]
        other_total = sum(other_natural)

        # Space left for the flex column after trailing columns take their share
        flex_space = available - other_total  # may be negative when very tight

        if flex_space >= flex_col.content_width + 2 * padding:
            # ── Surplus mode: flex column expands to fill remaining space ──
            flex_col.auto_width = False
            flex_col.width = flex_space - 2 * padding
        elif flex_space >= _FLEX_MIN_WIDTH + 2 * padding:
            # ── Compression mode: flex column shrinks, others stay full ──
            flex_col.auto_width = False
            flex_col.width = flex_space - 2 * padding
        elif flex_space >= _FLEX_MIN_WIDTH:
            # ── Very tight: flex column eats into its own padding budget ──
            flex_col.auto_width = False
            flex_col.width = max(_FLEX_MIN_WIDTH, flex_space)
        else:
            # ── Overflow: table is too narrow to compress further; let it scroll ──
            for col in ordered_cols:
                col.auto_width = True
            return

        # Trailing columns keep their content-sized auto widths
        for col in other_cols:
            col.auto_width = True

        # Recompute virtual size to match the new width distribution
        data_cells_width = sum(
            col.get_render_width(self) for col in self.columns.values()
        )
        total_width = data_cells_width + self._row_label_column_width
        header_height = self.header_height if self.show_header else 0
        self.virtual_size = Size(
            total_width,
            self._total_row_height + header_height,
        )

        # Invalidate render caches so updated widths are actually drawn
        self._clear_caches()

    def on_resize(self, event) -> None:
        """Re-distribute column widths whenever the widget is resized."""
        self._distribute_column_widths()
