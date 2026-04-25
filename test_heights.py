from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static

class TestApp(App):
    CSS = """
    * { scrollbar-size: 0 0; }
    #topbar {
        height: 1;
        border-bottom: solid #2e3947;
    }
    #chrome {
        height: 1;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="topbar"):
                yield Static("togglscale")
            with Horizontal(id="chrome"):
                yield Static("Tabs here")

if __name__ == "__main__":
    TestApp().run()
