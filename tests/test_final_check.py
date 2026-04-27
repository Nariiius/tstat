import asyncio
import sys
from TogglTrack import TogglTUI
from textual.events import Resize
from textual.geometry import Size

class TestTUI(TogglTUI):
    def _resize_tables(self):
        super()._resize_tables()
        t = self.query_one("#week-table")
        if t.columns:
            widths = {k: v.width for k, v in t.columns.items()}
            print(f"WEEK TABLE WIDTHS: {widths}")
            sys.exit(0)

async def main():
    app = TestTUI()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.5)
        # Should exit automatically
        print("Failed to exit")

if __name__ == "__main__":
    asyncio.run(main())
