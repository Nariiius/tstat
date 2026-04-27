from textual.app import App, ComposeResult
from textual.widgets import DataTable
import asyncio

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("Col1", key="c1")
        table.add_column("Col2", key="c2")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.add_row("A very long text that should be cut", "100.00")
        
async def main():
    app = TableApp()
    async with app.run_test() as pilot:
        table = app.query_one("#t", DataTable)
        for col in table.columns.values():
            print(f"col: {col.label}, content_width: {col.content_width}, width: {col.width}, auto_width: {col.auto_width}")

if __name__ == "__main__":
    asyncio.run(main())
