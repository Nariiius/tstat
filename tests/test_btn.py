from textual.app import App
from textual.widgets import Button
class TestApp(App):
    CSS = "Button { padding: 0; height: 1; }"
    def compose(self):
        yield Button("Hello World")
if __name__ == "__main__":
    app = TestApp()
    app.run()
