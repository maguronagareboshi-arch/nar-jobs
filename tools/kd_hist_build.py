# 2026-10-21 研究(手元・DB に書かない): 東海の馬の 2022-11 より前の地方の走りを KDSCOPE から引いて台帳の runs の形にする。
# 入力= 台帳の書き出し tokai_dump.json.gz(一時便の artifact)・KDSCOPE(C:/KDSCOPE/Data/RA/RA.DAT を chunks で)・
#       kd_read.py の出力 kd_se.parquet / kd_horse.parquet(KDSCOPE の SE・UM・NU をそのまま縦にしたもの)
# 出力= scratchpad/kd_hist.json.gz {"add": {code: [runs]}, "fill_ta": {code: {key: ta}}, "races": [[tr,d,no,name,kind]]}
import datetime as dt, gzip, json, os, re, sys, unicodedata
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

S = os.environ.get("KS_S", r"C:\Users\kouki\AppData\Local\Temp\claude\C--Users-kouki-nar-site\6ec6fe4f-561d-4388-87fe-dbb7d57d3fea\scratchpad")
V3 = "C:/Users/kouki/nankan_ai/v3/"
KD = "C:/KDSCOPE/Data/"
CUT = "2022-11-01"
JYO = {30: "門別", 31: "北見", 32: "岩見沢", 33: "帯広", 34: "旭川", 35: "盛岡", 36: "水沢", 37: "上山", 38: "三条", 39: "足利",
       40: "宇都宮", 41: "高崎", 42: "浦和", 43: "船橋", 44: "大井", 45: "川崎", 46: "金沢", 47: "笠松", 48: "名古屋", 49: "紀三井寺",
       50: "園田", 51: "姫路", 52: "益田", 53: "福山", 54: "高知", 55: "佐賀", 56: "荒尾", 57: "中津", 58: "札幌", 59: "函館",
       60: "新潟", 61: "中京", 83: "帯広"}


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s or "")))


def say(*a):
    print(*a, flush=True)


D = json.load(gzip.open(S + r"\dl\tokai_dump.json.gz", "rt", encoding="utf-8"))
births = D["births"]
# 1. 馬の結びつけ= 馬名+生年月日(KD で同じ鍵が 2 頭あれば使わない)
kh = pd.read_parquet(V3 + "kd_horse.parquet", columns=["ketto", "name", "birth"])
kh = kh[kh.ketto.notna() & kh.birth.notna()]
kh["key"] = kh.name.map(norm) + "|" + kh.birth.astype("int64").astype(str)
kh = kh.drop_duplicates(["key", "ketto"])   # kd_horse は UM と NU を縦につないだ= 同じ馬が 2 行
dup = kh.key.duplicated(keep=False)
k2t = dict(zip(kh.key[~dup], kh.ketto[~dup].astype("int64")))
dupk = set(kh.key[dup])
link, nolink, amb = {}, 0, 0
for r in D["rows"]:
    b = births.get(r["code"])
    if not b:
        nolink += 1
        continue
    key = norm(r["horse_name"]) + "|" + str(b).replace("-", "")[:8]
    if key in k2t:
        link[r["code"]] = k2t[key]
    elif key in dupk:
        amb += 1
    else:
        nolink += 1
say(f"馬 {len(D['rows'])}・結びついた {len(link)}・同じ鍵が 2 頭 {amb}・見つからない {nolink}")
t2c = {v: k for k, v in link.items()}
if len(t2c) != len(link):
    say("要判断: 1 つの KD 馬に台帳の 2 頭")
# 2. SE(地方の場)を結びついた馬だけ
cols = ["jyo", "date", "race", "ketto", "trainer_cd", "ijo", "finish", "prize"]
se = pq.read_table(V3 + "kd_se.parquet", columns=cols,
                   filters=[("ketto", "in", [float(x) for x in t2c]), ("jyo", ">", 10.0)]).to_pandas()
