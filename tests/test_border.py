from textual.app import App
from textual.widgets import DataTable
from textual.containers import Vertical

class TestApp(App):
    CSS = """
    * {
        scrollbar-size: 0 0;
    }
    .box {
        border: solid #2e3947;
        height: auto;
    }
    """
    def compose(self):
        v = Vertical(classes="box")
        v.border_title = "[#63f3ff][b]My Title[/b][/]"
        v.border_subtitle = "[#8d98a7]Subtitle[/]"
        with v:
            yield DataTable()

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K")
        for i in range(10):
            table.add_row(*[str(x) for x in range(11)])

if __name__ == "__main__":
    TestApp().run()
