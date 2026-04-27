import re

with open("toggl/tui.py", "r") as f:
    content = f.read()

# Fix 1: Loading all tabs instead of `display: none`
# Wait, let's read how update_view_visibility works first.
