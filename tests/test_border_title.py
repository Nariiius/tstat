from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static

class TestApp(App):
    CSS = """
    * { scrollbar-size: 0 0; }
    #chrome {
        border-top: solid #2e3947;
        border-bottom: solid #2e3947;
        height: 3;
        padding: 0 1;
    }
    .tab { margin-right: 2; }
    """
    def compose(self) -> ComposeResult:
        with Container(id="chrome"):
            with Horizontal():
                yield Static("Overview", classes="tab")
                yield Static("Models", classes="tab")

    def on_mount(self):
        chrome = self.query_one("#chrome")
        chrome.border_title = "[b][#63f3ff]tokscale[/][/]"
        chrome.border_subtitle = "  | [#8d98a7]Updated 2m ago[/]"

if __name__ == "__main__":
    TestApp().run()
