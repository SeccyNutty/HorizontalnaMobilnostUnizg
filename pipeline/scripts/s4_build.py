"""Stage 4: merge occurrences + details into one record per course, embed (gzip+base64) into the HTML template."""
import argparse, base64, collections, datetime, gzip, hashlib, json, os, re
from common import EXCLUDED_LEVELS, workdir, jload, jdump, add_common_args

HERE = os.path.dirname(os.path.abspath(__file__))
p = add_common_args(argparse.ArgumentParser())
p.add_argument("--out", default="/mnt/user-data/outputs/kolegiji-unizg.html")
a = p.parse_args()
wd = workdir(a)

insts = {v[0]: v[1] for v in jload(wd, "institutions.json")}
occ = [o for o in jload(wd, "occurrences.json") if o["raz"] not in EXCLUDED_LEVELS]
det = jload(wd, "details.json")
# Descriptions from faculty websites (stage 3b), used only where ISVU has no "Opis predmeta".
ext = jload(wd, "external.json") if os.path.exists(os.path.join(wd, "external.json")) else {"sources": {}, "c": {}}
SRC = list(ext["sources"])

DISPLAY = {37: "PMF – Matematički odsjek", 119: "PMF – prirodoslovni odsjeci",
           9996: "Sveučilište u Zagrebu (sveučilišni studiji)", 251: "Sveučilišni centar za protestantsku teologiju"}
AREAS = ["Prirodne znanosti", "Tehničke znanosti", "Biomedicina i zdravstvo", "Biotehničke znanosti",
         "Društvene znanosti", "Humanističke znanosti", "Umjetničko područje", "Interdisciplinarno"]
# Area is assigned per institution (ISVU has no field-of-science per course).
AREA_OF = {37: 0, 119: 0,
           54: 1, 36: 1, 125: 1, 135: 1, 120: 1, 7: 1, 160: 1, 82: 1, 128: 1, 124: 1, 195: 1, 117: 1,
           108: 2, 65: 2, 6: 2, 53: 2, 374: 2,
           178: 3, 68: 3, 58: 3,
           13: 4, 67: 4, 16: 4, 15: 4, 34: 4, 66: 4, 131: 4,
           130: 5, 2225: 5, 2223: 5, 203: 5, 251: 5,
           1053: 6, 381: 6, 1349: 6,
           9996: 7, 9950: 7}
LEVELS = {3: "Sveučilišni prijediplomski", 4: "Sveučilišni diplomski", 5: "Integrirani prijediplomski i diplomski",
          8: "Stručni prijediplomski", 6: "Stručni diplomski", 9: "Stručni kratki", 1: "Dodiplomski (stari program)"}
LV_ORDER = [3, 4, 5, 8, 6, 9, 1]
LV_SHORT = {3: "prijediplomski", 4: "diplomski", 5: "integrirani", 8: "stručni prijediplomski",
            6: "stručni diplomski", 9: "stručni kratki", 1: "dodiplomski"}
unknown_lv = {o["raz"] for o in occ} - set(LV_ORDER)
unknown_vu = set(insts) - set(AREA_OF)
if unknown_lv or unknown_vu:
    print(f"[s4] UPOZORENJE: nepoznate razine {unknown_lv} / sastavnice bez područja {unknown_vu} -> 'Interdisciplinarno'", flush=True)
    for r in unknown_lv:
        LV_ORDER.append(r); LEVELS[r] = f"Razina {r}"; LV_SHORT[r] = f"razina {r}"


