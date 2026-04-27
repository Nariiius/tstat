import re

with open("toggl/tui.py", "r") as f:
    content = f.read()

# I messed up the regex replace and now have a duplicated block.
# Let's cleanly replace the entire _resize_tables method using python.

import ast

tree = ast.parse(content)
start_line = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == '_resize_tables':
        start_line = node.lineno - 1
        break

if start_line is not None:
    lines = content.split('\n')
    
    with open('/tmp/old_resize.py', 'r') as f:
        old_resize_code = f.read().split('\n')
    
    # modify old resize code to remove scroll_to
    cleaned_resize = []
    for line in old_resize_code:
        if "table.scroll_to(x=0, animate=False)" not in line:
            cleaned_resize.append(line)
            
    # we need to find the end of the duplicated resize block
    # the duplicate block ends at the end of the file. No, it doesn't.
