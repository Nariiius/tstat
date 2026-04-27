from toggl.tui import strip_ansi

# Let's mock the DataTable properties and see how width calculation works.

class MockColumn:
    def __init__(self, name):
        class Label:
            def __init__(self, plain):
                self.plain = plain
        self.label = Label(name)
        self.width = 0
        self.auto_width = True

class MockTable:
    def __init__(self):
        self.columns = {
            'Category': MockColumn('Category'),
            'Hours': MockColumn('Hours'),
            'Rate': MockColumn('Rate'),
            'Points': MockColumn('Points')
        }
        self.cell_padding = 1
        self.row_count = 1
        
    def get_row_at(self, idx):
        return ["Learning to Code", "21.50h", "x3", "+64.5"]

table = MockTable()
available_width = 120 # typical terminal width
col_keys = list(table.columns.keys())
n_cols = len(col_keys)
req_widths = {key: len(col.label.plain) for key, col in table.columns.items()}

for row_idx in range(table.row_count):
    row_data = table.get_row_at(row_idx)
    for col_idx, col_key in enumerate(col_keys):
        val = str(row_data[col_idx])
        cell_w = len(strip_ansi(val))
        if cell_w > req_widths[col_key]:
            req_widths[col_key] = cell_w

print(f"req_widths: {req_widths}")

total_padding = 2 * table.cell_padding * n_cols
content_budget = available_width - total_padding
total_req_content = sum(req_widths.values())

print(f"total_padding: {total_padding}, content_budget: {content_budget}, total_req_content: {total_req_content}")

expandable_keys = ["Category"]
fixed_keys = ["Hours", "Rate", "Points"]

extra = content_budget - total_req_content
print(f"extra width: {extra}")

for key in fixed_keys:
    table.columns[key].width = req_widths[key]

expand_extra = extra // len(expandable_keys)
print(f"expand_extra for {expandable_keys[0]}: {expand_extra}")

table.columns[expandable_keys[0]].width = req_widths[expandable_keys[0]] + expand_extra

print("Final widths:")
for k, col in table.columns.items():
    print(f"  {k}: {col.width}")