def clean(t):
    if not t:
        return ""
    t = re.sub(r"[ \t]+\n", "\n", t.replace("\r", ""))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def fnum(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


by = collections.defaultdict(list)
for o in occ:
    by[(o["vu"], o["pid"])].append(o)

recs = []
for (vu, pid), os_ in by.items():
    d = det.get(f"{vu}:{pid}") or {}
    name = re.sub(r"\s+", " ", (d.get("naziv") or os_[0]["name"])).strip()
    e = fnum(d.get("ECTS bodovi"))
    if e is None:
        e = fnum(os_[0]["ects"]) or 0.0
    desc, dk, x = clean(d.get("Opis predmeta")), 0, 0
    xe = ext["c"].get(f"{vu}:{pid}")
    if not desc and xe:
        desc, dk = clean(xe["t"]), 2
        x = [SRC.index(xe["s"]), xe["u"], xe.get("y", "")]
    if not desc:
        desc = clean(d.get("Ishodi učenja"))
        dk = int(bool(desc))
    progs = list(dict.fromkeys(
        f'{o["smname"]} ({LV_SHORT[o["raz"]]}{", izvanredni" if o["izv"] == "I" else ""})'
        for o in sorted(os_, key=lambda o: (LV_ORDER.index(o["raz"]), o["smname"]))))
    ref = sorted(os_, key=lambda o: (o["izv"] != "R", o["raz"], o["sm"]))[0]
    recs.append(dict(vu=vu, pid=pid, name=name, e=e, desc=desc, dk=dk, progs=progs, ok=bool(d),
                     lv=sorted({o["raz"] for o in os_}, key=LV_ORDER.index), sems=sorted({o["sem"] for o in os_}),
                     langs=", ".join(x for x in (d.get("Jezici izvođenja nastave") or []) if x),
                     u=[pid, ref["raz"], ref["izv"], ref["sm"]], x=x))

# Same course under different codes at one institution (identical name, ECTS and description) -> merge.
groups = collections.defaultdict(list)
for r in recs:
    dh = hashlib.md5(r["desc"].encode()).hexdigest() if r["desc"] else f"nodesc{r['pid']}"
    groups[(r["vu"], r["name"].lower(), r["e"], dh)].append(r)
merged, n_merged = [], 0
for g in groups.values():
    r = dict(g[0])
    if len(g) > 1:
        n_merged += len(g) - 1
        r["lv"] = sorted({x for q in g for x in q["lv"]}, key=LV_ORDER.index)
        r["sems"] = sorted({x for q in g for x in q["sems"]})
        r["progs"] = list(dict.fromkeys(pp for q in g for pp in q["progs"]))
        r["langs"] = r["langs"] or next((q["langs"] for q in g if q["langs"]), "")
        r["alt_pids"] = [q["pid"] for q in g[1:]]
    merged.append(r)

vu_used = sorted({r["vu"] for r in merged}, key=lambda v: DISPLAY.get(v, insts[v]))
fidx = {v: i for i, v in enumerate(vu_used)}
lv_used = [l for l in LV_ORDER if any(l in r["lv"] for r in merged)]
lidx = {l: i for i, l in enumerate(lv_used)}
data = {"year": a.year, "areas": AREAS, "src": [ext["sources"][k] for k in SRC], "levels": [LEVELS[l] for l in lv_used],
        "fac": [[v, DISPLAY.get(v, insts[v]), AREA_OF.get(v, 7)] for v in vu_used],
        "c": [[r["name"], fidx[r["vu"]], r["e"], [lidx[x] for x in r["lv"]], r["sems"], r["desc"], r["dk"],
               r["u"], r["langs"], r["progs"], r["x"]] for r in merged]}
raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
b64 = base64.b64encode(gzip.compress(raw, 9)).decode()
jdump(merged, wd, "courses.json")

tpl = open(os.path.join(HERE, "..", "assets", "template.html"), encoding="utf-8").read()
today = datetime.date.today()
html = (tpl.replace("__DATA__", b64).replace("__DATE__", f"{today.day}. {today.month}. {today.year}.")
        .replace("__YEARLABEL__", f"{a.year}./{a.year + 1}."))
os.makedirs(os.path.dirname(a.out), exist_ok=True)
open(a.out, "w", encoding="utf-8").write(html)
size = len(html.encode()) / 1e6
print(f"[s4] kolegija: {len(merged)} (spojeno istih pod drugom šifrom: {n_merged})", flush=True)
print(f"[s4] bez detalja: {sum(not r['ok'] for r in merged)}, bez opisa: {sum(not r['desc'] for r in merged)}, "
      f"ishodi umjesto opisa: {sum(r['dk'] == 1 for r in merged)}, opis sa stranice fakulteta: {sum(r['dk'] == 2 for r in merged)}", flush=True)
print(f"[s4] podaci {len(raw)/1e6:.1f} MB -> HTML {size:.1f} MB: {a.out}", flush=True)
if size > 15.5:
    print("[s4] UPOZORENJE: HTML je blizu granice od 16 MB za objavu kao artefakt.", flush=True)
