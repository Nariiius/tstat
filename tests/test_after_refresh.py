import asyncio
from textual.app import App, ComposeResult
from textual.widgets import DataTable
from textual.containers import Horizontal, Vertical

class TableApp(App):
    def compose(self) -> ComposeResult:
        with Horizontal():
            table = DataTable(id="t")
            table.add_column("Category", key="c1")
            yield table
            yield Vertical(id="spark", styles="width: 32;")

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.add_row("Very long category")

    def on_resize(self):
        self.call_after_refresh(self._resize_tables)

    def _resize_tables(self):
        table = self.query_one("#t", DataTable)
        print(f"Table size: {table.size.width}, Outer: {table.outer_size.width}")
        if table.size.width > 0:
            table.columns["c1"].width = table.size.width
            table.columns["c1"].auto_width = False
            table.refresh()

async def main():
    app = TableApp()
    async with app.run_test(size=(80, 24)) as pilot:
        table = app.query_one("#t", DataTable)
        await pilot.pause(0.1)
        print("Final column width:", table.columns["c1"].width)

if __name__ == "__main__":
    asyncio.run(main())