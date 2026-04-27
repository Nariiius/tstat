from toggl.tui import strip_ansi

# The user explicitly wants a *maximum* of (max space / n_cols) for each column.
# Let's say available_width is 120. n_cols is 4.
# max_w = 120 / 4 = 30.
# So no column can be larger than 30.
# If required width is < 30, does it just get its required width?
# User: "make it so all columns have their own minium and have a maximum of (max space available/number of columns)"
# But if we cap the max, and use minimum for others, there's STILL empty space remaining.
# "No you are not using the whole space available. there is still space on the right side which can be put to use"
# Wait, if they want to USE the whole space available, they MUST want to expand the columns.
# If we cap the maximum to (max space / number of columns), and ALL columns reach the maximum, then they use all the space.
# But what if a column only needs 5 width? If we expand it to 30, it's just 25 width of empty space inside the column.

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

print(f"content_budget: {content_budget}, total_req_content: {total_req_content}")

max_col_w = content_budget // n_cols
print(f"max_col_w allowed: {max_col_w}")

# The user explicitly wants us to cap column widths at `max_col_w`, 
# BUT also they said "there is still space on the right side which can be put to use".
# If they want NO space on the right side, the sum of widths must exactly equal content_budget.
# Wait! The user said: "make it so all columns have their own minium and have a maximum of (max space available/number of columns)"
# Let's interpret: "use all space available" means sum(widths) = content_budget.
# Every column gets at least `req_widths[key]`.
# Any extra space is distributed among the columns, BUT a column's width shouldn't exceed `max_col_w`... Wait, if all columns hit `max_col_w`, their sum is exactly `content_budget` (since `max_col_w = content_budget / n_cols`).
# So if a column doesn't reach `max_col_w` because its required width is smaller? 
# If its required width is small, and we don't give it more width, then some OTHER column must get more than `max_col_w` in order to use up the full budget!
# So maybe the user meant: "Give every column its required width. Distribute remaining space evenly across all columns. But if a column is already really big, maybe cap it? No, capping it leaves empty space."
# Actually, the user's screenshot shows the "Mistake" row with "Points: -20.0".
# In my `git diff` output above, I already changed `expandable_keys` to be ALL columns:
# `expandable_keys = list(table.columns.keys())`
# Wait, I made that change previously to fix the previous "push to right" bug, but then I abandoned it when I restored the older `_resize_tables`?
# No, my `git diff` shows that `expandable_keys` IS currently `list(table.columns.keys())` in `toggl/tui.py` right now!
# Let me check the screenshot again... 
# Ah, the screenshot shows the result of `expandable_keys = list(table.columns.keys())`!
# Because I divided the extra space equally among ALL 4 columns, ALL 4 columns grew. 
# BUT since the table is so wide, "Hours", "Rate", and "Points" all got massive padding. 
# "Points" got +20 width. "Rate" got +20 width. 
# Since text is left-aligned by default, the text sits on the left of its massive column, and the rest of the column is empty space!
# So for the "Rate" column, it prints "x3" and then has 20 spaces. Then "Points" prints "+64.5" and has 20 spaces.
# That creates the huge visual "empty space" the user is complaining about! They are seeing the empty space *inside* the rightmost columns because those columns were given extra width!

# If the user wants NO wasted space, AND they don't want it pushed to the right, how should columns be sized?
# If we just give them `req_widths` and NO extra width, then the table just ends. That was the "squished" version from two turns ago.
# "You understood me wrong I want it to the right" -> Wait, they didn't say "I want it to the right" in this turn.
# In the previous turn, they said: "It should be like this 'Hours Rate Points' should be to the left side with no wasted space". Wait, "to the left side"?
# No, let's read carefully: "They should be to the left not to the right or middle?" (Screenshot shows numbers squished to the left, which happens when auto_width=True without expanding).
# AND THEN they said: "No you are not using the whole space available. there is still space on the right side which can be put to use ... make it so all columns have their own minium and have a maximum of (max space available/number of columns)"

# Okay, they want the entire width of the screen to be used. So sum(widths) == content_budget.
# They want to cap the maximum width of any column to `content_budget // n_cols` (i.e. distribute width evenly).
# BUT they want the text inside the numbers columns to be... wait. 
# If they distribute width evenly, there WILL be empty space inside the columns. Textual aligns text to the left by default for strings. If a column is 30 chars wide and contains "x3", there are 28 spaces of "wasted space" *inside* that column.
# Maybe they want the numbers to be RIGHT-aligned inside their columns?
# "make it so all columns have their own minium and have a maximum of (max space available/number of columns)"

# Let's write an algorithm that distributes `content_budget` exactly as requested:
# 1. Give every column its `req_width`.
# 2. If total is less than budget, distribute the remaining space.
# 3. Cap any column's width at `content_budget // n_cols` IF possible, but if that leaves unused space, we have to distribute it anyway?
# Let's just evenly divide the `content_budget` among all columns: `target_w = content_budget // n_cols`.
# If `req_width > target_w`, it gets `req_width`.
# If `req_width <= target_w`, it gets `target_w`.
# If sum(widths) > content_budget, we're over budget (which is fine, table will scroll or clip, but we want to avoid that if possible).

# Let's see what happens with:
# w = max(req_widths[key], content_budget // n_cols)
# Then sum(w) >= content_budget.
# This guarantees no empty space at the right of the table, because the table takes up at least `content_budget`.
# Let's test this math.
content_budget = 112
n_cols = 4
target_w = content_budget // n_cols # 28

final_widths = {}
for key in col_keys:
    final_widths[key] = max(req_widths[key], target_w)
    
print("Final widths:", final_widths)
print("Sum:", sum(final_widths.values()))
