from textual.app import App, ComposeResult
from textual.widgets import DataTable

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("Col1", key="c1")
        table.add_column("Col2", key="c2")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.add_row("A", "B")
        
    def on_resize(self):
        table = self.query_one("#t", DataTable)
        if "c1" in table.columns:
            w = self.size.width // 2
            table.columns["c1"].width = w
            table.columns["c2"].width = w
            table.refresh()

if __name__ == "__main__":
    TableApp().run()
