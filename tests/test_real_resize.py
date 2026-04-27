import asyncio
from TogglTrack import TogglTUI
from textual.events import Resize
from textual.geometry import Size

class TestTUI(TogglTUI):
    def on_resize(self):
        super().on_resize()
        with open("resize_real.log", "a") as f:
            f.write(f"on_resize App called\n")
            
    def _resize_tables(self):
        super()._resize_tables()
        with open("resize_real.log", "a") as f:
            f.write(f"_resize_tables called, app size: {self.size}, content size: {self.query_one('#content').size}\n")
            t = self.query_one("#week-table")
            if t.columns:
                f.write(f"col width: {t.columns[list(t.columns.keys())[0]].width}\n")

async def main():
    import os
    if os.path.exists("resize_real.log"):
        os.remove("resize_real.log")
    app = TestTUI()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.5)
        # We manually change the app size and dispatch a Resize event
        # Actually run_test doesn't support pilot.resize natively in old Textual versions.
        # So we dispatch Resize manually
        app.post_message(Resize(Size(100, 24), Size(80, 24)))
        await pilot.pause(0.5)

if __name__ == "__main__":
    asyncio.run(main())
