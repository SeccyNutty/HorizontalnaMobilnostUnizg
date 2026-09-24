"""Shared helpers: cached HTTP GET against ISVU, paths, constants."""
import hashlib, os, sys, time, json
import requests

ROOT = "https://www.isvu.hr"
BASE = ROOT + "/visokaucilista/hr/podaci"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (UNIZG course-search tool)"

# Doctoral (10) and postgraduate specialist (11) studies are not part of horizontal mobility.
EXCLUDED_LEVELS = {10, 11}


def workdir(args):
    wd = os.path.abspath(args.workdir)
    os.makedirs(os.path.join(wd, "cache"), exist_ok=True)
    return wd


def get(url, wd, tries=4, use_cache=True):
    """GET with on-disk cache. Returns text or None after retries."""
    fn = os.path.join(wd, "cache", hashlib.md5(url.encode()).hexdigest())
    if use_cache and os.path.exists(fn):
        return open(fn, encoding="utf-8").read()
    for t in range(tries):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 200:
                if use_cache:
                    open(fn, "w", encoding="utf-8").write(r.text)
                return r.text
            if r.status_code == 403 and "x-deny-reason" in r.headers:
                sys.exit(f"Mreža blokira {url}: {r.headers['x-deny-reason']}. Dopusti www.isvu.hr u mrežnim postavkama.")
        except requests.RequestException:
            pass
        time.sleep(2 * (t + 1))
    print("FAIL", url, file=sys.stderr, flush=True)
    return None


def jload(wd, name):
    return json.load(open(os.path.join(wd, name), encoding="utf-8"))


def jdump(obj, wd, name):
    json.dump(obj, open(os.path.join(wd, name), "w", encoding="utf-8"), ensure_ascii=False)


def add_common_args(p):
    p.add_argument("--year", type=int, default=2026, help="početna godina ak. god. (2026 = 2026./2027.)")
    p.add_argument("--workdir", default="/home/claude/isvu-work")
    return p
