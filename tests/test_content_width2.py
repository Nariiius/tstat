from textual.app import App, ComposeResult
from textual.widgets import DataTable
import asyncio

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("Category", key="c1")
        table.add_column("Hours", key="c2")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.columns["c1"].auto_width = False
        table.columns["c1"].width = 3
        table.add_row("Very long category", "100.0")
        print("AFTER ADD ROW:", table.columns["c1"].content_width)

async def main():
    app = TableApp()
    async with app.run_test() as pilot:
        pass

if __name__ == "__main__":
    asyncio.run(main())
