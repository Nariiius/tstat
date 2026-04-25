from textual.app import App
from textual.widgets import DataTable

class TestApp(App):
    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-background: #0b1016;
        scrollbar-color: #2e3947;
    }
    """
    def compose(self):
        yield DataTable()

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K")
        for i in range(100):
            table.add_row(*[str(x) for x in range(11)])

if __name__ == "__main__":
    TestApp().run()