se = se.drop_duplicates(["ketto", "date", "jyo", "race"], keep="last")
se["tr"] = se.jyo.astype(int).map(JYO)
se["d"] = se.date.dt.strftime("%Y-%m-%d")
se["code"] = se.ketto.astype("int64").map(t2c)
say(f"KD の地方の走り {len(se):,}・場名なし {int(se.tr.isna().sum())} {Counter(se.jyo[se.tr.isna()]).most_common(5)}")
# 調教師の所属= その年に一番多く走らせた場(東海= 名古屋→愛知・笠松→笠松・他→その場)
trs = set(se.trainer_cd.dropna())
tt = pq.read_table(V3 + "kd_se.parquet", columns=["trainer_cd", "jyo", "year"],
                   filters=[("trainer_cd", "in", list(trs)), ("jyo", ">", 10.0)]).to_pandas()
home = tt.groupby(["trainer_cd", "year"]).jyo.agg(lambda x: x.value_counts().index[0]).to_dict()
del tt
AREA = {47: "笠松", 48: "愛知"}
se["ta"] = [None if not isinstance(t, str) or not t else (lambda j: None if j is None else AREA.get(int(j), JYO.get(int(j), "他")))(home.get((t, y)))
            for t, y in zip(se.trainer_cd, se.date.dt.year)]
# 3. RA(レース名・格)を chunks で: 結びついた走りのレース+東海の全レース(2022-11 より前)
need = set(((se.date.dt.year * 10000 + se.date.dt.month * 100 + se.date.dt.day) * 100 + se.jyo) * 100 + se.race)
ra = []
L = 1272
with open(KD + "RA/RA.DAT", "rb") as f:
    while True:
        buf = f.read(L * 100000)
        if not buf:
            break
        a = np.frombuffer(buf, dtype=np.uint8).reshape(-1, L)
        a = a[(a[:, 0] == ord("R")) & (a[:, 1] == ord("A"))]

        def num(s, l):
            sub = a[:, s:s + l].astype(np.int64) - 48
            return (sub * (10 ** np.arange(l - 1, -1, -1))).sum(1)

        y, md, jy, rc, mk = num(11, 4), num(15, 4), num(19, 2), num(25, 2), num(3, 8)
        key = ((y * 10000 + md) * 100 + jy) * 100 + rc
        ok = (jy > 10) & (np.isin(key, list(need)) | (np.isin(jy, [47, 48]) & (y * 10000 + md < 20221101) & (y >= 2000)))
        for i in np.nonzero(ok)[0]:
            rec = a[i]
            t = lambda s, l: rec[s:s + l].tobytes().decode("cp932", "replace").replace("\u3000", "").strip()
            ra.append((int(key[i]), int(mk[i]), int(y[i]), int(md[i]), int(jy[i]), int(rc[i]),
                       t(32, 60), t(92, 60), t(152, 60), t(637, 60), t(614, 1)))
ra = pd.DataFrame(ra, columns=["key", "make", "y", "md", "jyo", "race", "hon", "fuku", "kakko", "joken", "grade"])
ra = ra.sort_values("make").drop_duplicates("key", keep="last")
ra["name"] = (ra.hon + ra.fuku + ra.kakko + ra.joken)
ra["d"] = [f"{y:04d}-{md // 100:02d}-{md % 100:02d}" for y, md in zip(ra.y, ra.md)]
say(f"RA のレース {len(ra):,}")
# 格の読み= 重なる期間の台帳の race_kind と RA の grade を並べる
dr = {(t, d, int(n)): (rn, rk) for t, d, n, rn, rk in D["races"]}
ov = ra[ra.jyo.isin([47, 48])].copy()
ov["dk"] = [dr.get((JYO[j], d, r)) for j, d, r in zip(ov.jyo, ov.d, ov.race)]
ov = ov[ov.dk.notna()]
say("格の読み(RA grade → 台帳 race_kind)", Counter((g, k[1]) for g, k in zip(ov.grade, ov.dk)).most_common(12))
for g, nm, k in list(zip(ov.grade, ov.name, ov.dk))[:4] + [x for x in zip(ov.grade, ov.name, ov.dk) if x[2][1] == "重賞"][:3]:
    say("   例", repr(g), nm, "|", k[0], k[1])
