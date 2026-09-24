"""Stage 3b: course descriptions from faculty websites, for courses whose ISVU entry has no "Opis predmeta".

Every adapter returns {isvu_course_id: {"t": text, "u": source_url, "n": name_at_source, "e": ects_at_source}}.
Only sources that publish the ISVU course code are used, so matching is by code, never by name.
A faculty that is unreachable or changed its site is skipped with a warning; it never breaks the build.

Output: external.json = {"sources": {key: label}, "c": {"vu:pid": {..., "s": key}}}, plus external_report.md.
"""
import argparse, hashlib, io, json, os, re, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from common import S, get, workdir, jload, jdump, add_common_args

MAX_LEN = 2500
LIMIT = int(os.environ.get("S3B_LIMIT", "0"))  # testing: only the first N items per source  # characters per description (page size stays well under the 16 MB artifact limit)


# ---------------------------------------------------------------- helpers
def fetch(url, wd, binary=False, data=None, tries=3, timeout=90):
    """Cached GET/POST for faculty sites. Returns text/bytes or None."""
    key = url + ("|" + json.dumps(data, sort_keys=True) if data else "")
    fn = os.path.join(wd, "cache", "x_" + hashlib.md5(key.encode()).hexdigest())
    if os.path.exists(fn):
        b = open(fn, "rb").read()
        return b if binary else b.decode("utf-8", "replace")
    for t in range(tries):
        try:
            r = S.post(url, data=data, timeout=timeout) if data else S.get(url, timeout=timeout)
            if r.status_code == 200:
                open(fn, "wb").write(r.content)
                return r.content if binary else r.content.decode(r.encoding or "utf-8", "replace")
            if r.status_code in (403, 404, 410):
                return None
        except Exception:
            pass
        time.sleep(3 * (t + 1))
    return None


def txt(el):
    """Readable text from an HTML fragment: list items become '- ' lines, paragraphs are kept."""
    if el is None:
        return ""
    for li in el.find_all("li"):
        li.insert(0, "\n- ")
    for br in el.find_all("br"):
        br.replace_with("\n")
    for p in el.find_all(["p", "div", "tr"]):
        p.insert_after("\n")
    return tidy(el.get_text(""))


def tidy(s):
    s = (s or "").replace("\r", "").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n+(?=- )", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def unwrap(s):
    """Join PDF line wraps: a line continues the previous one unless it starts a list item."""
    out = []
    for l in (s or "").split("\n"):
        l = l.strip()
        if not l:
            continue
        if out and not re.match(r"^([-•–*]|\d{1,2}[.)]|[a-z][.)] )", l) and not out[-1].endswith(":"):
            out[-1] += " " + l
        else:
            out.append(l)
    return "\n".join(out)


KIF_LEAK = re.compile(r"^(učenja na razini|na razini|predmeta|detaljno razrađen|prema satnici|nastave|razini programa)$", re.I)


def compose(parts):
    """[(heading, text)] -> one description, capped at MAX_LEN on a line boundary."""
    out = "\n\n".join(f"{h}:\n{t}" if h else t for h, t in parts if t and len(t) > 3)
    if len(out) > MAX_LEN:
        cut = out[:MAX_LEN]
        out = cut[:max(cut.rfind("\n"), MAX_LEN - 300)].rstrip() + " …"
    return out


