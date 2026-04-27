from textual.app import App, ComposeResult
from textual.widgets import Static
from textual import events, on

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("Hello World! " * 20, id="s", styles="background: red; width: 100%; height: 100%;")

    @on(events.Resize)
    def _on_app_resize(self, event: events.Resize):
        self.query_one("#s").update(f"Resized to {event.size}")

if __name__ == "__main__":
    app = TestApp()
    app.run()
