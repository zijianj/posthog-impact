#!/usr/bin/env python3
"""Inline data.json into template.html -> index.html (self-contained, no fetch)."""
import json
tpl = open("template.html").read()
data = json.load(open("data.json"))
html = tpl.replace("__DATA__", json.dumps(data))
open("index.html", "w").write(html)
print(f"Built index.html ({len(html)//1024} KB), {len(data['leaderboard'])} engineers embedded.")
