from textual.app import App, ComposeResult
from textual.widgets import Static
from textual import events

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("Hello", id="s")

    def on_resize(self, event: events.Resize):
        with open("resize.log", "a") as f:
            f.write(f"Resize: {event.size}\n")

if __name__ == "__main__":
    import os
    if os.path.exists("resize.log"):
        os.remove("resize.log")
    app = TestApp()
    # We can't easily manually resize in run_test, but we can run with different sizes
