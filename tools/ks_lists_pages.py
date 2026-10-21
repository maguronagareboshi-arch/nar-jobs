# 2026-10-21 笠松の番組賞金の仕組みの照合(手元・書き込みなし)。入力の台帳= 一時便(ks_dump.py・コミット 32a4679)の artifact tokai_dump.json.gz・
# 一覧= fetch_lists(笠松 /raceprogram の 21 回+名古屋 2025-15〜2026-16)→ ks_lists_pages.py で開催日ごとに。パス S は手元の作業場所
import datetime as dt, json, re, sys, glob, unicodedata
sys.path.insert(0, r"C:\Users\kouki\wt\nar-jobs-ks-mech\cloud")
import tokai_official as T
import pymupdf
S = r"C:\Users\kouki\AppData\Local\Temp\claude\C--Users-kouki-nar-site\6ec6fe4f-561d-4388-87fe-dbb7d57d3fea\scratchpad"
pages = {}   # date -> {name: k}
bad = 0
for f in sorted(glob.glob(S + r"\dl\ks\c*.pdf")):
    doc = pymupdf.open(f)
    for page in doc:
        raw = page.get_text()
        t = unicodedata.normalize("NFKC", raw)
        fy = re.search(r"令和(\d+)年度", t)
        md = re.search(r"第\s*\d+\s*日目\s*(\d+)月\s*(\d+)日", t)
        if not fy or not md:
            print("NO DATE", f); continue
        y = 2018 + int(fy.group(1)); m, d = int(md.group(1)), int(md.group(2))
        day = dt.date(y + (1 if m < 4 else 0), m, d)
        ls = [x.strip() for x in raw.splitlines()]
        got = pages.setdefault(day.isoformat(), {})
        for i in range(1, len(ls)):
            mm = T.KS_PRIZE.match(ls[i])
            if not mm or (not mm.group(2) and len(mm.group(1)) < 3):
                continue
            if T.KS_NAME.fullmatch(ls[i - 1]):
                n, p = ls[i - 1], int(mm.group(1))
                if n in got and got[n] != p:
                    bad += 1
                got[n] = p
# 連続する開催日(2 日以内の空き)を 1 つの一覧に
blocks = []
for d in sorted(pages):
    dd = dt.date.fromisoformat(d)
    if blocks and (dd - blocks[-1]["last"]).days <= 2:
        blocks[-1]["last"] = dd; blocks[-1]["days"].append(d)
    else:
        blocks.append({"first": dd, "last": dd, "days": [d]})
out = []
for b in blocks:
    off, conf = {}, set()
    for d in b["days"]:
        for n, p in pages[d].items():
            if n in off and off[n] != p: conf.add(n)
            off[n] = p
    for n in conf: off.pop(n)
    out.append({"first": b["first"].isoformat(), "days": b["days"], "off": off, "conf": len(conf)})
    print(b["first"], len(b["days"]), len(off), "conf", len(conf))
print("bad in page", bad)
L = json.load(open(S + r"\lists.json", encoding="utf-8"))
L["ksb"] = out
json.dump(L, open(S + r"\lists.json", "w", encoding="utf-8"), ensure_ascii=False)
