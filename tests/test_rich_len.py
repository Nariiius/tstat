from rich.text import Text

s1 = "[#ff5f5f]-12.4[/]"
s2 = "[b]Hello[/]"
s3 = "Plain text"

print(len(Text.from_markup(s1).plain))
print(Text.from_markup(s1).cell_len)
