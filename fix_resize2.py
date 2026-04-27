import re

with open("toggl/tui.py", "r") as f:
    content = f.read()

# First replace _resize_tables with the old correct logic minus the scrolling bug
with open("/tmp/old_resize.py", "r") as f:
    old_resize = f.read()

# Clean up scroll_to calls from old_resize
old_resize_clean = re.sub(r'\s+table\.scroll_to\(x=0, animate=False\)', '', old_resize)

# Replace the gutted _resize_tables
content = re.sub(r'    def _resize_tables\(self\):\n        self\.update_sparkbar_visibility\(\)\n', old_resize_clean + '\n', content)

# Re-add _schedule_resize to action_toggle_sparkbar
content = re.sub(
    r'(    def action_toggle_sparkbar\(self\):\n(?:.*\n){7}        self\.update_sparkbar_visibility\(\)\n)',
    r'\1        self._schedule_resize()\n',
    content
)

# Re-add _schedule_resize to refresh_all_views
content = re.sub(
    r'(    def refresh_all_views\(self\):\n(?:.*\n){7}        self\.update_sparkbar_visibility\(\)\n)',
    r'\1        self._schedule_resize()\n',
    content
)

with open("toggl/tui.py", "w") as f:
    f.write(content)
