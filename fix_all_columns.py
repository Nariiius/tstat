import re

with open("toggl/tui.py", "r") as f:
    content = f.read()

# Replace the part where we isolate expandable_keys based on text_cols
# We will just make all columns expandable so they all stretch and fill the space equally.
# We will also add a tiny bit of extra width (+1) to available_width if there is an off-by-1 error, but let's stick to content_w - 2.

old_logic = """
            expandable_keys = []
            fixed_keys = []
            for key, col in table.columns.items():
                label_str = col.label.plain
                if label_str in text_cols or label_str.startswith("Cat"):
                    expandable_keys.append(key)
                else:
                    fixed_keys.append(key)

            if not expandable_keys:
                expandable_keys = list(table.columns.keys())
                fixed_keys = []
"""

new_logic = """
            # User Steering: Expand ALL columns to fix maximum space instead of pushing to the right.
            expandable_keys = list(table.columns.keys())
            fixed_keys = []
"""

if old_logic.strip() in content:
    content = content.replace(old_logic.strip(), new_logic.strip())
else:
    print("Could not find old logic exactly")

with open("toggl/tui.py", "w") as f:
    f.write(content)
