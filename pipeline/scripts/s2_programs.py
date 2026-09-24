"""Stage 2: for every institution walk level -> mode -> study tree -> curriculum page,
and record every course occurrence (course x study x semester) -> occurrences.json"""
import argparse, json, re, time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from common import BASE, get, workdir, jload, jdump, add_common_args

p = add_common_args(argparse.ArgumentParser())
p.add_argument("--threads", type=int, default=6)
a = p.parse_args()
wd, Y = workdir(a), a.year


def walk(nodes, out):
    for n in nodes:
        if n.get("imaNastavniProgram") == 1:
            out.append(n)
        walk(n.get("listaPodredjenihStudija") or [], out)


def parse_program(h):
    soup = BeautifulSoup(h, "html.parser")
    occ = []
    for pane in soup.select("div.tab-pane"):
        m = re.match(r"semestar(\d+)", pane.get("id", ""))
        if not m:
            continue
        for tr in pane.find_all("tr"):
            link = tr.find("a", href=re.compile(r"/predmet/\d+/"))
            if not link:
                continue
            ects = tr.find("td", attrs={"data-title": "ECTS"})
            occ.append(dict(pid=int(re.search(r"/predmet/(\d+)/", link["href"]).group(1)),
                            name=link.get_text(" ", strip=True), href=link["href"],
                            ects=ects.get_text(strip=True) if ects else None, sem=int(m.group(1)),
                            izborni=tr.find_parent("table", class_="panel") is not None))
    return occ


def jget(url):
    t = get(url, wd)
    return json.loads(t) if t else []


def crawl(vu):
    progs = []
    for r in jget(f"{BASE}/{vu}/dohvatirazine/{Y}"):
        for i in jget(f"{BASE}/{vu}/razina/{r['sifraRazine']}/dohvatiizvedbe/{Y}"):
            lst = []
            walk(jget(f"{BASE}/{vu}/razina/{r['sifraRazine']}/izvedba/{i['oznaka']}/akgodina/{Y}"), lst)
            progs += [(r["sifraRazine"], r["nazivRazineIVrste"], i["oznaka"], n["sifraSmjera"], n["nazivSmjera"]) for n in lst]

    def one(pr):
        rz, rzn, iz, sm, smn = pr
        h = get(f"{BASE}/{vu}/nastavniprogram/{Y}/razina/{rz}/izvedba/{iz}/smjer/{sm}", wd)
        o = parse_program(h) if h else []
        for x in o:
            x.update(vu=vu, raz=rz, razname=rzn, izv=iz, sm=sm, smname=smn)
        return o

    occ = []
    with ThreadPoolExecutor(a.threads) as ex:
        for o in ex.map(one, progs):
            occ += o
    return progs, occ


allocc, summary = [], []
for vu, name, *_ in jload(wd, "institutions.json"):
    t = time.time()
    progs, occ = crawl(vu)
    n = len({o["pid"] for o in occ})
    summary.append([vu, name, len(progs), n])
    print(f"[s2] {vu:>5} {name[:50]:<50} {len(progs):>4} programa {n:>5} predmeta ({time.time()-t:.0f}s)", flush=True)
    allocc += occ
jdump(allocc, wd, "occurrences.json")
jdump(summary, wd, "institution_summary.json")
empty = [s[1] for s in summary if s[3] == 0]
print(f"[s2] ukupno {len({(o['vu'], o['pid']) for o in allocc})} jedinstvenih predmeta; bez programa u ISVU-u: {', '.join(empty) or 'nema'}", flush=True)