gk = Counter((g, k[1]) for g, k in zip(ov.grade, ov.dk))
GMAP = {}
for g in set(ov.grade):
    GMAP[g] = max(((k, n) for (gg, k), n in gk.items() if gg == g), key=lambda x: x[1])[0]
say("採る読み", GMAP)
ra["kind"] = ra.grade.map(GMAP).fillna("普通")
rmap = {k: (n, kd) for k, n, kd in zip(ra.key, ra.name, ra.kind)}
se["key"] = ((se.date.dt.year * 10000 + se.date.dt.month * 100 + se.date.dt.day) * 100 + se.jyo) * 100 + se.race
se["name"] = se.key.map(lambda k: rmap.get(k, ("", ""))[0])
# 4. 重なる期間(2022-11 以降)の照らし合わせ: 賞金・着順・所属
rows = {r["code"]: r for r in D["rows"]}
cmp = Counter()
for x in se[se.d >= CUT].itertuples():
    r = rows.get(x.code)
    hit = [y for y in r["runs"] if y.get("d") == x.d and y.get("tr") == x.tr and y.get("no") == int(x.race)]
    if not hit:
        cmp["台帳に無い"] += 1
        continue
    y = hit[0]
    cmp["比べた"] += 1
    kf = None if (x.ijo and x.ijo > 0) or not x.finish else int(x.finish)
    if y.get("fin") is not None and kf is not None:
        cmp["着順比べた"] += 1
        cmp["着順一致"] += y["fin"] == kf
    kp = int(x.prize or 0) * 100
    cmp["賞金一致"] += int(y.get("prize") or 0) == kp
    if int(y.get("prize") or 0) != kp and cmp["賞金違い例"] < 5:
        cmp["賞金違い例"] += 1
        say("   賞金違い", x.d, x.tr, int(x.race), y.get("prize"), kp)
    if y.get("ta"):
        cmp["所属比べた"] += 1
        tok = lambda v: v if v in ("愛知", "笠松", "岐阜") else "外"
        cmp["所属一致(東海/外)"] += tok(y["ta"]).replace("岐阜", "笠松") == tok(x.ta)
dlocal = sum(1 for c in t2c.values() for y in rows[c]["runs"] if not y.get("jra") and y.get("d", "") >= CUT and y.get("d", "") <= "2026-09-27")
say(f"重なり: 台帳の地方の走り(結びついた馬・〜9/27){dlocal:,}・KD {int((se.d >= CUT).sum()):,}・", dict(cmp))
# 5. 足す走り(2022-11 より前・台帳に同じ走りが無いもの)と所属の埋め
add, fill = defaultdict(list), defaultdict(dict)
for x in se[se.d < CUT].itertuples():
    r = rows[x.code]
    hit = [y for y in r["runs"] if y.get("d") == x.d and y.get("tr") == x.tr and y.get("no") == int(x.race)]
    if hit:
        if not hit[0].get("ta") and x.ta:
            fill[x.code][f"{x.d}|{x.tr}|{int(x.race)}"] = x.ta
        continue
    fin = None if (x.ijo and x.ijo > 0) or not x.finish else int(x.finish)
    add[x.code].append({"d": x.d, "tr": x.tr, "no": int(x.race), "fin": fin, "prize": int(x.prize or 0) * 100,
                        "name": x.name, "ta": x.ta, "jra": False, "src": "kd"})
racesadd = [[JYO[j], d, int(r), n, k] for j, d, r, n, k in zip(ra.jyo, ra.d, ra.race, ra.name, ra.kind)
            if j in (47, 48) and d < CUT and (JYO[j], d, int(r)) not in dr]
say(f"足す走り {sum(len(v) for v in add.values()):,}({len(add)} 頭)・所属を埋める {sum(len(v) for v in fill.values())}・足す東海のレース {len(racesadd):,}")
json.dump({"cmp": dict(cmp), "add": add, "fill_ta": fill, "races": racesadd, "link": {k: int(v) for k, v in link.items()}},
          gzip.open(S + r"\kd_hist.json.gz", "wt", encoding="utf-8"), ensure_ascii=False)
say("保存", S + r"\kd_hist.json.gz")
