import sys
from textual.app import App, ComposeResult
from textual.widgets import DataTable
from textual.containers import Container

class TableApp(App):
    CSS = """
    DataTable {
        border: solid green;
    }
    """
    def compose(self) -> ComposeResult:
        table = DataTable()
        table.add_columns("A", "B")
        table.add_row("Long text to see", "Short")
        yield table

    def on_mount(self):
        self.set_timer(0.5, self.measure)

    def measure(self):
        t = self.query_one(DataTable)
        # Set widths explicitly to match our math
        # Let's say terminal width is 80.
        # content_budget = 80 - 2 (borders) - (2*1*2 padding) = 74
        # "Short" requires 5. "A" requires 74 - 5 = 69
        cols = list(t.columns.keys())
        t.columns[cols[0]].width = 69
        t.columns[cols[0]].auto_width = False
        t.columns[cols[1]].width = 5
        t.columns[cols[1]].auto_width = False
        t.refresh(layout=True)
        self.set_timer(0.5, self.exit)

app = TableApp()
app.run()
