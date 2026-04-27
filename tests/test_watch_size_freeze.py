from textual.app import App, ComposeResult
from textual.widgets import Static
import asyncio

class TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("Hello " * 100, id="s", styles="background: red; width: 100%; height: 100%;")

    def watch_size(self, size):
        pass

async def main():
    app = TestApp()
    async with app.run_test(size=(40, 20)) as pilot:
        pass
        
if __name__ == "__main__":
    asyncio.run(main())
