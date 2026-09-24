"""Stage 3: fetch the detail page of every unique course (institution, course id) -> details.json"""
import argparse, time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from common import ROOT, EXCLUDED_LEVELS, get, workdir, jload, jdump, add_common_args


def parse_detail(h):
    soup = BeautifulSoup(h, "html.parser")
    t = soup.select_one("div.card-header h2.card-title")
    d = {"naziv": t.get_text(" ", strip=True) if t else None}
    for dt in soup.select("dl.row > dt"):
        k = dt.get_text(" ", strip=True).rstrip(":").strip()
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        if k == "Predmet u nastavnom programu":
            d["np"] = [[td.get_text(" ", strip=True) for td in tr.find_all("td")][:5] for tr in dd.select("tbody tr")]
        elif k in ("Izvođači", "Jezici izvođenja nastave"):
            d[k] = [x.get_text(" ", strip=True) for x in dd.find_all("p")] or [dd.get_text(" ", strip=True)]
        else:
            d[k] = dd.get_text("\n").strip()
    return d


if __name__ == "__main__":
    p = add_common_args(argparse.ArgumentParser())
    p.add_argument("--threads", type=int, default=10)
    a = p.parse_args()
    wd = workdir(a)
    first = {}
    for o in jload(wd, "occurrences.json"):
        if o["raz"] not in EXCLUDED_LEVELS:
            first.setdefault((o["vu"], o["pid"]), o["href"])
    keys = list(first)
    print(f"[s3] {len(keys)} kolegija za dohvat detalja", flush=True)
    done, t0 = [0], time.time()

    def one(k):
        h = get(ROOT + first[k], wd)
        done[0] += 1
        if done[0] % 1000 == 0:
            rate = done[0] / (time.time() - t0)
            print(f"[s3] {done[0]}/{len(keys)}  ~{(len(keys)-done[0])/rate/60:.0f} min do kraja", flush=True)
        return k, (parse_detail(h) if h else None)

    res = {}
    with ThreadPoolExecutor(a.threads) as ex:
        for k, d in ex.map(one, keys):
            res[f"{k[0]}:{k[1]}"] = d
    jdump(res, wd, "details.json")
    print(f"[s3] gotovo, neuspjelih: {sum(v is None for v in res.values())}", flush=True)
