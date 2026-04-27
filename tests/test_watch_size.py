from textual.app import App
import asyncio

class TestApp(App):
    def watch_size(self, old_size, new_size):
        with open("watch_size.log", "a") as f:
            f.write(f"watch_size called: {new_size}\n")

async def main():
    import os
    if os.path.exists("watch_size.log"):
        os.remove("watch_size.log")
    app = TestApp()
    async with app.run_test(size=(40, 20)) as pilot:
        pass
        
if __name__ == "__main__":
    asyncio.run(main())
