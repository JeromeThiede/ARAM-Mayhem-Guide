#!/usr/bin/env python3
"""
ARAM Mayhem data updater (flat / single-file version).

Fetches the public arammayhem.com pages and writes fresh data DIRECTLY into
index.html, between the /*DATA_START*/ and /*DATA_END*/ markers:
  - CHAMPS       roster (name, slug, role, tier, rank, wr, pr)
  - AUGS         all augments (rank, name, slug, rarity, new, wr, pr, top[])
  - META         patch, update date, counts
  - EXACT_BUILDS per-champion item builds (start / core / boots item ids)

No sub-folders, no separate data files. Runs server-side (GitHub Actions),
so there is no CORS restriction. Item icons are rendered from the same
arammayhem.com/items/<id>.png URLs the source uses, so they always match.
"""
import json, re, sys, time, datetime, os, argparse
import requests
from bs4 import BeautifulSoup

BASE = "https://arammayhem.com"
ROLES = ["Marksman", "Assassin", "Support", "Fighter", "Tank", "Mage"]
BOOTS_IDS = {3006, 3009, 3020, 3047, 3111, 3117, 3158, 3170}
HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; aram-mayhem-site/1.0)"})


def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            print(f"  {url} -> HTTP {r.status_code}")
        except Exception as e:
            print(f"  {url} -> {e}")
        time.sleep(1.5 * (i + 1))
    return None


def parse_champions(html):
    soup = BeautifulSoup(html, "html.parser")
    champs, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/build/[a-z0-9]+/?$")):
        title = a.get("title", "") or ""
        if "Rank: #" not in title:
            continue
        slug = re.search(r"/build/([a-z0-9]+)/?$", a["href"]).group(1)
        if slug in seen:
            continue
        txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        role = next((r for r in ROLES if txt.endswith(r)), None)
        name = title.split("Rank:")[0].strip()
        rank = re.search(r"Rank:\s*#(\d+)", title)
        wr = re.search(r"Win Rate:\s*([\d.]+)%", title)
        pr = re.search(r"Pick Rate:\s*([\d.]+)%", title)
        tier = None
        prev = a.find_previous(string=re.compile(r"(S\+|S|A|B|C)\s*Tier"))
        if prev:
            tm = re.search(r"(S\+|S|A|B|C)\s*Tier", prev)
            tier = tm.group(1) if tm else None
        seen.add(slug)
        champs.append({"name": name, "slug": slug, "role": role, "tier": tier,
                       "rank": int(rank.group(1)) if rank else None,
                       "wr": float(wr.group(1)) if wr else None,
                       "pr": float(pr.group(1)) if pr else None})
    champs.sort(key=lambda c: (c["rank"] is None, c["rank"]))
    return champs


