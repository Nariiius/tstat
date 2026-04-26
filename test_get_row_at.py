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
        table.add_row("Very long category")
        
        # Test getting rows
        for i in range(table.row_count):
            row = table.get_row_at(i)
            print(f"Row {i}: {row}")

async def main():
    app = TableApp()
    async with app.run_test() as pilot:
        pass

if __name__ == "__main__":
    asyncio.run(main())