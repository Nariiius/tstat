from textual.app import App, ComposeResult
from textual.widgets import DataTable
from textual import events, on
import asyncio

class TestApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("C1", key="c1")
        yield table

    def on_mount(self):
        self.query_one("#t", DataTable).add_row("Hello")

    @on(events.Resize)
    def on_any_resize(self, event: events.Resize) -> None:
        with open("loop.log", "a") as f:
            f.write(f"Resize App: {event.size}\n")
        self.set_timer(0.05, self.do_resize)

    def do_resize(self):
        with open("loop.log", "a") as f:
            f.write("do_resize called\n")
        table = self.query_one("#t", DataTable)
        table.columns["c1"].width = 20
        table.refresh(layout=True)

if __name__ == "__main__":
    import os
    if os.path.exists("loop.log"):
        os.remove("loop.log")
    app = TestApp()
    asyncio.run(app.run_test(size=(40, 20)))
