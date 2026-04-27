import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Static
from textual import events, on

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("Hello", id="s")

    @on(events.Resize)
    def on_any_resize(self, event: events.Resize) -> None:
        with open("resize_any.log", "a") as f:
            f.write(f"Resize: {event.size}\n")

async def main():
    import os
    if os.path.exists("resize_any.log"):
        os.remove("resize_any.log")
    app = TestApp()
    async with app.run_test(size=(40, 20)) as pilot:
        pass
        
if __name__ == "__main__":
    asyncio.run(main())