import datetime as dt, json, re, sys, os, urllib.request, time
sys.path.insert(0, r"C:\Users\kouki\wt\nar-jobs-ks-mech\cloud")
import tokai_official as T
S = r"C:\Users\kouki\AppData\Local\Temp\claude\C--Users-kouki-nar-site\6ec6fe4f-561d-4388-87fe-dbb7d57d3fea\scratchpad\dl"
def get(u, p):
    if os.path.exists(p):
        return open(p, "rb").read()
    try:
        b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    except Exception as e:
        return None
    open(p, "wb").write(b); time.sleep(0.3)
    return b
html = get(T.KS_BASE + "/raceprogram", S + r"\ks\page.html").decode("utf-8", "ignore")
ms = list(T.KS_CYC.finditer(html))
ks = []
for i, mc in enumerate(ms):
    seg = html[mc.end(): ms[i + 1].start() if i + 1 < len(ms) else len(html)]
    head = re.match(r"\s*</span>([^<]*)", seg)
    days = T.ks_dates(head.group(1) if head else "", dt.date(2026, 10, 21))
    ml = T.KS_LINK.search(seg)
    data = get(T.KS_BASE + ml.group(1), S + rf"\ks\c{i:02d}_{mc.group(1)}.pdf")
    seen, bad = {}, set()
    for n, p in T.ks_parse_pdf(data):
        if n in seen and seen[n] != p: bad.add(n)
        seen[n] = p
    for k in bad: seen.pop(k)
    ks.append({"cyc": int(mc.group(1)), "days": sorted(d.isoformat() for d in days), "off": seen, "dup": len(bad)})
    print("KS", mc.group(1), min(days) if days else None, len(seen), len(bad))
ng = []
for y, cs in ((2025, range(15, 27)), (2026, range(1, 17))):
    for c in cs:
        for d in range(1, 6):
            b = get(f"{T.BASE}/file/{y}-{c}-{d}.pdf", S + rf"\ng\{y}-{c}-{d}.pdf")
            if not b or not b.startswith(b"%PDF"):
                if b is not None and os.path.exists(S + rf"\ng\{y}-{c}-{d}.pdf"): os.remove(S + rf"\ng\{y}-{c}-{d}.pdf")
                continue
            ng.append({"y": y, "c": c, "d": d, "off": [list(x) for x in T.parse_pdf(b)]})
    print("NG", y, len(ng))
json.dump({"ks": ks, "ng": ng}, open(S + r"\..\lists.json", "w", encoding="utf-8"), ensure_ascii=False)
