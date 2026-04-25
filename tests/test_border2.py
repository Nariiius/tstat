from textual.app import App
from textual.widgets import DataTable

class TestApp(App):
    CSS = """
    * { scrollbar-size: 0 0; }
    #root { padding: 1; }
    DataTable {
        border: solid #2e3947;
        height: 1fr;
    }
    """
    def compose(self):
        table = DataTable()
        table.border_title = "[b][#63f3ff]My Table[/][/]"
        table.border_subtitle = "[#8d98a7]Subtitle[/]"
        yield table

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("A", "B", "C")
        for i in range(5):
            table.add_row("1", "2", "3")

if __name__ == "__main__":
    TestApp().run()
