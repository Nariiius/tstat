from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, DataTable

class TestApp(App):
    CSS = """
    * { scrollbar-size: 0 0; }
    #chrome {
        height: 3;
        border: solid #2e3947;
    }
    #main {
        height: 1fr;
    }
    DataTable {
        height: 1fr;
        border: solid #2e3947;
    }
    #footer {
        height: auto;
    }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            with Vertical(id="chrome"):
                yield Static("chrome")
            with Horizontal(id="main"):
                yield DataTable()
            with Vertical(id="footer"):
                yield Static("footer")

    def on_mount(self):
        chrome = self.query_one("#chrome")
        chrome.border_title = "[b][#63f3ff]chrome[/][/]"
        
        table = self.query_one(DataTable)
        table.border_title = "[b][#63f3ff]table[/][/]"
        table.add_columns("A", "B", "C")
        for i in range(5):
            table.add_row("1", "2", "3")

if __name__ == "__main__":
    TestApp().run()
