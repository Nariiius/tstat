from textual.app import App, ComposeResult
from textual.widgets import DataTable
import asyncio

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t", show_horizontal_scrollbar=False)
        table.add_column("Category", key="c1")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.add_row("Very long category " * 5)
        
    def on_resize(self, event):
        table = self.query_one("#t", DataTable)
        print("Resize App event:", event)

async def main():
    app = TableApp()
    async with app.run_test(size=(40, 20)) as pilot:
        pass

if __name__ == "__main__":
    asyncio.run(main())