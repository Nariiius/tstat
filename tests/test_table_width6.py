from textual.app import App, ComposeResult
from textual.widgets import DataTable
from textual import events, on
import asyncio

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("Category", key="c1")
        table.add_column("Hours", key="c2")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.add_row("A very long category name that should be cut", "100.00")
        
    @on(events.Resize, "DataTable")
    def on_table_resize(self, event: events.Resize):
        table = event.control
        print(f"Table resize event: {event.size}")
        if not table.columns:
            return
            
        aw = event.size.width
        if aw <= 0:
            return
            
        print(f"Resizing columns with aw={aw}")
        table.columns["c1"].width = aw // 2
        table.columns["c1"].auto_width = False
        table.columns["c2"].width = aw // 2
        table.columns["c2"].auto_width = False
        table.refresh()

async def main():
    app = TableApp()
    async with app.run_test(size=(60, 20)) as pilot:
        pass

if __name__ == "__main__":
    asyncio.run(main())
