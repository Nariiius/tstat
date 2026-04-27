import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Static

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("Hello")

    def on_resize(self, event):
        with open("resize_app.log", "a") as f:
            f.write(f"App on_resize: {event}\n")

async def main():
    app = TestApp()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.resize(width=60, height=20)

if __name__ == "__main__":
    import os
    if os.path.exists("resize_app.log"):
        os.remove("resize_app.log")
    try:
        asyncio.run(main())
    except:
        pass
