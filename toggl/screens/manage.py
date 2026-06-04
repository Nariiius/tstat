"""ManageScreen — view, delete, and change dates of logged activities."""

from __future__ import annotations

import logging
from datetime import date, datetime

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static, Tab, Tabs

from toggl.cache import DataCache
from toggl.neg import delete_activity_entry, update_activity_date
from toggl.screens.dialogs import ConfirmScreen
from toggl.widgets.date_stepper import DateStepper
from toggl.widgets.notifications import status_message

logger = logging.getLogger("TStat")


class ManageScreen(ModalScreen):
    """Large modal to manage logged positive/negative entries.

    Two-tab layout (Negatives / Positives), each with a DataTable.
    Key bindings:
        d — delete selected entry (with confirmation)
        e — edit date of selected entry (inline stepper)
        escape — close
    """

    DEFAULT_CSS = """
    ManageScreen {
        background: #0b1016 60%;
    }

    #manage-dialog {
        width: 90%;
        height: 85%;
        align: center middle;
        margin: 2 5;
    }

    #manage-box {
        width: 1fr;
        height: 1fr;
        border: round #3d4f63;
        padding: 1 2;
        background: #0b1016;
        color: #d7dde8;
    }

    #manage-box:focus,
    #manage-box:focus-within {
        border: round $accent;
        background: #0b1016;
        background-tint: transparent 0%;
    }

    #manage-tabs {
        margin-bottom: 1;
    }

    #manage-tabs > .-active {
        color: #63f3ff;
        text-style: bold;
    }

    #manage-neg-table, #manage-pos-table {
        height: 1fr;
        border: round #3d4f63;
        background: #0b1016;
    }

    #manage-neg-table:focus-within, #manage-pos-table:focus-within {
        border: round $accent;
    }

    #manage-neg-table > .datatable--header,
    #manage-pos-table > .datatable--header {
        background: #0b1016;
        color: #63f3ff;
        text-style: bold;
    }

    #manage-neg-table > .datatable--cursor,
    #manage-pos-table > .datatable--cursor {
        background: #1e2a36;
        color: #d7dde8;
    }

    #edit-bar {
        display: none;
        height: auto;
        align: center middle;
        margin-top: 1;
        padding: 0 2;
    }

    #edit-bar.visible {
        display: block;
    }

    #edit-bar-help {
        color: #8d98a7;
        margin-top: 1;
        text-align: center;
    }

    #manage-help {
        color: #8d98a7;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("d", "delete_entry", "Delete"),
        ("e", "edit_date", "Edit Date"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._cache: DataCache | None = None
        self._editing_entry: dict | None = None  # {mode, date, name, points}
        self._active_tab = "negatives"
        self._entry_data: dict[str, dict] = {}  # row_key → entry data

    def compose(self) -> ComposeResult:
        with Container(id="manage-dialog"):
            with Container(id="manage-box"):
                yield Tabs(
                    Tab("Negatives", id="tab-negatives"),
                    Tab("Positives", id="tab-positives"),
                    id="manage-tabs",
                )
                # Negative table (visible by default)
                yield DataTable(
                    zebra_stripes=False, cursor_type="row", id="manage-neg-table"
                )
                # Positive table (hidden)
                yield DataTable(
                    zebra_stripes=False, cursor_type="row", id="manage-pos-table"
                )
                # Inline edit bar (hidden until e is pressed)
                with Container(id="edit-bar"):
                    yield DateStepper(id="edit-date-stepper")
                    yield Static(
                        "[bold #63f3ff]Enter[/] confirm  [bold #8d98a7]Esc[/] cancel",
                        id="edit-bar-help",
                    )
                yield Static(
                    "[bold #63f3ff]d[/] [dim]Delete[/]    "
                    "[bold #63f3ff]e[/] [dim]Edit Date[/]    "
                    "[bold #63f3ff]Esc[/] [dim]Close[/]",
                    id="manage-help",
                )

    def on_mount(self) -> None:
        self.query_one("#manage-box").border_title = (
            "[b][#63f3ff]Manage Activity Log[/][/]"
        )

        # Set up negative table
        neg_table = self.query_one("#manage-neg-table", DataTable)
        neg_table.add_columns("Date", "Name", "Points")
        for col in neg_table.columns.values():
            col.text_align = "center"
        neg_table.styles.display = "block"
        neg_table.can_focus = True

        # Set up positive table
        pos_table = self.query_one("#manage-pos-table", DataTable)
        pos_table.add_columns("Date", "Name", "Points")
        for col in pos_table.columns.values():
            col.text_align = "center"
        pos_table.styles.display = "none"
        pos_table.can_focus = True

        # Hide positive tab initially — we start on negatives
        # Actually, we default to Negatives tab active
        self._refresh_tables()

    # ── helpers ────────────────────────────────────────────────────

    def _load_cache(self) -> DataCache:
        if self._cache is None:
            self._cache = DataCache.load()
        return self._cache

    def _fmt_points(self, pts: float) -> str:
        if pts >= 0:
            return f"+{int(pts)}" if pts == int(pts) else f"+{pts:.1f}"
        return str(int(pts)) if pts == int(pts) else f"{pts:.1f}"

    def _rebuild_table(self, mode: str) -> None:
        """Reload the negative or positive table from cache."""
        table_id = "#manage-neg-table" if mode == "negative" else "#manage-pos-table"
        table = self.query_one(table_id, DataTable)
        table.clear(columns=False)

        cache = self._load_cache()
        if mode == "negative":
            rows = cache.get_negative_log_rows(limit=10000)
            for idx, r in enumerate(rows):
                pts = -float(r["points"])
                name_text = Text.from_markup(f"[#ff5f5f]{r['name']}[/]")
                key = f"neg|{r['date']}|{r['name']}|{idx}"
                self._entry_data[key] = {
                    "mode": "negative",
                    "date": r["date"],
                    "name": r["name"],
                    "points": float(r["points"]),
                }
                table.add_row(
                    r["date"],
                    name_text,
                    self._fmt_points(pts),
                    key=key,
                )
        else:
            rows = cache.get_positive_log_rows(limit=10000)
            for idx, r in enumerate(rows):
                pts = float(r["points"])
                name_text = Text.from_markup(f"[#37d994]{r['name']}[/]")
                key = f"pos|{r['date']}|{r['name']}|{idx}"
                self._entry_data[key] = {
                    "mode": "positive",
                    "date": r["date"],
                    "name": r["name"],
                    "points": float(r["points"]),
                }
                table.add_row(
                    r["date"],
                    name_text,
                    self._fmt_points(pts),
                    key=key,
                )

        if len(table.rows) > 0:
            table.move_cursor(row=0)

    def _get_selected_entry(self) -> dict | None:
        """Get the currently selected entry from the active table."""
        table = self._get_active_table()
        if table is None or table.cursor_row < 0:
            return None
        try:
            row_key = str(list(table.rows.keys())[table.cursor_row].value)
            return self._entry_data.get(row_key)
        except (IndexError, AttributeError):
            return None

    def _get_active_table(self) -> DataTable | None:
        table_id = "#manage-neg-table" if self._active_tab == "negatives" else "#manage-pos-table"
        try:
            return self.query_one(table_id, DataTable)
        except Exception:
            return None

    def _refresh_tables(self) -> None:
        """Refresh both tables (reload from CSV on disk)."""
        # Force cache reload so we see latest data
        self._cache = DataCache.load()
        if self._active_tab == "negatives":
            self._rebuild_table("negative")
        else:
            self._rebuild_table("positive")

    def _show_edit_bar(self) -> None:
        """Show the inline date edit bar."""
        edit_bar = self.query_one("#edit-bar")
        edit_bar.set_class(True, "visible")

    def _hide_edit_bar(self) -> None:
        """Hide the inline date edit bar."""
        edit_bar = self.query_one("#edit-bar")
        edit_bar.set_class(False, "visible")
        self._editing_entry = None

    # ── tab switching ──────────────────────────────────────────────

    @on(Tabs.TabActivated, "#manage-tabs")
    def _on_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab.id == "tab-negatives":
            self._active_tab = "negatives"
            self.query_one("#manage-neg-table", DataTable).styles.display = "block"
            self.query_one("#manage-pos-table", DataTable).styles.display = "none"
            self._rebuild_table("negative")
            self.query_one("#manage-neg-table", DataTable).focus()
        else:
            self._active_tab = "positives"
            self.query_one("#manage-neg-table", DataTable).styles.display = "none"
            self.query_one("#manage-pos-table", DataTable).styles.display = "block"
            self._rebuild_table("positive")
            self.query_one("#manage-pos-table", DataTable).focus()
        self._hide_edit_bar()

    # ── actions ────────────────────────────────────────────────────

    def action_cancel(self) -> None:
        if self._editing_entry is not None:
            self._cancel_edit()
            return
        self.dismiss(True)  # Signal that views should refresh

    def action_delete_entry(self) -> None:
        """Delete the currently selected entry after confirmation."""
        if self._editing_entry is not None:
            return  # Don't delete while editing

        entry = self._get_selected_entry()
        if entry is None:
            status_message(self.app, "Select an entry in the table first.", severity="warning")
            return

        # Push confirmation
        def after_confirm(confirmed: bool) -> None:
            if confirmed:
                logger.debug("ManageScreen: deleting %s entry '%s' (%s)",
                              entry["mode"], entry["name"], entry["date"])
                ok, msg = delete_activity_entry(
                    entry["mode"], entry["date"], entry["name"]
                )
                if ok:
                    self._refresh_tables()
                    status_message(self.app, msg)
                else:
                    status_message(self.app, msg, severity="error")

        self.app.push_screen(
            ConfirmScreen("Delete Entry", f"Delete '{entry['name']}' from {entry['date']}?"),
            after_confirm,
        )

    def action_edit_date(self) -> None:
        """Start editing the date of the selected entry."""
        if self._editing_entry is not None:
            return  # Already editing

        entry = self._get_selected_entry()
        if entry is None:
            status_message(self.app, "Select an entry in the table first.", severity="warning")
            return

        self._editing_entry = entry

        # Parse the entry's date
        try:
            entry_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        except ValueError:
            status_message(self.app, "Could not parse the entry date.", severity="error")
            return

        # Set up the date stepper
        stepper = self.query_one("#edit-date-stepper", DateStepper)
        stepper.selected_date = entry_date
        stepper.max_date = date.today()
        self._show_edit_bar()
        stepper.focus()

    # ── key handling for edit bar ──────────────────────────────────

    def on_key(self, event) -> None:
        """Handle left/right for tab switching, and Enter/Escape while editing."""
        if self._editing_entry is None:
            tabs = self.query_one("#manage-tabs", Tabs)
            if event.key == "left":
                event.stop()
                if self._active_tab != "negatives":
                    tabs.active = "tab-negatives"
            elif event.key == "right":
                event.stop()
                if self._active_tab != "positives":
                    tabs.active = "tab-positives"
            return

        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self._confirm_edit()
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self._cancel_edit()

    def _confirm_edit(self) -> None:
        """Apply the date change."""
        if self._editing_entry is None:
            return
        entry = self._editing_entry
        stepper = self.query_one("#edit-date-stepper", DateStepper)
        new_date = stepper.selected_date.strftime("%Y-%m-%d")

        if new_date == entry["date"]:
            self._hide_edit_bar()
            return  # No change

        logger.debug("ManageScreen: updating %s entry '%s' from %s to %s",
                      entry["mode"], entry["name"], entry["date"], new_date)
        ok, msg = update_activity_date(
            entry["mode"], entry["date"], entry["name"], new_date
        )
        if ok:
            self._hide_edit_bar()
            self._refresh_tables()
            status_message(self.app, msg)
        else:
            status_message(self.app, msg, severity="error")

    def _cancel_edit(self) -> None:
        """Cancel date editing."""
        self._hide_edit_bar()
        # Re-focus the active table
        table = self._get_active_table()
        if table:
            table.focus()