def parse_augments(html, name_set):
    soup = BeautifulSoup(html, "html.parser")
    names_sorted = sorted(name_set, key=len, reverse=True)

    def split_champs(blob):
        res, s = [], blob.strip()
        while s:
            s = s.strip()
            if not s:
                break
            hit = next((n for n in names_sorted if s.startswith(n)), None)
            if not hit:
                break
            res.append(hit); s = s[len(hit):]
        return res

    norm_map = {re.sub(r"[^a-z0-9]", "", n.lower()): n for n in name_set}

    augs, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/augments/[a-z0-9\-]+/?$")):
        slug = re.search(r"/augments/([a-z0-9\-]+)/?$", a["href"]).group(1)
        text = re.sub(r"\s+", " ", a.get_text("", strip=True)).strip()
        m = re.match(r"^(\d+)\s*(.*)$", text)
        if not m or slug in seen:
            continue
        rank = int(m.group(1)); body = m.group(2)
        rm = re.search(r"(New)?\s*(Prismatic|Gold|Silver)(?=\s*(?:\d|No data))", body)
        if not rm:
            continue
        is_new = bool(rm.group(1)); rarity = rm.group(2)
        img = a.find("img")
        name = (img.get("alt").strip() if img and img.get("alt") else "")
        if not name:
            nm = body[:rm.start()].strip()
            if len(nm) % 2 == 0 and nm[:len(nm)//2] == nm[len(nm)//2:]:
                nm = nm[:len(nm)//2]
            name = nm
        rest = body[rm.end():].strip()
        wr = pr = None; top = []
        if not rest.startswith("No data"):
            pcts = list(re.finditer(r"([\d.]+)%", rest))
            if len(pcts) >= 2:
                wr = float(pcts[0].group(1)); pr = float(pcts[1].group(1))
            # Top champions are rendered as champion ICONS (images) in the row, so
            # read them from <img alt="..."> in DOM order; fall back to inline text.
            seen_t = set()
            for img in a.find_all("img"):
                alt = (img.get("alt") or "").strip()
                key = re.sub(r"[^a-z0-9]", "", alt.lower())
                nm = norm_map.get(key)
                if nm and nm not in seen_t:
                    seen_t.add(nm); top.append(nm)
            if not top and len(pcts) >= 3:
                top = split_champs(rest[pcts[2].end():])
        seen.add(slug)
        augs.append({"rank": rank, "name": name, "slug": slug, "rarity": rarity,
                     "new": is_new, "wr": wr, "pr": pr, "top": top})
    augs.sort(key=lambda a: a["rank"])
    return augs


def item_ids_after(html, marker, count):
    idx = html.find(marker)
    if idx < 0:
        return []
    window = html[idx: idx + 6000]
    ids, seen = [], set()
    for m in re.finditer(r"/items/(\d+)\.png", window):
        iid = int(m.group(1))
        if iid not in seen:
            seen.add(iid); ids.append(iid)
        if len(ids) >= count:
            break
    return ids


def parse_build(html):
    core = item_ids_after(html, "Core Build", 3)       # top core build (highest pick rate)
    start = item_ids_after(html, "Starting Items", 5)
    boots_all = item_ids_after(html, "Boots", 8)
    boots = [i for i in boots_all if i in BOOTS_IDS][:1]
    out = {}
    if start:
        out["start"] = start[:3]
    if core:
        out["core"] = core[:3]
    if boots:
        out["boots"] = boots
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-builds", action="store_true", help="skip per-champion item builds")
    ap.add_argument("--limit", type=int, default=0, help="limit champion build fetches (debug)")
    args = ap.parse_args()

    print("Fetching champion roster…")
    idx_html = fetch(BASE + "/build/")
    if not idx_html:
        print("FATAL: build index"); sys.exit(1)
    champs = parse_champions(idx_html)
    print(f"  {len(champs)} champions")
    if len(champs) < 100:
        print("FATAL: too few champions, aborting"); sys.exit(1)

    patch = None
    pm = re.search(r"Patch\s*(\d+\.\d+)", idx_html)
    if pm:
        patch = pm.group(1)

    print("Fetching augments…")
    aug_html = fetch(BASE + "/augments/")
    if not aug_html:
        print("FATAL: augments"); sys.exit(1)
    augs = parse_augments(aug_html, {c["name"] for c in champs})
    print(f"  {len(augs)} augments")
    if len(augs) < 100:
        print("FATAL: too few augments, aborting"); sys.exit(1)

    # keep existing builds unless we successfully scrape a fresh set
    builds = current_builds()
    if not args.no_builds:
        todo = champs if not args.limit else champs[:args.limit]
        print(f"Fetching item builds for {len(todo)} champions…")
        fresh = {}
        for i, c in enumerate(todo, 1):
            html = fetch(f"{BASE}/build/{c['slug']}/")
            if html:
                b = parse_build(html)
                if b:
                    fresh[c["slug"]] = b
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}")
            time.sleep(0.3)
        print(f"  builds captured: {len(fresh)}")
        if len(fresh) >= 50:            # only replace if the scrape clearly worked
            builds = fresh

    meta = {"updated": datetime.date.today().isoformat(), "patch": patch or "n/a",
            "source": "arammayhem.com", "champions": len(champs),
            "augments": len(augs), "builds": len(builds)}

    j = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    block = ("/*DATA_START - auto-generated by scrape.py, do not edit by hand*/\n"
             "const CHAMPS = " + j(champs) + ";\n"
             "const AUGS = " + j(augs) + ";\n"
             "const META = " + j(meta) + ";\n"
             "const EXACT_BUILDS = " + j(builds) + ";\n"
             "/*DATA_END*/")

    html = open(INDEX, encoding="utf-8").read()
    if "/*DATA_START" not in html or "/*DATA_END*/" not in html:
        print("FATAL: data markers not found in index.html"); sys.exit(1)
    html = re.sub(r"/\*DATA_START.*?/\*DATA_END\*/", lambda _m: block, html, count=1, flags=re.S)
    open(INDEX, "w", encoding="utf-8").write(html)
    print("Updated index.html ->", meta)


def current_builds():
    """Read the EXACT_BUILDS object already embedded in index.html, so a build-less
    run (or one that fails) keeps the last good builds instead of wiping them."""
    try:
        html = open(INDEX, encoding="utf-8").read()
        m = re.search(r"const EXACT_BUILDS\s*=\s*(\{.*?\});", html, re.S)
        if m:
            return json.loads(m.group(1))
    except Exception as e:
        print("  (could not read existing builds:", e, ")")
    return {}


if __name__ == "__main__":
    main()
