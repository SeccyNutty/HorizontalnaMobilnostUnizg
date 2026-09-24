"""Stage 1: list all institutions whose parent is the given university -> institutions.json"""
import argparse, re, html
from common import BASE, get, workdir, jdump, add_common_args

p = add_common_args(argparse.ArgumentParser())
p.add_argument("--university", default="Sveučilište u Zagrebu")
a = p.parse_args()
wd = workdir(a)

h = get("https://www.isvu.hr/visokaucilista/hr/pretrazivanje", wd)
rows = re.findall(r'href="/visokaucilista/hr/podaci/(\d+)"[^>]*>(.*?)</a>\s*</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>', h, re.S)
out = []
for vid, name, parent, city in rows:
    name, parent = html.unescape(name.strip()), html.unescape(parent.strip())
    if parent == a.university or (name == a.university and not parent):
        out.append([int(vid), name, parent, city.strip()])
jdump(out, wd, "institutions.json")
print(f"[s1] {len(out)} sastavnica ({a.university})", flush=True)
for r in out:
    print("   ", r[0], r[1])
