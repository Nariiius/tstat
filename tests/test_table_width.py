import sys
from textual.app import App, ComposeResult
from textual.widgets import DataTable

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable()
        table.add_column("Col1", key="c1")
        table.add_column("Col2", key="c2")
        yield table

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_row("A", "B")
        
    def on_resize(self):
        table = self.query_one(DataTable)
        if "c1" in table.columns:
            table.columns["c1"].width = self.size.width // 2
            table.columns["c2"].width = self.size.width // 2
            table.refresh()

TableApp().run()
