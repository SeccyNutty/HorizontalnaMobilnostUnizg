"""Stage 5: verify the built page.
 A) live sample: re-fetch N course pages from ISVU WITHOUT cache, compare name / ECTS / description / language,
    check the stored ISVU link resolves, and compare semesters with the page's own 'Predmet u nastavnom programu' table.
 B) embedded data: decode the HTML data block and compare with courses.json.
 C) search: run the page's own normalisation + stemmer (extracted from the HTML) in Node on the real data.
Writes verification_report.md into the workdir; exits 1 if a hard check fails."""
import argparse, base64, gzip, json, os, random, re, subprocess, sys, unicodedata
from common import ROOT, BASE, get, workdir, jload, add_common_args
from s3_details import parse_detail

p = add_common_args(argparse.ArgumentParser())
p.add_argument("--out", default="/mnt/user-data/outputs/kolegiji-unizg.html")
p.add_argument("--sample", type=int, default=25)
p.add_argument("--seed", type=int, default=None)
p.add_argument("--queries", default="poduzetništvo|poduzetnički,robotika|robotski,informatika|informatički,politika|politički,tehnika|tehnički,fizika|fizički,matematika|matematički,ekonomija|ekonomski,financije|financijski")
a = p.parse_args()
wd = workdir(a)
rng = random.Random(a.seed)
courses = jload(wd, "courses.json")
insts = {v[0]: v[1] for v in jload(wd, "institutions.json")}
rep, hard_fail = [], False


def n(s):
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def log(line=""):
    print(line, flush=True)
    rep.append(line)


# ---------- A: live sample ----------
by_vu = {}
for c in courses:
    by_vu.setdefault(c["vu"], []).append(c)
vus = rng.sample(sorted(by_vu), min(a.sample, len(by_vu)))
sample = [rng.choice(by_vu[v]) for v in vus]
while len(sample) < a.sample:
    sample.append(rng.choice(courses))

log(f"# Provjera podataka prema ISVU-u\n\n## A) Uzorak od {len(sample)} kolegija, dohvaćeno uživo (bez keša)\n")
log("| Sastavnica | Kolegij | Naziv | ECTS | Opis | Jezik | Link | Semestri |")
log("|---|---|---|---|---|---|---|---|")
ok_count, sem_warn = 0, 0
for c in sample:
    url = f"{BASE}/{c['vu']}/akademskagodina/{a.year}/predmet/{c['u'][0]}/razina/{c['u'][1]}/izvedba/{c['u'][2]}/smjer/{c['u'][3]}"
    h = get(url, wd, use_cache=False)
    if not h:
        log(f"| {insts[c['vu']]} | {c['name']} | – | – | – | – | NE RADI | – |")
        hard_fail = True
        continue
    d = parse_detail(h)
    live_desc = d.get("Opis predmeta") or (d.get("Ishodi učenja") if c["dk"] else "") or ""
    chk = {
        "name": n(d.get("naziv")) == n(c["name"]),
        "ects": abs(float((d.get("ECTS bodovi") or "0").replace(",", ".")) - c["e"]) < 1e-6,
        "desc": n(live_desc)[:300] == n(c["desc"])[:300],
        "lang": ", ".join(d.get("Jezici izvođenja nastave") or []) == c["langs"],
        "link": True,
    }
    # ISVU table: "izborni *" = not taught in that semester; skip levels we do not include.
    live_sems = {int(r[3]) for r in d.get("np", []) if len(r) >= 5 and r[3].isdigit() and "*" not in r[4]
                 and not re.search(r"doktor|specijal|poslijedipl|cjeloživot", r[2], re.I)}
    ours = set(c["sems"])
    missing, extra = live_sems - ours, ours - live_sems
    if not live_sems or ours == live_sems:
        sem_txt = "✓"
    elif not missing:
        sem_txt = f"✓ (+{sorted(extra)}: višesemestralni)"   # e.g. "Harmonija B1 (1/2)", "(2/2)"
    else:
        sem_warn += 1
        sem_txt = f"⚠ nedostaje {sorted(missing)}"
    if all(chk.values()):
        ok_count += 1
    else:
        hard_fail = hard_fail or not (chk["name"] and chk["ects"] and chk["desc"])
    mk = lambda b: "✓" if b else "✗"
    log(f"| {insts[c['vu']][:40]} | [{c['name'][:45]}]({url}) | {mk(chk['name'])} | {mk(chk['ects'])} | "
        f"{mk(chk['desc'])} | {mk(chk['lang'])} | ✓ | {sem_txt} |")
