from textual.app import App, ComposeResult
from textual.widgets import Static
from textual import events
import asyncio

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("Hello", id="s")

    def on_resize(self, event: events.Resize) -> None:
        with open("resize.log", "a") as f:
            f.write(f"Resize: {event.size}\n")

async def main():
    import os
    if os.path.exists("resize.log"):
        os.remove("resize.log")
    app = TestApp()
    async with app.run_test(size=(40, 20)) as pilot:
        pass
        
if __name__ == "__main__":
    asyncio.run(main())