def num(x):
    try:
        return float(str(x).replace(",", ".").split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def pmap(fn, items, threads):
    with ThreadPoolExecutor(threads) as ex:
        return list(ex.map(fn, items))


# ---------------------------------------------------------------- Filozofski (130): ECTS katalog
FF = "https://thetha.ffzg.hr"


def ffzg(wd, year, threads):
    studies = set()
    for kind in ("Trenutni", "Reformirani"):
        for r in (3, 4, 5):
            h = fetch(f"{FF}/ECTS/Studij/{kind}?razinaStudijaID={r}", wd)
            if h:
                studies |= set(re.findall(r'/ECTS/Studij/Index/(\d+)', h))
    if not studies:
        raise RuntimeError("nema popisa studija")
    courses = set()
    for h in pmap(lambda s: fetch(f"{FF}/ECTS/Studij/Index/{s}", wd), sorted(studies)[:LIMIT or None], threads):
        courses |= set(re.findall(r'/ECTS/Predmet/Index/(\d+)', h or ""))
    print(f"[s3b] ffzg: {len(studies)} studija, {len(courses)} kolegija u katalogu", flush=True)

    def one(cid):
        url = f"{FF}/ECTS/Predmet/Index/{cid}"
        h = fetch(url, wd)
        if not h:
            return None
        s = BeautifulSoup(h, "html.parser")
        dl = {dt.get_text(" ", strip=True): dt.find_next_sibling("dd") for dt in s.select("dl dt")}
        code = dl.get("Šifra")
        code = code.get_text(strip=True) if code else ""
        if not code.isdigit():
            return None
        panels = {}
        for p in s.select("div.panel"):
            t = p.select_one(".panel-title")
            if t:
                panels.setdefault(t.get_text(" ", strip=True), p.select_one(".panel-body"))
        d = compose([("Cilj", txt(panels.get("Cilj"))), ("Sadržaj", txt(panels.get("Sadržaj"))),
                     ("Ishodi učenja", txt(panels.get("Ishodi učenja")))])
        name = dl.get("Naziv")
        return int(code), dict(t=d, u=url, n=name.get_text(" ", strip=True) if name else "",
                               e=num(dl["ECTS"].get_text(strip=True)) if dl.get("ECTS") else None)

    return {k: v for k, v in filter(None, pmap(one, sorted(courses, key=int), threads)) if v["t"]}


# ---------------------------------------------------------------- FER (36): /predmet/{kratica}, year via AJAX
FER = "https://www.fer.unizg.hr"


def fer(wd, year, threads):
    h = fetch(f"{FER}/predmet", wd)
    slugs = sorted(set(re.findall(r'href="(?:https://www\.fer\.unizg\.hr)?/predmet/([a-z0-9_]+)"', h or "")))
    if not slugs:
        raise RuntimeError("nema popisa predmeta")
    print(f"[s3b] fer: {len(slugs)} predmeta na popisu", flush=True)

    def one(slug):
        url = f"{FER}/predmet/{slug}"
        page = fetch(url, wd)
        if not page:
            return []
        m = re.search(r'ajax_call_async\("([^"]+)",\s*"([^"]+)",\s*data', page)
        if not m or "Opis kolegija" not in page:
            return []   # redirect stub or page without course detail
        frag = fetch(f"{FER}/jsxr.php/predmet/{slug}", wd, data={"json": json.dumps(
            {"_method": "_obj_call_", "_func": m.group(1), "_dataEncoded": m.group(2), "data": {"academicYear": str(year)}})})
        try:
            frag = json.loads(frag)
        except (TypeError, ValueError):
            return []
        if not isinstance(frag, str) or f'value="{year}" selected' not in frag:
            return []   # course not offered in the requested year
        s = BeautifulSoup(frag, "html.parser")
        sec = {}
        for h4 in s.find_all("h4"):
            c = h4.find_next_sibling("div", class_="content") or h4.find_next("div", class_="content")
            sec.setdefault(h4.get_text(" ", strip=True), c)
        d = compose([("", txt(sec.get("Opis kolegija"))), ("Ishodi učenja", txt(sec.get("Ishodi učenja")))])
        flat = s.get_text(" | ", strip=True)
        iz = flat[flat.rfind("Izvedba"):] if "Izvedba" in flat else ""
        ids = [int(x) for x in re.findall(r"\| (?:HR|EN) \| (\d{5,7}) \|", iz)]
        ects = re.search(r"\| ([\d.,]+) \| ECTS \|", iz)
        name = re.search(r"<title>\s*([^<|]+?)\s*(?:[|-][^<]*)?</title>", page)
        rec = dict(t=d, u=url, n=name.group(1).strip() if name else "", e=num(ects.group(1)) if ects else None)
        return [(i, rec) for i in ids] if d else []

    return {k: v for lst in pmap(one, slugs[:LIMIT or None], threads) for k, v in lst}


# ---------------------------------------------------------------- Kineziološki (34): PDF "Izvedbeni plan"
KIF = "https://www.kif.unizg.hr/_download/repository/"
# Newest published plans. KIF does not link them from a stable page, so they are listed here; add new ones at the top.
KIF_PDFS = [
    ("PRIJEDLOG_IZVEDBENI PLAN I PROGRAM RPSSIT I IPSSIT za ak. god. 2025-26[1].pdf", "2025./2026."),
    ("Izvedbeni plan IPDSSK[1].pdf", "2023./2024."),
    ("Prijedlog izvedbeni.pdf", "2023./2024."),
]
KIF_LABELS = [("ciljevi predmeta", "Ciljevi"), ("očekivani ishodi", "Ishodi učenja"), ("sadržaj predmeta", "Sadržaj")]
KIF_STOP = re.compile(r"^(nositelj|kancelarija|konzultacije|e-mail|telefon|studijski|semestar|uvjeti|predmeta$|mjesto|način|nastave$|"
                      r"ishodi učenja na|razini programa|kojima predmet|pridonosi|obveze|praćenje|obvezna|dopunska|ostale|"
                      r"izvedbeni sati|kvalitete)", re.I)


def kif(wd, year, threads):
    import pdfplumber
    out = {}
    for fname, ylabel in KIF_PDFS:
        url = KIF + quote(fname)
        b = fetch(url, wd, binary=True, timeout=240)
        if not b:
            print(f"[s3b] kif: nedostupan {fname}", flush=True)
            continue
        cur, field, acc, n = None, None, {}, 0

        def flush():
            if cur and cur[0] not in out:
                d = compose([(lab, unwrap("\n".join(l for l in "\n".join(acc.get(lab, [])).split("\n")
                                                   if not KIF_LEAK.match(l.strip())))) for _, lab in KIF_LABELS])
                if d:
                    out[cur[0]] = dict(t=d, u=url, n=cur[1].capitalize(), e=acc.get("_e"), y=ylabel)

        with pdfplumber.open(io.BytesIO(b)) as pdf:
            for page in pdf.pages:
                top = (page.extract_text() or "").strip().split("\n")[0].strip()
                m = re.match(r"^(.{3,120}?)\s*\((\d{5,7})\)\s*$", top)
                if m and int(m.group(2)) != (cur or [0])[0]:
                    flush()
                    cur, field, acc = (int(m.group(2)), m.group(1)), None, {}
                    n += 1
                if not cur:
                    continue
                for tab in page.extract_tables():
                    for row in tab:
                        cells = [tidy(c) for c in row if c and tidy(c)]
                        if not cells:
                            continue
                        head = cells[0].replace("\n", " ").lower()
                        lab = next((l for k, l in KIF_LABELS if head.startswith(k)), None)
                        if lab:
                            field, cells = lab, cells[1:]
                        elif KIF_STOP.match(head):
                            field = None
                            e = re.search(r"([\d.,]+)\s*ECTS", " ".join(cells))
                            if e and "_e" not in acc:
                                acc["_e"] = num(e.group(1))
                            continue
                        elif len(cells) > 1 and field:
                            continue   # multi-column row inside a field (assessment tables etc.)
                        if field and cells:
                            acc.setdefault(field, []).append(max(cells, key=len))
            flush()
        print(f"[s3b] kif: {fname}: {n} kolegija", flush=True)
    return out


# ---------------------------------------------------------------- Agronomski (178): /hr/course/{n}, "Naziv (šifra)"
AGR = "https://www.agr.unizg.hr/hr/course/"


def agr(wd, year, threads, max_id=3000, gap=150):
    if fetch(AGR + "1", wd) is None and fetch(AGR + "899", wd) is None:
        raise RuntimeError("stranica nedostupna")
    out, last_hit, i = {}, 0, 0

    def one(n):
        h = fetch(AGR + str(n), wd)
        if not h:
            return n, None
        s = BeautifulSoup(h, "html.parser")
        title = next((t.get_text(" ", strip=True) for t in s.find_all(["h1", "h2", "title"])
                      if re.search(r"\(\d{5,7}\)", t.get_text())), "")
        m = re.search(r"^(.*?)\s*\((\d{5,7})\)", title)
        if not m:
            return n, None
        main = s.find("main") or s.find(id="content") or s.body
        sec, curh = {}, None
        for el in main.find_all(["h2", "h3", "h4", "h5", "strong", "p", "ul", "ol", "div"], recursive=True):
            if el.name in ("h2", "h3", "h4", "h5") or (el.name == "strong" and len(el.get_text(strip=True)) < 60):
                curh = el.get_text(" ", strip=True).rstrip(":")
            elif curh and el.name in ("p", "ul", "ol") and not el.find_parent(["ul", "ol"]):
                sec.setdefault(curh, []).append(txt(el))
        pick = lambda *ks: tidy("\n".join(next((v for k, v in sec.items() if any(x in k.lower() for x in ks)), [])))
        d = compose([("Opis", pick("opis", "cilj")), ("Sadržaj", pick("sadržaj")), ("Ishodi učenja", pick("ishodi"))])
        e = re.search(r"ECTS[^0-9]{0,20}([\d.,]+)", main.get_text(" "))
        return n, (int(m.group(2)), dict(t=d, u=AGR + str(n), n=m.group(1), e=num(e.group(1)) if e else None))

    while i < max_id and i - last_hit < gap:
        batch = list(range(i + 1, i + 1 + 50))
        for n, r in pmap(one, batch, threads):
            if r:
                last_hit = max(last_hit, n)
                if r[1]["t"]:
                    out.setdefault(r[0], r[1])
        i += 50
    return out


# ---------------------------------------------------------------- Pravni (66): {šifra}-NTJ.pdf / -IUK.pdf (WordPress media)
PRAVO = "https://www.pravo.unizg.hr"


def pravo(wd, year, threads, targets=()):
    """Files are named by ISVU code; found via the WordPress media search API."""
    media = {}
    for q in ("NTJ", "IUK"):
        for pg in range(1, 60):
            h = fetch(f"{PRAVO}/wp-json/wp/v2/media?search={q}&per_page=100&page={pg}&_fields=source_url,date", wd)
            try:
                items = json.loads(h) if h else []
            except ValueError:
                items = []
            if not isinstance(items, list) or not items:
                break
            for it in items:
                m = re.search(r"/(\d{5,7})-(NTJ|IUK)[^/]*\.pdf$", it.get("source_url", ""), re.I)
                if m:
                    k = (int(m.group(1)), m.group(2).upper())
                    if k not in media or it["date"] > media[k][1]:
                        media[k] = (it["source_url"], it["date"])
    if not media:
        raise RuntimeError("nema PDF-ova (API nedostupan?)")
    import pdfplumber
    out = {}

    def one(code):
        parts, src, name = [], None, ""
        for kind, lab in (("NTJ", "Nastavne teme"), ("IUK", "Ishodi učenja")):
            if (code, kind) not in media:
                continue
            url = media[(code, kind)][0]
            b = fetch(url, wd, binary=True)
            if not b:
                continue
            items = []
            try:
                with pdfplumber.open(io.BytesIO(b)) as pdf:
                    for page in pdf.pages:
                        for tab in page.extract_tables():
                            for row in tab:
                                c0 = tidy(row[0] or "")
                                m = re.search(r"Naziv kolegija:\s*(.+)", c0)
                                if m and not name:
                                    name = m.group(1).split("\n")[0].strip()
                                m = re.match(r"^\d+\.\s*Naziv nastavne teme/jedinice:\s*(.+)$", c0, re.S)
                                if kind == "NTJ" and m:
                                    items.append(m.group(1))
                                elif kind == "IUK" and c0.upper() == "ISHOD UČENJA" and len(row) > 1 and row[1]:
                                    items.append(tidy(row[1]))
            except Exception:
                continue
            if items:
                src = src or url
                parts.append((lab, "\n".join("- " + re.sub(r"\s+", " ", i).strip() for i in dict.fromkeys(items))))
        d = compose(parts)
        return (code, dict(t=d, u=src, n=name, e=None)) if d else None

    codes = sorted({c for c, _ in media if not targets or c in targets})
    return dict(filter(None, pmap(one, codes, threads)))


# ---------------------------------------------------------------- registry
ADAPTERS = {  # key: (vu, label shown on the page, function)
    "ffzg": (130, "ECTS katalog Filozofskog fakulteta", ffzg),
    "fer": (36, "stranica predmeta na fer.unizg.hr", fer),
    "kif": (34, "Izvedbeni plan Kineziološkog fakulteta", kif),
    "agr": (178, "stranica predmeta na agr.unizg.hr", agr),
    "pravo": (66, "izvedbeni plan predmeta Pravnog fakulteta", pravo),
}

if __name__ == "__main__":
    p = add_common_args(argparse.ArgumentParser())
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--only", default="", help="npr. ffzg,fer")
    p.add_argument("--keep", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "external.json.gz"),
                   help="zadnji uspješni rezultat (u repou); koristi se za izvor koji je trenutno nedostupan")
    a = p.parse_args()
    wd = workdir(a)
    det = jload(wd, "details.json")
    need = {}   # vu -> {pid} of courses with no ISVU description
    for k, d in det.items():
        vu, pid = map(int, k.split(":"))
        if d and not (d.get("Opis predmeta") or "").strip():
            need.setdefault(vu, set()).add(pid)
    import gzip
    prev = json.load(gzip.open(a.keep, "rt", encoding="utf-8")) if os.path.exists(a.keep) else {"c": {}}
    res, rep = {}, ["# Opisi sa stranica fakulteta\n", "| Izvor | Bez opisa u ISVU | Pronađeno na izvoru | Popunjeno | Stanje |", "|---|---|---|---|---|"]
    for key, (vu, label, fn) in ADAPTERS.items():
        if a.only and key not in a.only.split(","):
            continue
        t0, tgt = time.time(), need.get(vu, set())
        try:
            got = fn(wd, a.year, a.threads, targets=tgt) if key == "pravo" else fn(wd, a.year, a.threads)
            state = "✓"
        except Exception as e:
            traceback.print_exc()
            # keep last successful result for this source rather than losing it
            got = {int(k.split(":")[1]): v for k, v in prev["c"].items() if v.get("s") == key}
            state = f"⚠ {type(e).__name__}: {e} (zadržani prethodni podaci: {len(got)})"
        hit = 0
        for pid, v in got.items():
            if pid in tgt:
                res[f"{vu}:{pid}"] = dict(v, s=key)
                hit += 1
        rep.append(f"| {label} | {len(tgt)} | {len(got)} | {hit} | {state} |")
        print(f"[s3b] {key}: izvor {len(got)}, popunjeno {hit}/{len(tgt)} ({time.time()-t0:.0f} s) {state}", flush=True)
    if a.only:   # partial run: keep the other sources from the last full result
        res = {**{k: v for k, v in prev["c"].items() if v.get("s") not in a.only.split(",")}, **res}
    out = {"sources": {k: v[1] for k, v in ADAPTERS.items()}, "c": dict(sorted(res.items()))}
    jdump(out, wd, "external.json")
    os.makedirs(os.path.dirname(a.keep), exist_ok=True)
    with gzip.open(a.keep, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(wd, "external_report.md"), "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print(f"[s3b] ukupno popunjeno: {len(res)}", flush=True)
