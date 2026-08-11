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
METASRC = "https://www.metasrc.com"
ROLES = ["Marksman", "Assassin", "Support", "Fighter", "Tank", "Mage"]
BOOTS_IDS = {3006, 3009, 3020, 3047, 3111, 3117, 3158, 3170}
# consumables / wards / elixirs to exclude from builds
CONSUMABLES = {2003, 2010, 2031, 2033, 2055, 2138, 2139, 2140, 2141, 2422, 3340, 3363, 3364, 2052}
HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


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
        # capture the real augment icon URL (naming is inconsistent, so don't guess)
        icon = ""
        for img in a.find_all("img"):
            s = (img.get("data-src") or img.get("src") or "").strip()
            if "_mayhem_augment" in s or "/augments/" in s.lower():
                icon = s
                break
        if icon.startswith("/"):
            icon = BASE + icon
        seen.add(slug)
        augs.append({"rank": rank, "name": name, "slug": slug, "rarity": rarity,
                     "new": is_new, "wr": wr, "pr": pr, "top": top, "icon": icon})
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
    """Assemble a full 6-item build: the champion's most-used core items,
    guaranteed to include boots, topped up from starting items if needed."""
    build = item_ids_after(html, "Core Build", 6)     # most-used core items (dedup, in order)
    boots = [i for i in item_ids_after(html, "Boots", 8) if i in BOOTS_IDS][:1]
    if boots and boots[0] not in build:
        build = (build[:5] + boots) if len(build) >= 6 else (build + boots)
    if len(build) < 6:
        for i in item_ids_after(html, "Starting Items", 6):
            if i not in build:
                build.append(i)
            if len(build) >= 6:
                break
    build = build[:6]
    return {"build": build} if build else None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def metasrc_slug_map(champs):
    """Match each champion to its metasrc slug using the live index (robust to naming)."""
    html = fetch(METASRC + "/lol/mayhem/champions")
    if not html:
        print("  metasrc index: no response (blocked?)")
        return {}
    ms_slugs = set(re.findall(r"/lol/mayhem/champions/([a-z0-9\-]+)/build", html))
    print(f"  metasrc index: {len(html)} bytes, {len(ms_slugs)} champion slugs found")
    out = {}
    for c in champs:
        name = c["name"]
        base = re.sub(r"\s+", " ", name.lower().replace("&", "").replace("'", "").replace(".", "")).strip()
        base_and = re.sub(r"\s+", " ", name.lower().replace("&", "and").replace("'", "").replace(".", "")).strip()
        cands = [base.replace(" ", "-"), base.replace(" ", ""),
                 base_and.replace(" ", "-"), base_and.replace(" ", "")]
        hit = next((s for s in cands if s in ms_slugs), None)
        if not hit:
            hit = next((s for s in ms_slugs if _norm(s) == _norm(name)), None)
        if hit:
            out[c["slug"]] = hit
    return out


def _match_ms_slugs(ms_slugs, champs):
    out = {}
    for c in champs:
        name = c["name"]
        base = re.sub(r"\s+", " ", name.lower().replace("&", "").replace("'", "").replace(".", "")).strip()
        base_and = re.sub(r"\s+", " ", name.lower().replace("&", "and").replace("'", "").replace(".", "")).strip()
        cands = [base.replace(" ", "-"), base.replace(" ", ""),
                 base_and.replace(" ", "-"), base_and.replace(" ", "")]
        hit = next((s for s in cands if s in ms_slugs), None) \
            or next((s for s in ms_slugs if _norm(s) == _norm(name)), None)
        if hit:
            out[c["slug"]] = hit
    return out


def metasrc_builds_browser(champs):
    """Render metasrc with a headless browser (bypasses the plain-request 403 + JS)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("  playwright not available:", e)
        return {}
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    builds = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent=UA, locale="en-US",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()

            def get(url):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(1800)
                    return page.content()
                except Exception as ex:
                    print("   render failed:", url, ex)
                    return None

            idx = get(METASRC + "/lol/mayhem/champions")
            if not idx:
                print("  metasrc index: no render (blocked?)")
                browser.close()
                return {}
            ms_slugs = set(re.findall(r"/lol/mayhem/champions/([a-z0-9\-]+)/build", idx))
            print(f"  metasrc index (browser): {len(ms_slugs)} champion slugs found")
            smap = _match_ms_slugs(ms_slugs, champs)
            print(f"  metasrc matched {len(smap)}/{len(champs)} champions")
            for i, c in enumerate(champs, 1):
                ms = smap.get(c["slug"])
                if not ms:
                    continue
                html = get(f"{METASRC}/lol/mayhem/champions/{ms}/build")
                if html:
                    b = parse_metasrc_build(html)
                    if b:
                        builds[c["slug"]] = b
                if i % 25 == 0:
                    print(f"  {i}/{len(champs)} (builds so far: {len(builds)})")
            browser.close()
    except Exception as e:
        print("  browser scrape error:", e)
    return builds


def parse_metasrc_build(html):
    """Read the completed items from metasrc's Item Build Order: each completed item's
    icon is immediately followed by a gold-coin marker."""
    ids = []
    for cm in re.finditer(r"icons/coin\.png", html):
        pre = html[max(0, cm.start() - 1500):cm.start()]
        found = re.findall(r"static/items/[a-z0-9\-]*?-(\d+)\.png", pre)
        if found:
            iid = int(found[-1])
            if iid not in ids and iid not in CONSUMABLES:
                ids.append(iid)
        if len(ids) >= 6:
            break
    return {"build": ids[:6]} if ids else None


def scrape_arammayhem_builds(champs):
    """Fallback build source: arammayhem champion pages (reachable from CI)."""
    builds = {}
    for i, c in enumerate(champs, 1):
        html = fetch(f"{BASE}/build/{c['slug']}/")
        if html:
            b = parse_build(html)
            if b:
                builds[c["slug"]] = b
        if i % 25 == 0:
            print(f"  {i}/{len(champs)}")
        time.sleep(0.3)
    return builds


def scrape_metasrc_builds(champs):
    smap = metasrc_slug_map(champs)
    print(f"  metasrc matched {len(smap)}/{len(champs)} champions")
    builds = {}
    for i, c in enumerate(champs, 1):
        ms = smap.get(c["slug"])
        if not ms:
            continue
        html = fetch(f"{METASRC}/lol/mayhem/champions/{ms}/build")
        if html:
            b = parse_metasrc_build(html)
            if b:
                builds[c["slug"]] = b
        if i % 25 == 0:
            print(f"  {i}/{len(champs)}")
        time.sleep(0.3)
    return builds


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

    # item builds from metasrc (fail-safe: keep existing builds if too few come back)
    builds = current_builds()
    if not args.no_builds:
        todo = champs if not args.limit else champs[:args.limit]
        print("Fetching item builds from metasrc (headless browser)…")
        fresh = metasrc_builds_browser(todo)
        print(f"  metasrc builds captured: {len(fresh)}")
        if len(fresh) >= 50:
            builds = fresh   # fresh authoritative metasrc set
        else:
            # keep existing (e.g. browser-harvested) builds; only fill missing champions
            print("metasrc unavailable — keeping existing builds, filling gaps via arammayhem…")
            missing = [c for c in todo if c["slug"] not in builds]
            if missing:
                am = scrape_arammayhem_builds(missing)
                builds.update(am)
                print(f"  arammayhem filled {len(am)} missing champions")

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