log(f"\nPotpuno podudaranje: {ok_count}/{len(sample)}. Kolegija kojima nedostaje semestar naveden na stranici kolegija: {sem_warn}.\n")

# ---------- B: embedded data ----------
html = open(a.out, encoding="utf-8").read()
m = re.search(r'<script id="data" type="application/octet-stream">(.*?)</script>', html, re.S)
data = json.loads(gzip.decompress(base64.b64decode(m.group(1).strip())))
emb_ok = len(data["c"]) == len(courses) and all(
    data["c"][i][0] == courses[i]["name"] and data["c"][i][2] == courses[i]["e"] for i in range(len(courses)))
log(f"## B) Ugrađeni podaci\n\n{len(data['c'])} kolegija u stranici, {len(courses)} u courses.json: {'✓ podudara se' if emb_ok else '✗ RAZLIKA'}. "
    f"Veličina HTML-a {len(html.encode())/1e6:.1f} MB.\n")
hard_fail = hard_fail or not emb_ok

# ---------- C: search behaviour (page's own JS) ----------
core = re.search(r"// @@core-start(.*?)// @@core-end", html, re.S).group(1)
dpath = os.path.join(wd, "_search_test_data.json")
json.dump([[r[0], r[5]] for r in data["c"]], open(dpath, "w", encoding="utf-8"), ensure_ascii=False)
js = core + r"""
const fs = require("fs");
const docs = JSON.parse(fs.readFileSync(process.argv[2], "utf8")).map(([n,d]) => new Set((norm(n)+" "+norm(d||"")).match(WORD)||[]));
function count(q){ const qs = parseQuery(q); return docs.filter(ws => qs.every(qt => [...ws].some(w => tokMatch(w, qt)))).length; }
const out = {};
for (const pair of process.argv[3].split(",")) {
  const forms = pair.split("|");
  out[pair] = forms.map(f => ({f, stem: parseQuery(f).map(x=>x.s).join(" "), n: count(f)}));
  const f0 = forms[0]; const plain = f0.normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/đ/g,"d");
  out[pair].push({f: plain + " (bez dijakritika)", stem: parseQuery(plain).map(x=>x.s).join(" "), n: count(plain)});
}
console.log(JSON.stringify(out));
"""
jsf = os.path.join(wd, "_search_test.js")
open(jsf, "w").write(js)
r = subprocess.run(["node", jsf, dpath, a.queries], capture_output=True, text=True)
log("## C) Pretraga (logika iz same stranice, na stvarnim podacima)\n")
if r.returncode:
    log("✗ Node test nije uspio: " + r.stderr[:500]); hard_fail = True
else:
    for pair, rows in json.loads(r.stdout).items():
        same = len({x["stem"] for x in rows}) == 1 and len({x["n"] for x in rows}) == 1
        log(f"- {'✓' if same else '⚠'} " + "; ".join(f"„{x['f']}” → korijen `{x['stem']}`, {x['n']} kolegija" for x in rows))
        if not same and pair == a.queries.split(",")[0]:
            hard_fail = True

open(os.path.join(wd, "verification_report.md"), "w", encoding="utf-8").write("\n".join(rep))
log(f"\n[s5] {'NEUSPJEH' if hard_fail else 'USPJEH'} – izvještaj: {os.path.join(wd, 'verification_report.md')}")
sys.exit(1 if hard_fail else 0)
