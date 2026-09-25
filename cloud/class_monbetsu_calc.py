# -*- coding: utf-8 -*-
"""§284① 門別の番組賞金と級を「公式の起点+自前の加算」で出す(nar_meta 'monbetsu_class_calc')。

公式の級別表(nar_meta 'monbetsu_class'・class_monbetsu.py)は隔週にしか出ない。その間の走を
番組編成要領 令和8年度 第7(表2・表3/表B・※1〜※4)で自前に足して「今日の番組賞金と級」を出す。
⛔§38「推定と公式を混ぜない」= 公式の写し 'monbetsu_class' は変えない。こちらは別キー・src="calc"。

  起点= 馬ごとに、その馬が公式の表に載った**最新回**の番組賞金。締め= その回の一般(ipan)の発表日の前日
        (2歳も同じ・第8回のように ipan/2sai で日が違う回がある= stage2_rules.json)。
  加算= 締めより後の走。門別= 表2(同着は ※4 の平均・1万円未満切捨て / 2歳 ※1 15万・※2 40万)。
        他場= 表3(地方は1着賞金の段で率・上限)。中央= 賞金が DB に無い→ 1〜5着の平地は加算せず
        flag='jra_missing'(公式の次の回で起点が置き直る)。上限 4,000 万。
  級  = 3歳以上で、起点の見出し(cls)が級の形(単独/並記/範囲)の馬だけ KAKUZUKE に当てる(kaku_of)。
  答え合わせ= 公式の新しい回が入った直後に、前の起点+加算(新しい回の締めまで)と新しい公式を全頭照合し
        check に書く。外れがあれば heartbeat 'monbetsu_calc' を ok=False(件数と馬名 3 頭まで)。
        外れた馬も含め、起点は常に最新回の公式に置き直す。
  検算(2026-09-25・scratchpad stage2.py/stage3_*.json): 起点が公式と合った馬は第1〜13回まで加算だけで全頭一致
        (S2 291/291・S3 176/176・2歳 328/328)。第12回起点→第13回 813/815(外れ 2 は同着の端数の揺れ)。

  出力 = nar_meta key='monbetsu_class_calc' の value:
    {"built","src":"calc","fy","base_kai","base_asof","upto","cuts":{"1":"2026-04-09",…},
     "horses":{馬名:{"prize":円,"kaku":"Ｃ２","base":円,"base_kai":13,"cls":起点の見出し,"age":4,
                     "add":[[日付,場,R,着,円,表の区分],…],"flag":null|"jra_missing"|"race_missing"|"class_unknown"}},
     "check":{"kai":13,"n":…,"match":…,"miss":[[馬名,自前の円,公式の円,起点の回],…]}}

  python cloud/class_monbetsu_calc.py --env pipeline/.env.nar            # ドライラン(読むだけ・--out へ書く)
  python cloud/class_monbetsu_calc.py --apply                            # nar_meta へ upsert+heartbeat
  (class_monbetsu.py --timed が新しい回を入れた後と、nar-refresh の朝の便から呼ばれる)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 読めない。
⛔本番 DB は対象馬に絞った PostgREST だけ(今年度の走・order は一意)。重い SQL は使わない。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import class_monbetsu as CM  # noqa: E402

CALC_KEY = "monbetsu_class_calc"
BEAT_JOB = "monbetsu_calc"
MAN = CM.MAN
CAP = 4000                       # 番組賞金の上限(万)
JST = CM.JST
CHUNK = 50                       # 馬名の in.(…) 1 本あたり
PAGE = 1000
D = dt.date.fromisoformat
# hist('monbetsu_class_hist')は回ごとの asof(大きい方)しか持たない。一般の発表日が違う回だけここで補う
SEED_IPAN_ASOF = {(2026, 8): "2026-07-17"}

# ------------------------------------------------------------ 表2(要領 令和8年度 第7・単位 万円)
T2_2 = {"JBC": [500, 140, 105, 70, 35], "EDEL": [300, 84, 63, 42, 21], "H1": [250, 70, 52, 35, 17],
        "H2": [200, 56, 42, 28, 14], "H3": [150, 42, 31, 21, 10], "OP": [100, 28, 21, 14, 7],
        "OP1": [70, 19, 14, 9, 4], "K12": [50, 14, 10, 7, 3], "SFC": [100, 7, 6, 5, 4],
        "ATK": [80, 5, 4, 3, 2], "NEW": [40, 5, 4, 3, 2], "K3": [30, 4, 3, 2, 1], "MI": [15, 4, 3, 2, 1]}
T2_3 = {"HSC": [500, 140, 105, 70, 35], "H1": [400, 112, 84, 56, 28], "H2": [250, 70, 52, 35, 17],
        "H3": [200, 56, 42, 28, 14], "OP1": [100, 28, 21, 14, 7], "K13": [50, 14, 10, 7, 3],
        "JRA": [50, 14, 10, 7, 3], "K4": [40, 0, 0, 0, 0], "MI": [40, 0, 0, 0, 0]}
T2_G = {"BGC": [1200, 336, 252, 168, 84], "DOEI": [800, 224, 168, 112, 56], "DSP": [500, 140, 105, 70, 35],
        "H2": [400, 112, 84, 56, 28], "H3": [300, 84, 63, 42, 21], "JUN": [250, 70, 52, 35, 17],
        "A1": [150, 42, 31, 21, 10], "A2": [100, 28, 21, 14, 7], "A34": [80, 22, 16, 11, 5],
        "B": [50, 14, 10, 7, 3], "CH": [40, 11, 8, 5, 2], "CL": [40, 0, 0, 0, 0],
        "CL7": [40, 0, 0, 0, 0]}   # 令和7年度の Ｃ４－３(1着だけ・上限40万)
TOK = re.compile(r"([ＡＢＣ])([１２３４1234])")
FLAG = {"中央の賞金なし": "jra_missing", "レース情報なし": "race_missing", "区分不明": "class_unknown"}


def fy_of(d):
    return d.year if d.month >= 4 else d.year - 1


def started(r):
    """出走した(取消・除外でない)"""
    n = r.get("finish_note") or ""
    return r.get("finish") is not None or ("中止" in n or "失格" in n or "落馬" in n)


def race_group(runners, race):
    nm = race.get("race_name") or ""
    ages = {r.get("age") for r in runners if r.get("age")}
    if "以上" in nm:
        return "3u"
    if "２歳" in nm and ages <= {2}:
        return "2"
    if "３歳" in nm:
        return "3"
    if "歳" not in nm and ages == {3} and len(runners) >= 3:
        return "3"
    return "3u"


def t2_key(runners, race, fy):
    """→ (表, 区分)。表が決まらなければ (None, "不明")。"""
    nm = race.get("race_name") or ""
    p1 = ((race.get("prize_yen") or [0])[0] or 0) // MAN
    kind = race.get("race_kind") or ""
    grp = race_group(runners, race)
    if grp == "2":
        if "ＪＢＣ２歳優駿" in nm:
            return T2_2, "JBC"
        if "エーデルワイス" in nm:
            return T2_2, "EDEL"
        if kind == "重賞" or p1 >= 800:   # 1着800万以上は特別でも H1(北海道２歳スプリント)
            return T2_2, ("H1" if p1 >= 800 else "H2" if p1 >= 500 else "H3")
        for w, k in (("フレッシュチャレンジ", "SFC"), ("アタックチャレンジ", "ATK"), ("新馬", "NEW"), ("未勝利", "MI"), ("３組", "K3")):
            if w in nm:
                return T2_2, k
        return T2_2, ("OP" if p1 >= 200 else "OP1" if p1 >= 100 else "K12")
    if grp == "3":
        if "北海道スプリント" in nm:
            return T2_3, "HSC"
        if kind == "重賞":
            return T2_3, ("H1" if p1 > 1000 else "H2" if p1 >= 600 else "H3")
        if "ＪＲＡ" in nm and "認定" not in nm:
            return T2_3, "JRA"
        if "未勝利" in nm:
            return T2_3, "MI"
        if "４組" in nm or "Ｃ４" in nm:
            return T2_3, "K4"
        if p1 >= 100 and not TOK.search(nm):
            return T2_3, "OP1"
        return T2_3, "K13"
    if "ブリーダーズゴールドカップ" in nm:
        return T2_G, "BGC"
    if "道営記念" in nm:
        return T2_G, "DOEI"
    if "道営スプリント" in nm:
        return T2_G, "DSP"
    if kind == "重賞":
        return T2_G, ("H2" if p1 >= 600 else "H3")
    if "準重賞" in nm:
        return T2_G, "JUN"
    if "ＪＲＡ" in nm and "認定" not in nm:
        return T2_G, "A2"
    m = TOK.search(nm.replace("ＪＢＣ", ""))     # ＪＢＣ の Ｃ を級と見ない
    if m:
        c, d = m.group(1), m.group(2).translate(str.maketrans("１２３４", "1234"))
        if c == "Ａ":
            return T2_G, {"1": "A1", "2": "A2"}.get(d, "A34")
        if c == "Ｂ":
            return T2_G, "B"
        if fy == 2025 and d == "4" and re.search(r"Ｃ４[－-]３", nm) and not re.search(r"Ｃ[１２３]|Ｃ４[－-][12１２]", nm):
            return T2_G, "CL7"
        return T2_G, ("CH" if d in "12" or fy == 2025 else "CL")
    if "オープン" in nm:
        return T2_G, "A1"
    return None, "不明"


def tb_nar(yen):
    """表3/表B 地方 1 走の獲得賞金(円)→ 加算(万)"""
    m = yen // MAN if yen else 0
    y = yen or 0
    for lo, pct, cap in ((1000, 15, None), (500, 20, 150), (200, 25, 100), (100, 30, 50), (50, 35, 30), (0, 40, 17)):
        if m >= lo:
            v = y * pct // 100 // MAN
            return min(v, cap) if cap else v
    return 0


def earned(r, races):
    """→ 獲得賞金(円)。中央で 1〜5 着= 賞金が DB に無い= None。"""
    f = r.get("finish")
    if r["track"] == "中央":
        if "prize_off" in r:
            return r["prize_off"]
        return None if (f and f <= 5) else 0
    race = races.get((r["track"], r["race_date"], r["race_no"]))
    if not race or not f or f > 5:
        return 0
    p = race.get("prize_yen") or []
    return p[f - 1] if len(p) >= f and p[f - 1] else 0


def tb_run(r, races):
    """→ (万, 欠け理由 or None)"""
    if r["track"] == "中央":
        if r.get("surface") == "障":
            return 0, None
        e = earned(r, races)
        if e is None:
            return 0, "中央の賞金なし"
        m = e // MAN          # 中央の平地: 500万以上 15%・未満 20%(上限75万)
        return (e * 15 // 100 // MAN if m >= 500 else min(e * 20 // 100 // MAN, 75)), None
    if (r["track"], r["race_date"], r["race_no"]) not in races:
        return 0, "レース情報なし"
    return tb_nar(earned(r, races)), None


class Acc:
    """番組賞金(万)を 1 走ずつ積む(表2・表3・※1〜※4・上限)。stage2.py の Acc と同じ。"""

    def __init__(self, val, wins, races, runners, cap2=True):
        self.val, self.wins, self.cap2 = val, wins, cap2
        self.races, self.runners = races, runners
        self.flags, self.det = set(), []

    def add(self, r):
        d = D(r["race_date"])
        fy = fy_of(d)
        f = r.get("finish")
        key = (r["track"], r["race_date"], r["race_no"])
        if r["track"] == "門別":
            race = self.races.get(key)
            if race is None:
                self.flags.add("レース情報なし")
                self.det.append([r["race_date"], "門別", r["race_no"], f, 0, "レース情報なし"])
            elif f and f <= 5:
                runners = self.runners.get(key, [])
                tab, k = t2_key(runners, race, fy)
                if tab is None:
                    self.flags.add("区分不明")
                    self.det.append([r["race_date"], "門別", r["race_no"], f, 0, "区分不明"])
                else:
                    ties = [x for x in runners if x.get("finish") == f]
                    if len(ties) > 1:     # ※4 同着= 該当する着の額の平均・1万円未満切捨て
                        amt = sum(tab[k][ff - 1] for ff in range(f, min(f + len(ties), 6))) // len(ties)
                        self.flags.add("同着")
                    else:
                        amt = tab[k][f - 1]
                    p = race.get("prize_yen") or []
                    real = p[f - 1] // MAN if len(p) >= f and p[f - 1] else None
                    if real is not None:
                        amt = min(amt, real)
                    nv = self.val + amt
                    lim = None
                    if k == "CL7":
                        lim = 40
                    elif tab is T2_2 and k in ("ATK", "MI") and not (f == 1 or (k == "ATK" and self.wins > 0)):
                        lim = 15      # ※1
                    elif tab is T2_2 and f != 1 and (k == "K3" or (self.cap2 and self.val <= 40)):
                        lim = 40      # ※2(40万以下の2歳馬の1着以外にも当てる= 実データ)
                    if lim is not None:
                        nv = max(self.val, min(nv, lim))
                        self.flags.add("2歳上限")
                    self.det.append([r["race_date"], "門別", r["race_no"], f, (nv - self.val) * MAN, "表2 " + k])
                    self.val = nv
        else:
            v, why = tb_run(r, self.races)
            if why:
                self.flags.add(why)
            self.flags.add("他場(表3)")
            self.val += v
            self.det.append([r["race_date"], r["track"], r.get("race_no"), f, v * MAN, why or "表3"])
        if f == 1:
            self.wins += 1
        self.val = min(self.val, CAP)
        return self


# ------------------------------------------------------------ 起点と加算(通信なし)
def ipan_cut(fy, kai, asof, asof_by=None):
    """回の締め= 一般(ipan)の発表日の前日。"""
    a = (asof_by or {}).get("ipan") or SEED_IPAN_ASOF.get((fy, int(kai))) or asof
    return str(D(a) - dt.timedelta(days=1))


def is_nisai(h):
    return h.get("age") in (None, 2)


def overlay(bases, horses, kai, year):
    """公式の 1 回ぶんで起点を置き直す(賞金の無い馬= 他所属は起点から外す)。"""
    for nm, h in horses.items():
        if h.get("prize") is None:
            bases.pop(nm, None)
            continue
        age = h.get("age") or 2
        bases[nm] = {"kai": int(kai), "prize": int(h["prize"]), "age": age, "cls": h.get("cls"),
                     "by": int(year) - age}


def horse_runs(name, by, nar_by_name, jra_by_name):
    """その馬の走(年齢の食い違う同名馬を除く)+中央の走。日付順・重複なし。"""
    out, seen = [], set()
    for r in nar_by_name.get(name, []):
        if r["track"] == "帯広ば":
            continue
        if r.get("birth_date") and int(r["birth_date"][:4]) != by:
            continue
        if r.get("age") is not None and r["age"] != int(r["race_date"][:4]) - by:
            continue
        k = (r["track"], r["race_date"], r["race_no"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    out += jra_by_name.get((name, by), [])
    return sorted(out, key=lambda r: (r["race_date"], r.get("race_no") or 0))


def runners_of(nar_rows):
    seen, rn = set(), defaultdict(list)
    for r in nar_rows:
        k = (r["horse_name"], r["track"], r["race_date"], r["race_no"])
        if k in seen:
            continue
        seen.add(k)
        rn[(r["track"], r["race_date"], r["race_no"])].append(r)
    return rn


def calc_one(b, cut, upto, runs, races, runners):
    """起点(万)に 締め<日付<=upto の走を積む → Acc"""
    wins0 = sum(1 for r in runs if r["race_date"] <= cut and r.get("finish") == 1)
    acc = Acc(b["prize"] // MAN, wins0, races, runners)
    for r in runs:
        if cut < r["race_date"] <= upto and started(r):
            acc.add(r)
    return acc


def calc_all(bases, cuts, upto, nar_by_name, jra_by_name, races, runners, fy):
    out = {}
    for nm, b in sorted(bases.items()):
        cut = cuts[str(b["kai"])]
        acc = calc_one(b, cut, upto, horse_runs(nm, b["by"], nar_by_name, jra_by_name), races, runners)
        prize = acc.val * MAN
        kaku = None
        cls = b.get("cls")
        if fy == CM.KAKUZUKE_FY and not (b["age"] in (None, 2)) and cls and CM.in_label("Ｃ４", cls) is not None:
            kaku = CM.kaku_of(prize)
        fl = sorted({FLAG[f] for f in acc.flags if f in FLAG})
        out[nm] = {"prize": prize, "kaku": kaku, "base": b["prize"], "base_kai": b["kai"], "cls": cls,
                   "age": b["age"], "add": acc.det, "flag": ",".join(fl) or None}
    return out


def check_round(bases, cuts, new, nar_by_name, jra_by_name, races, runners, fy):
    """前の起点+加算(新しい回の締めまで)を新しい公式と照合。"""
    cut_new = ipan_cut(fy, new["kai"], new["asof"], new.get("asof_by"))
    n, match, miss = 0, 0, []
    for nm, h in sorted(new["horses"].items()):
        b = bases.get(nm)
        if h.get("prize") is None or not b:
            continue
        runs = horse_runs(nm, b["by"], nar_by_name, jra_by_name)
        acc = calc_one(b, cuts[str(b["kai"])], cut_new, runs, races, runners)
        n += 1
        if acc.val * MAN == int(h["prize"]):
            match += 1
        else:
            miss.append([nm, acc.val * MAN, int(h["prize"]), b["kai"]])
    return {"kai": int(new["kai"]), "cut": cut_new, "n": n, "match": match, "miss": miss}


def plan(official, hist, prev):
    """→ (bases_before_new, cuts, need_check)。prev(前回の calc)が同じ年度ならそれを、無ければ hist から起点を作る。"""
    fy = official["fy"]
    kai = int(official["kai"])
    year = int(official["asof"][:4])
    bases, cuts = {}, {}
    if prev and prev.get("fy") == fy and prev.get("horses"):
        cuts = dict(prev.get("cuts") or {})
        for nm, h in prev["horses"].items():
            bases[nm] = {"kai": int(h["base_kai"]), "prize": int(h["base"]), "age": h.get("age") or 2,
                         "cls": h.get("cls"), "by": year - (h.get("age") or 2)}
        last = int(prev.get("base_kai") or 0)
    else:
        last = 0
        if hist and hist.get("fy") == fy:
            for k in sorted(int(x) for x in (hist.get("kais") or {})):
                if k >= kai:
                    continue
                v = hist["kais"][str(k)]
                cuts[str(k)] = ipan_cut(fy, k, v["asof"], v.get("asof_by"))
                overlay(bases, v.get("horses") or {}, k, v["asof"][:4])
                last = k
    return bases, cuts, bool(bases) and kai > last


def build(official, hist, prev, nar_rows, jra_by_name, races, upto):
    """通信なしの本体。→ value(nar_meta 'monbetsu_class_calc')"""
    fy = official["fy"]
    kai = int(official["kai"])
    bases, cuts, need = plan(official, hist, prev)
    nar_by_name = defaultdict(list)
    for r in nar_rows:
        nar_by_name[r["horse_name"]].append(r)
    runners = runners_of(nar_rows)
    check = (prev or {}).get("check") if (prev or {}).get("fy") == fy else None
    if need:
        check = check_round(bases, cuts, official, nar_by_name, jra_by_name, races, runners, fy)
        check["new"] = True
    elif check:
        check = dict(check, new=False)
    cuts[str(kai)] = ipan_cut(fy, kai, official["asof"], official.get("asof_by"))
    overlay(bases, official.get("horses") or {}, kai, official["asof"][:4])
    horses = calc_all(bases, cuts, upto, nar_by_name, jra_by_name, races, runners, fy)
    return {"built": f"{dt.datetime.now(JST):%Y-%m-%d %H:%M}", "src": "calc", "fy": fy,
            "base_kai": kai, "base_asof": official["asof"], "upto": upto,
            "cuts": dict(sorted(cuts.items(), key=lambda x: int(x[0]))), "horses": horses, "check": check}


# ------------------------------------------------------------ 取得(PostgREST・対象馬だけ)
def _get(base, key, path):
    out, off = [], 0
    while True:
        req = urllib.request.Request(f"{base}/rest/v1/{path}&limit={PAGE}&offset={off}", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "User-Agent": CM.UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode("utf-8"))
        out += rows
        if len(rows) < PAGE:
            return out
        off += PAGE


def _inq(names):
    return urllib.parse.quote(",".join('"' + n.replace('"', '') + '"' for n in names), safe="")


def fetch(base, key, names, since, cut_min):
    """今年度の走(nar_runs)・締め以降の競走(nar_races)・中央の走(nar_jra_*)を対象馬だけ。"""
    names = sorted(names)
    nar = []
    for i in range(0, len(names), CHUNK):
        nar += _get(base, key, "nar_runs?select=track,race_date,race_no,horse_name,birth_date,age,finish,finish_note"
                    f"&horse_name=in.({_inq(names[i:i + CHUNK])})&race_date=gte.{since}"
                    "&order=track,race_date,race_no,runner_number")
    want = defaultdict(set)
    for r in nar:
        if r["race_date"] > cut_min and r["track"] != "帯広ば":
            want[r["track"]].add(r["race_date"])
    races = {}
    for tr, ds in want.items():
        ds = sorted(ds)
        for i in range(0, len(ds), 80):
            for x in _get(base, key, "nar_races?select=track,race_date,race_no,race_name,race_kind,prize_yen"
                          f"&track=eq.{urllib.parse.quote(tr)}&race_date=in.({','.join(ds[i:i + 80])})"
                          "&order=race_date,race_no"):
                races[(x["track"], x["race_date"], x["race_no"])] = x
    jh = []
    for i in range(0, len(names), CHUNK):
        jh += _get(base, key, "nar_jra_horses?select=kb_horse_id,horse_name,birth_year"
                   f"&horse_name=in.({_inq(names[i:i + CHUNK])})&order=kb_horse_id")
    return nar, races, jra_group(jh, _jra_runs(base, key, jh, cut_min))


def _jra_runs(base, key, jh, cut_min):
    ids = sorted({h["kb_horse_id"] for h in jh})
    rs = []
    for i in range(0, len(ids), CHUNK):
        rs += _get(base, key, "nar_jra_runs?select=kb_horse_id,race_date,race_no,surface,finish,finish_note"
                   f"&kb_horse_id=in.({','.join(ids[i:i + CHUNK])})&race_date=gt.{cut_min}"
                   "&order=kb_horse_id,race_date,race_no")
    return rs


def jra_group(jh, jruns):
    """(馬名, 生年) が 1 頭に決まる馬だけ中央の走を付ける(stage2 と同じ)。"""
    ids = defaultdict(list)
    for h in jh:
        ids[(h["horse_name"], h["birth_year"])].append(h["kb_horse_id"])
    by_id = defaultdict(list)
    for r in jruns:
        by_id[r["kb_horse_id"]].append(dict(r, track="中央"))
    return {k: by_id[v[0]] for k, v in ids.items() if len(v) == 1 and by_id.get(v[0])}


# ------------------------------------------------------------ 便
def note_of(value):
    hs = value["horses"]
    n_add = sum(1 for h in hs.values() if h["add"])
    n_k = sum(1 for h in hs.values() if h["kaku"] and h["prize"] != h["base"]
              and h["kaku"] != CM.kaku_of(h["base"]))
    n_j = sum(1 for h in hs.values() if h["flag"] and "jra_missing" in h["flag"])
    s = f"第{value['base_kai']}回起点 {len(hs)}頭 加算あり{n_add} 級変わる{n_k} 中央欠け{n_j}"
    c = value.get("check")
    ok = True
    if c:
        s += f" 照合 第{c['kai']}回 {c['match']}/{c['n']}"
        if c.get("new") and c["miss"]:
            ok = False
            s += f" 外れ{len(c['miss'])} " + "・".join(m[0] for m in c["miss"][:3])
    return ok, s, (n_add, n_k, n_j)


def run(apply=False, out=None, upto=None):
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        CM.log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2, None
    official = CM.sb_get_meta(base, key, CM.META_KEY)
    if not official or not official.get("horses"):
        CM.log(f"{CM.META_KEY} が読めない")
        return 2, None
    prev = CM.sb_get_meta(base, key, CALC_KEY)
    hist = None if (prev or {}).get("fy") == official["fy"] else CM.sb_get_meta(base, key, CM.HIST_KEY)
    bases, cuts, _ = plan(official, hist, prev)
    names = set(bases) | {n for n, h in official["horses"].items() if h.get("prize") is not None}
    cut_all = list(cuts.values()) + [ipan_cut(official["fy"], official["kai"], official["asof"], official.get("asof_by"))]
    since = f"{official['fy']}-04-01"
    try:
        nar, races, jra = fetch(base, key, names, since, min(cut_all))
    except Exception as e:                              # noqa: BLE001
        CM.log(f"走歴が読めない {type(e).__name__}: {str(e)[:150]}")
        return 2, None
    upto = upto or f"{dt.datetime.now(JST):%Y-%m-%d}"
    value = build(official, hist, prev, nar, jra, races, upto)
    ok, note, _ = note_of(value)
    CM.log(f"走 {len(nar)} / 競走 {len(races)} / 中央の馬 {len(jra)} → {note}")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"{CALC_KEY}.json").write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        CM.log(f"{Path(out) / (CALC_KEY + '.json')} に書き出し")
    if not apply:
        CM.log(f"ドライラン(書かない) heartbeat {BEAT_JOB} {'ok' if ok else 'fail'} {note}")
        return 0, value
    import beat as B
    status, msg = CM.upsert(base, key, "nar_meta", "key", [
        {"key": CALC_KEY, "value": value, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
    if status not in (200, 201):
        CM.log(f"投入失敗 {status} {str(msg)[:150]}")
        B.beat(BEAT_JOB, False, f"投入失敗 {status}")
        return 1, value
    B.beat(BEAT_JOB, ok, note)
    return 0, value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ入れて heartbeat を書く(既定はドライラン)")
    ap.add_argument("--env")
    ap.add_argument("--out", help="value を JSON で書き出す先")
    ap.add_argument("--upto", help="加算の最終日(既定= JST の今日)")
    args = ap.parse_args()
    if args.env:
        CM.load_env(args.env)
    rc, _ = run(args.apply, args.out, args.upto)
    return rc


if __name__ == "__main__":
    sys.exit(main())
