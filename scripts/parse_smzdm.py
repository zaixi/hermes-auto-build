#!/usr/bin/env python3
import json, sys

data = json.loads(sys.stdin.read())
snap = data.get("snapshot", "")
lines = snap.split("\n")

for i, line in enumerate(lines):
    l = line.strip()
    if "link" not in l:
        continue
    if "元" in l or "http" in l or len(l) < 20 or len(l) > 150:
        continue
    clean = l.replace('"', '').replace('[', '').replace(']', '').strip()
    if not any(x in clean for x in ["iPhone", "苹果", "Apple", "手机"]):
        continue
    for j in range(i+1, min(i+5, len(lines))):
        p = lines[j].strip()
        if "link" in p and "元" in p:
            price = p.replace('"', '').replace('[', '').replace(']', '').strip()[:60]
            print(clean[:80])
            print("  " + price)
            print()
            break
