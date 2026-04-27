import asyncio
import os
from TogglTrack import TogglTUI

class TestTUI(TogglTUI):
    def on_resize(self, event):
        super().on_resize()
        with open("resize_app.log", "a") as f:
            f.write(f"Resize App: {event.size}\n")
            
    def _resize_tables(self):
        super()._resize_tables()
        with open("resize_app.log", "a") as f:
            f.write(f"_resize_tables called\n")

async def main():
    if os.path.exists("resize_app.log"):
        os.remove("resize_app.log")
    app = TestTUI()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.5)
        # We need to simulate terminal resize
        # pilot.app.post_message(events.Resize(size=...)) 
        from textual.events import Resize
        from textual.geometry import Size
        app.post_message(Resize(Size(100, 24), Size(80, 24)))
        await pilot.pause(0.5)

if __name__ == "__main__":
    asyncio.run(main())
