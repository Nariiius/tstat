from textual.app import App
import asyncio
import sys

class TestApp(App):
    def watch_size(self, size) -> None:
        with open("watch_size2.log", "a") as f:
            f.write(f"watch_size called: {size}\n")

async def main():
    app = TestApp()
    async with app.run_test(size=(40, 20)) as pilot:
        pass
        
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
