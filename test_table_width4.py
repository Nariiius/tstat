from textual.app import App, ComposeResult
from textual.widgets import DataTable
import asyncio

class TableApp(App):
    def compose(self) -> ComposeResult:
        table = DataTable(id="t")
        table.add_column("Category", key="c1")
        table.add_column("Hours", key="c2")
        table.add_column("Points", key="c3")
        yield table

    def on_mount(self):
        table = self.query_one("#t", DataTable)
        table.add_row("A very long category name that should be cut", "100.00", "200.00")
        
    def on_resize(self):
        table = self.query_one("#t", DataTable)
        if not table.columns:
            return
            
        available_width = max(10, self.size.width - 2)
        text_cols = {"Category", "Negative", "Positive", "Metric", "Value"}
        
        req_widths = {}
        for key, col in table.columns.items():
            req_widths[key] = max(len(col.label.plain), col.content_width) + 2
            
        total_req_width = sum(req_widths.values())
        
        expandable_keys = []
        fixed_keys = []
        for key, col in table.columns.items():
            if col.label.plain in text_cols:
                expandable_keys.append(key)
            else:
                fixed_keys.append(key)
                
        if not expandable_keys:
            expandable_keys = list(table.columns.keys())
            fixed_keys = []
            
        if available_width >= total_req_width:
            extra = available_width - total_req_width
            for key in fixed_keys:
                table.columns[key].width = req_widths[key]
                table.columns[key].auto_width = False
                
            expand_extra = extra // len(expandable_keys)
            rem = extra % len(expandable_keys)
            for i, key in enumerate(expandable_keys):
                table.columns[key].width = req_widths[key] + expand_extra + (1 if i < rem else 0)
                table.columns[key].auto_width = False
        else:
            fixed_req = sum(req_widths[k] for k in fixed_keys)
            if available_width > fixed_req and expandable_keys:
                for key in fixed_keys:
                    table.columns[key].width = req_widths[key]
                    table.columns[key].auto_width = False
                rem_width = available_width - fixed_req
                base_w = rem_width // len(expandable_keys)
                rem = rem_width % len(expandable_keys)
                for i, key in enumerate(expandable_keys):
                    table.columns[key].width = max(1, base_w + (1 if i < rem else 0))
                    table.columns[key].auto_width = False
            else:
                for i, key in enumerate(table.columns.keys()):
                    base_w = available_width // len(table.columns)
                    rem = available_width % len(table.columns)
                    table.columns[key].width = base_w + (1 if i < rem else 0)
                    table.columns[key].auto_width = False
        table.refresh()

async def main():
    app = TableApp()
    async with app.run_test(size=(60, 20)) as pilot:
        table = app.query_one("#t", DataTable)
        for col in table.columns.values():
            print(f"col: {col.label}, req_width: {max(len(col.label.plain), col.content_width) + 2}, width: {col.width}")
            
    async with app.run_test(size=(40, 20)) as pilot:
        table = app.query_one("#t", DataTable)
        for col in table.columns.values():
            print(f"col: {col.label}, req_width: {max(len(col.label.plain), col.content_width) + 2}, width: {col.width}")

if __name__ == "__main__":
    asyncio.run(main())
