from textual.app import App, ComposeResult
from textual.widgets import DataTable
import asyncio

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("Category", key="c1")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        print("BEFORE ROW, auto_width:", table.columns["c1"].auto_width, "content_width:", table.columns["c1"].content_width)
        table.add_row("Very long category")
        print("AFTER ROW, auto_width:", table.columns["c1"].auto_width, "content_width:", table.columns["c1"].content_width)
        table.columns["c1"].auto_width = False
        table.add_row("Very long category 22222")
        print("AFTER ROW (auto_width=False), content_width:", table.columns["c1"].content_width)

async def main():
    app = TableApp()
    async with app.run_test() as pilot:
        pass

if __name__ == "__main__":
    asyncio.run(main())