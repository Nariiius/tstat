import asyncio
from TogglTrack import TogglTUI, load_runtime_settings

async def test_app():
    load_runtime_settings()
    app = TogglTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        print("App started")
        
        # Switch to Week view (index 2)
        await pilot.press("right", "right")
        await pilot.pause()
        print(f"Active view: {app.VIEWS[app.active_view_index]}")
        
        # Check week table columns
        table = app.query_one("#week-table")
        print(f"Week table columns: {[c.label for c in table.columns.values()]}")
        
        # Check category table for LOGGED POSITIVE
        cat_table = app.query_one("#week-category-table")
        rows = [cat_table.get_row_at(i) for i in range(cat_table.row_count)]
        print(f"Category table rows: {[r[0] for r in rows]}")
        
        await pilot.press("q")

if __name__ == "__main__":
    asyncio.run(test_app())
