import asyncio
from TogglTrack import TogglTUI

async def main():
    app = TogglTUI()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.5)
        table = app.query_one("#week-table")
        print("WEEK TABLE COLUMNS")
        for key, col in table.columns.items():
            print(f"  {col.label.plain}: width={col.width} (auto={col.auto_width})")
            
        print("OVERVIEW TABLE COLUMNS")
        overview = app.query_one("#overview-table")
        for key, col in overview.columns.items():
            print(f"  {col.label.plain}: width={col.width} (auto={col.auto_width})")

if __name__ == "__main__":
    asyncio.run(main())