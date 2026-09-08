#!/usr/bin/env python3
"""§79 P3 場ごとの「番組賞金(当サイトの計算)」と「あと◯」を台帳 nar_horse_prize.calc に書く。

設計= docs/proposal_s79_p3_class_calc_20260903.md。対応= **高知**(令和8年度 番組編成要領 4./5./6.(4))・
**帯広ばんえい**(令和8年度 番組編成要領 第2・第7。検算= docs/s79_p3_verify_obihiro_20260903.md 99.27%)・
**佐賀**(令和8年度 番組編成要領 第4-1。状態機械。検算= docs/s79_p3_verify_saga_20260903.md 98.27%)・
**東海(笠松・名古屋)**(番組要綱。1 地区の状態機械。検算= docs/s79_p3_verify_tokai_20260903.md 97.66%・計算した級の精度 ≥96.5%)・
**兵庫(園田・姫路)**(ポイント制。走歴の格組を合図に同期し昇級だけ予測。検算= docs/s79_p3_verify_hyogo_20260903.md 94.4%・表示方針つき 99.0%)。

  py -3.12 -X utf8 cloud/class_calc.py --verify --prefix kochi [--local kochi_ledger.json]   # 検算(書かない)
  py -3.12 -X utf8 cloud/class_calc.py --apply  --prefix kochi --env <.env.nar>               # calc 列を書く
  py -3.12 -X utf8 cloud/class_calc.py --verify --prefix obihiro --local obihiro_ledger.json   # 帯広(--local は pull_obihiro.py の JSON・races 付き)

⛔線の表は Python に写さない。`tests/class_const_dump.mjs` を node で叩いて js/pages/class.js の SYSTEMS を読む(§5.4)。
⛔計算は「当サイトの計算」= src:'calc'。画面は主催者の発表(門別級別表・南関 uma_info・直近の格組)と混ぜない。

高知の規則(要領の写し・2026-09-03 に PDF を再読):
  4.(1)(ア) 番組賞金= 期間内に収得した本賞金の合計。4/1〜8/31 開催= 2年前の 4/1 から編成日まで、
            9/1〜3/31 開催= 2年前の 9/1 から編成日まで(令和8年度は 2024/4/1・2024/9/1)。
  4.(1)(イ) 換算率: 高知の2歳競走 10% / 高知の3歳競走・中央・ダートグレード・他場の2歳競走 30% /
            南関4場 50% / 兵庫 70% / 岩手・金沢・笠松・愛知・北海道・佐賀 90% / 高知 100%。換算後 千円未満切捨。
  5.(1)     2歳・3歳は番組賞金 1,000,000 円に達したら一般格へ編入。5.(4) 3歳格は 9/27 まで(9/28 一斉編入)。
  6.(4)     Ａ 1,100万円超 / Ｂ 1,100万以下 / Ｃ１ 700万以下 / Ｃ２ 460万以下 / Ｃ３上 300万以下 / Ｃ３下 200万以下。
            昇(降)級は 1 サイクル終了毎。
⚠近似(検算の分類で見張る): ①中央の「収得賞金」は付加賞込みの値しか無い→ 1万円未満を切り捨てて本賞金とみなす
  ②編成日は公表されない→ 「レース日の lag 日前まで」で数える(--lag・既定は検算で決めた値)
  ③帯広ばんえい・海外は換算率の表に無い→ 90%(既定)で数え、件数を検算に出す
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(HERE))
from load_nar_official import load_env, upsert            # noqa: E402
from odds import JST, http_get                            # noqa: E402


def log(*a):
    print(*a, flush=True)

T_PRIZE = "nar_horse_prize"
T_CODES = "nar_horse_codes"
GENERAL = "一般格"


# ---------------------------------------------------------------- 定数(class.js から)
def load_consts(node=None):
    """node で tests/class_const_dump.mjs を叩いて SYSTEMS を読む。線の表の正本は class.js。"""
    node = node or os.environ.get("NODE_BIN") or "node"
    out = subprocess.run([node, str(ROOT / "tests" / "class_const_dump.mjs")], capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def _yen(s):
    return int(s.replace(",", "")) * 10000


def prize_lines(system):
    """[['Ａ','1,100万円 超'], ['Ｂ','700万円 超 〜 1,100万円 以下'], ..., ['Ｃ３下','200万円 以下']]
    → 上から順の [(cls, min_exclusive, max_inclusive)]。'超' の額= 下限(その額は含まない)。"""
    rows = []
    for cls, text in system["lines"]:
        nums = re.findall(r"([\d,]+)万円", text)
        if not nums:
            continue
        if "超" in text and "以下" in text:
            rows.append((cls, _yen(nums[0]), _yen(nums[1])))
        elif "超" in text:
            rows.append((cls, _yen(nums[0]), None))
        elif "以下" in text:
            rows.append((cls, 0, _yen(nums[0])))
    return rows


def classify(lines, value):
    """線の表から位置を引く(上から見て value > 下限 の最初の級。どれにも当たらなければ最下級)。"""
    for cls, lo, _hi in lines:
        if value > lo:
            return cls
    return lines[-1][0]


def next_line(lines, cls):
    """1つ上の級とその下限(超なので need = lo + 1000 円: 千円単位で数えるため)。最上級なら None。"""
    idx = [c for c, _, _ in lines].index(cls)
    if idx == 0:
        return None
    up_cls, up_lo, _ = lines[idx - 1]
    return up_cls, up_lo + 1000


# ---------------------------------------------------------------- 高知
KOCHI_RATE = [
    (("浦和", "船橋", "大井", "川崎"), 0.50),
    (("園田", "姫路", "兵庫"), 0.70),
    (("盛岡", "水沢", "岩手", "金沢", "笠松", "名古屋", "弥富", "愛知", "門別", "北海道", "佐賀"), 0.90),
    (("高知",), 1.00),
]
AGE_RACE = re.compile(r"([２３23])[歳才](?!以上|上)")   # 「２歳」「３歳」= 年齢限定。「３歳以上」「３歳上」は一般


def is_age_race(kind, run):
    """kind='２'|'３'。格組(cls)が「２歳」「３歳」か、競走名に「２歳」「３歳」(以上を除く)を含む。"""
    cls = str(run.get("cls") or "")
    name = str(run.get("name") or "")
    if cls.startswith(kind + "歳"):
        return True
    for m in AGE_RACE.finditer(name):
        if m.group(1) in (kind, {"２": "2", "３": "3"}[kind]):
            return True
    return False


def kochi_rate(run):
    """要領 4.(1)(イ)。→ (rate, 分類ラベル)"""
    tr = str(run.get("tr") or "")
    name = str(run.get("name") or "")
    if run.get("jra") or tr.startswith("Ｊ"):
        return 0.30, "中央"
    if re.search(r"Ｊｐｎ|Jpn|ＪＢＣ|JBC", name):
        return 0.30, "ダートグレード"
    if tr == "高知":
        if is_age_race("２", run):
            return 0.10, "高知2歳"
        if is_age_race("３", run):
            return 0.30, "高知3歳"
        return 1.00, "高知"
    if is_age_race("２", run):
        return 0.30, "他場2歳"
    for names, rate in KOCHI_RATE:
        if tr in names:
            return rate, tr
    return 0.90, "表に無い場(" + tr + ")"


def kochi_conv(run):
    """その走の収得賞金 → 番組賞金への換算額(千円未満切捨)。中央は付加賞込みなので 1万円未満を落としてから。"""
    prize = int(run.get("prize") or 0)
    if prize <= 0:
        return 0, None
    rate, label = kochi_rate(run)
    if label == "中央":
        prize = prize // 10000 * 10000
    return int(prize * rate) // 1000 * 1000, label


def kochi_window(d):
    """要領 4.(1)(ア)。開催日 d → 算出対象期間の開始日。"""
    fy = d.year if d.month >= 4 else d.year - 1
    return dt.date(fy - 2, 4, 1) if 4 <= d.month <= 8 else dt.date(fy - 2, 9, 1)


def kochi_value(runs, asof, lag):
    """asof(編成日)時点の番組賞金。数える走= window(asof) <= d < asof - lag。→ (value, Counter(分類→額))"""
    start = kochi_window(asof)
    cutoff = asof - dt.timedelta(days=lag)
    total, by = 0, Counter()
    for r in runs:
        d = _date(r.get("d"))
        if not d or d < start or d >= cutoff:      # 編成日当日の走は数えない(結果はまだ無い)
            continue
        v, label = kochi_conv(r)
        if v:
            total += v
            by[label] += v
    return total, by


def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def kochi_calc(lines, runs, asof, lag, age_at):
    """1頭ぶんの calc。age_at(asof) が 2/3 歳で 100万円未満なら 2歳格/3歳格(5.(1))。"""
    value, by = kochi_value(runs, asof, lag)
    age = age_at(asof)
    out = {"prefix": "kochi", "src": "calc", "asof": asof.isoformat(), "basis": "prize", "value": value,
           "window": kochi_window(asof).isoformat() + "〜", "lag": lag}
    if age in (2, 3) and value < 1_000_000 and not (age == 3 and (asof.month, asof.day) >= (9, 28)):
        out["cls"] = f"{age}歳"
        out["next"] = {"cls": GENERAL, "need": 1_000_000, "gap": 1_000_000 - value}
    else:
        cls = classify(lines, value)
        out["cls"] = cls
        nx = next_line(lines, cls)
        out["next"] = {"cls": nx[0], "need": nx[1], "gap": nx[1] - value} if nx else None
    notes = []
    other = {k: v for k, v in by.items() if k.startswith("表に無い場")}
    if other:
        notes.append("換算率の表に無い場の走を 90% で数えています")
    if 4 <= asof.month <= 8:
        # 9/1 の起算日変更(同じ年度の要領で確定)で落ちる額
        nstart = dt.date(asof.year - 2, 9, 1)
        drop = sum(kochi_conv(r)[0] for r in runs
                   if (d := _date(r.get("d"))) and kochi_window(asof) <= d < nstart)
        if drop:
            out["drop"] = {"on": f"{asof.year}-09-01", "yen": drop}
            notes.append(f"9月1日の数え始めの変更で {drop // 10000}万円ぶん落ちる見込み")
    if notes:
        out["note"] = "・".join(notes)
    return out


# ---------------------------------------------------------------- 帯広ばんえい(令和8年度 番組編成要領 第2・第7・第13)
# 第2-1 収得賞金= 番組で示した賞金額(千円未満切捨)。第2-2 通算収得賞金= 令和5年度以降。
#        ただし 令和5・6・7年度の 牝馬限定の重賞・特別 と 2歳牡馬限定競走 の賞金は 1/2。
# 第7-1 2歳= 本年度収得賞金順(線が無い→ calc を書かない)。
# 第7-2 (1) 5歳以上 と 3・4歳で通算 340万円以上= オープン(1,300万以上)/Ａ1(1,300万未満)/Ａ2(1,000万未満)/
#            Ｂ1(850万未満)/Ｂ2(670万未満)/Ｂ3(550万未満)/Ｂ4(430万未満)。(2) 3・4歳で 340万円未満= Ｃ1(340万未満)/Ｃ2(220万未満)。
# 第13  馬齢は 1月以降 +1(= 年−生年。台帳の age と同じ)。
# ⚠近似: ①牝馬限定は名前の「牝」+既知の牝馬限定重賞名で判定 ②2歳牡馬限定は名前に「２歳」と「牡」 ③編成日は開催初日の4日前=lag で吸収
OBI_START = dt.date(2023, 4, 1)
OBI_HALF_FY = (2023, 2024, 2025)
OBI_FILLY = ("黒ユリ賞", "ヒロインズカップ", "クインカップ", "ばんえいオークス", "ばんえいプリンセス賞", "白雪賞")
OBI_TOKEN = re.compile(r"(オープン|[ＡＢＣ][１２３４])")
OBI_YOUNG_MAX = 3_400_000        # 3・4歳の Ｃ 格の上限(第7-2(2))
FULL = str.maketrans("0123456789", "０１２３４５６７８９")


def _fy(d):
    return d.year if d.month >= 4 else d.year - 1


def obi_lines(system):
    """class.js の '以上/未満' の行 → (main=[(cls, lo_excl, hi)], young=[(cls, lo_excl, hi)])。
    '未満' の行の下限= 次の行の額(千円単位で「以上」になるよう −1000)。最下級の下限は 0。"""
    rows = []
    for cls, text in system["lines"]:
        m = re.search(r"([\d,]+)万円", text)
        if m:
            rows.append((cls.translate(FULL), _yen(m.group(1)), "以上" in text))
    main = [r for r in rows if "歳" not in r[0]]
    young = [r for r in rows if "歳" in r[0]]

    def build(rs):
        out = []
        for i, (cls, t, ge) in enumerate(rs):
            name = re.sub(r"\(.*?\)", "", cls)
            if ge:                                    # 'X万円 以上'
                out.append((name, t - 1000, None))
            else:                                     # 'X万円 未満' = [次の額, X)
                nxt = rs[i + 1][1] if i + 1 < len(rs) else None
                out.append((name, (nxt - 1000) if nxt is not None else 0, t))
        c, _, h = out[-1]
        out[-1] = (c, 0, h)
        return out
    return build(main), build(young)


def obi_half(run, race):
    d = _date(run.get("d"))
    if not d or _fy(d) not in OBI_HALF_FY:
        return False
    name = str((race or {}).get("race_name") or run.get("name") or "")
    kind = str((race or {}).get("race_kind") or "")
    if kind in ("重賞", "特別", "準重賞") and ("牝" in name or any(g in name for g in OBI_FILLY)):
        return True
    return "２歳" in name and "牡" in name


def obi_conv(run, race):
    prize = int(run.get("prize") or 0) // 1000 * 1000
    if prize <= 0:
        return 0
    return prize // 2 // 1000 * 1000 if obi_half(run, race) else prize


def _rkey(r):
    return (str(r.get("d"))[:10], int(r.get("no")) if r.get("no") is not None else None)


def obi_value(runs, asof, lag, races):
    cutoff = asof - dt.timedelta(days=lag)
    total = 0
    for r in runs:
        d = _date(r.get("d"))
        if not d or d < OBI_START or d >= cutoff or r.get("tr") != "帯広":
            continue
        total += obi_conv(r, races.get(_rkey(r)))
    return total


def obi_calc(tables, runs, asof, lag, age_at, races):
    """1頭ぶんの calc。2歳は None(線が無い)。"""
    main, young = tables
    age = age_at(asof)
    if age == 2:
        return None
    value = obi_value(runs, asof, lag, races)
    out = {"prefix": "obihiro", "src": "calc", "asof": asof.isoformat(), "basis": "prize", "value": value,
           "window": OBI_START.isoformat() + "〜", "lag": lag}
    if age in (3, 4) and value < OBI_YOUNG_MAX:
        cls = classify(young, value)
        nx = next_line(young, cls)
        if nx is None:                                # Ｃ1 の上= 340万円で (1) の表に入る(最下級= Ｂ4)
            nx = (main[-1][0], OBI_YOUNG_MAX)
    else:
        cls = classify(main, value)
        nx = next_line(main, cls)
    out["cls"] = cls
    out["next"] = {"cls": nx[0], "need": nx[1], "gap": nx[1] - value} if nx else None
    notes = []
    if age in (3, 4):
        notes.append("3・4歳は通算 340万円未満だとＣ格(要領 第7-2(2))")
    if asof.month <= 3:
        # 年度替わりで通算の数え始めが 1 年ぶん進む見込み(令和8年度要領= 令和5年度以降。次年度も同じ型なら令和6年度以降)
        drop = sum(obi_conv(r, races.get(_rkey(r))) for r in runs
                   if (d := _date(r.get("d"))) and OBI_START <= d < dt.date(2024, 4, 1) and r.get("tr") == "帯広")
        if drop:
            out["drop"] = {"on": f"{asof.year}-04-01", "yen": drop}
            notes.append(f"4月1日の年度替わりで {drop // 10000}万円ぶん落ちる見込み(次年度の要領が同じ型なら)")
    if notes:
        out["note"] = "・".join(notes)
    return out


def obi_actual(name):
    """レース名の末尾の級(混合・2歳・3歳/4歳限定は None)。"""
    n = str(name or "")
    if "混合" in n:
        return None
    m = OBI_TOKEN.findall(n)
    return m[-1] if m else None


def verify_obihiro(tables, rows, births, races, since, lags):
    rep = {}
    order = [c for c, _, _ in tables[0]] + [c for c, _, _ in tables[1]]
    for lag in lags:
        ok, ng, kinds = Counter(), Counter(), Counter()
        samples = defaultdict(list)
        for r in rows:
            runs = r.get("runs") or []
            b = _date(births.get(r["code"]))
            age_at = (lambda d, b=b, r=r: (d.year - b.year) if b else r.get("age"))
            for x in runs:
                d = _date(x.get("d"))
                if not d or d < since or x.get("tr") != "帯広":
                    continue
                race = races.get(_rkey(x))
                # ⛔オラクルは**普通競走だけ**(特別・重賞は下の級の馬も出られる= 名前の級は出走資格でなく格付ではない)
                if race and race.get("race_kind") and race.get("race_kind") != "普通":
                    continue
                actual = obi_actual((race or {}).get("race_name") or x.get("name"))
                if not actual:
                    continue
                c = obi_calc(tables, runs, d, lag, age_at, races)
                if not c:
                    continue
                pred = c["cls"]
                if pred == actual:
                    ok[actual] += 1
                else:
                    ng[actual] += 1
                    earlier = [y for y in runs if (dd := _date(y.get("d"))) and dd < d and y.get("tr") == "帯広"]
                    if not earlier:
                        k = "初戦"
                    elif actual in order and pred in order:
                        k = "実際が上" if order.index(actual) < order.index(pred) else "実際が下"
                    else:
                        k = "表に無い級"
                    kinds[k] += 1
                    if len(samples[k]) < 6:
                        samples[k].append((r.get("horse_name"), d.isoformat(), actual, pred, c["value"], age_at(d)))
        rep[lag] = {"ok": ok, "ng": ng, "kinds": kinds, "samples": samples}
    return rep


def race_map(races):
    return {(str(r["race_date"])[:10], int(r["race_no"])): r for r in races if r.get("race_no") is not None}


def fetch_obihiro(url, key, since):
    today = dt.datetime.now(JST).date()
    q = urllib.parse.quote
    runs = sb_all(url, key, f"nar_runs?select=horse_name,birth_date,race_date&track=eq.{q('帯広ば')}"
                            f"&race_date=gte.{since.isoformat()}")
    names = sorted({r["horse_name"] for r in runs})
    entered = {r["horse_name"] for r in runs if r["race_date"] >= today.isoformat()}
    codes = []
    for i in range(0, len(names), 80):
        inq = ",".join('"' + n + '"' for n in names[i:i + 80])
        codes += sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date&horse_name=in.({q(inq)})")
    cs = sorted({c["code"] for c in codes})
    led = []
    for i in range(0, len(cs), 100):
        led += sb_all(url, key, f"{T_PRIZE}?select=code,horse_name,age,last_cls,local_prize,runs,calc&code=in.({','.join(cs[i:i + 100])})")
    births = {c["code"]: c.get("birth_date") for c in codes}
    races = sb_all(url, key, f"nar_races?select=race_date,race_no,race_name,race_kind&track=eq.{q('帯広ば')}"
                             f"&race_date=gte.{OBI_START.isoformat()}")
    return led, births, entered, race_map(races)


# ---------------------------------------------------------------- 佐賀(令和8年度 番組編成要領 第4-1)
# 番組賞金= 初出走からの通算(1〜5着本賞金・付加賞除く)に、次の率と減額を重ねた**状態機械**(馬ごとに時系列で再現)。
#  加算率 ④: 新規馬(転入時)= 2・3歳の中央/海外 60%・4歳以上の中央/海外 30%・4歳以上の他場地方 50%(2・3歳の他場は 100%)。
#           在籍馬= 佐賀のＪＲＡ認定 30%(他場の認定 50%)・重賞 50%(佐賀記念/サマーチャンピオン 10%・2歳3歳重賞 30%)・
#           九州産重賞とステップ 20%・令和6年度以降の2歳新馬戦 50%・他場遠征 10%・協賛金競走 20%(⚠名前で判別できず=100%)。
#  減額 ③: 8月競馬= 3歳 50%減額(一般格編入)・4歳5歳 −50万円。1月= 6歳が2歳時ぶん・7歳が3歳時ぶん・8歳が4歳時ぶん。
#           新規馬(入厩時)= 4歳 8〜12月 −50万 / 5歳 1〜7月 −50万・8〜12月 −100万 / 6歳 2歳時+100万 / 7歳 2・3歳時+100万 / 8歳以上 2・3・4歳時+100万。
#  格付 (1): Ａ1 1,000万以上 / Ａ2 600万以上 / Ｂ 300万以上 / Ｃ1 150万以上 / Ｃ2 150万未満。2歳格・3歳格(3歳は 300万超で編入・1〜3月を除く・8月に一斉編入)。
#  ⚠近似: ①転出/遠征の区別= 佐賀の走の間が 150 日以内なら遠征 ②8月競馬= 8/1・1月= 1/1 ③3歳の 50% は 8/1 に在籍3歳全頭
#         ④重賞/認定/新馬/九州産は nar_races の名前と種別で判定(他場の走は台帳の短い名前だけ)
SAGA_AWAY_DAYS = 150
SAGA_LOW = ("佐賀記念", "サマーチャンピオン")


def saga_lines(system):
    """'1,000万円 以上' / '600万円 以上 1,000万円 未満' / '150万円 未満' → 上から [(cls, lo_excl, hi)]"""
    rows = []
    for cls, text in system["lines"]:
        if "歳" in cls:
            continue
        nums = [_yen(x) for x in re.findall(r"([\d,]+)万円", text)]
        if not nums:
            continue
        if "以上" in text:
            rows.append((cls.translate(FULL), nums[0] - 1000, nums[1] if len(nums) > 1 else None))
        else:
            rows.append((cls.translate(FULL), 0, nums[0]))
    return rows


def _thou(v):
    return int(v) // 1000 * 1000


def saga_rate_resident(run, race):
    name = str((race or {}).get("race_name") or run.get("name") or "")
    kind = str((race or {}).get("race_kind") or "")
    d = _date(run.get("d"))
    if "認定" in name or "Ｊ認" in name:                  # 台帳の短い名前は「Ｊ認 ２歳－１組」
        return 0.30, "認定"
    if kind == "重賞" or "Ｊｐｎ" in name or "Jpn" in name:
        if any(k in name for k in SAGA_LOW):
            return 0.10, "佐賀記念等"
        if "九州産" in name:
            return 0.20, "九州産重賞"
        if re.search(r"[２３]歳", name):
            return 0.30, "2歳3歳重賞"
        return 0.50, "重賞"
    if "九州産" in name and kind in ("準重賞", "特別"):
        return 0.20, "九州産ステップ"
    if "新馬" in name and d and _fy(d) >= 2024:
        return 0.50, "2歳新馬"
    return 1.00, "佐賀"


# 検算で決めた読み方(2026-09-03・docs/s79_p3_verify_saga_20260903.md): (ハ)「3歳馬の古馬編入後の新規馬は 4歳以上を適用」は
#   **換算率(④)だけ**に効き、入厩時の減額表は 3歳のまま(= 減額なし)。減額も 4歳扱いにすると 96.8%、率も 3歳のままだと 95.8%、
#   2・3歳の他場地方を 50% にしても下がる(97.2%)。→ 率だけ 4歳扱い= 98.27%
def saga_entry_age(a, d):
    return 4 if (a == 3 and d.month >= 8) else a


def saga_cut_age(a, d):
    return a


def saga_rate_entry(run, age_entry):
    """④(イ)(ロ)。age_entry は saga_entry_age を通した年齢。2・3歳の他場地方は要領に率が無い= 100%。"""
    tr = str(run.get("tr") or "")
    jra = bool(run.get("jra")) or tr.startswith("Ｊ") or tr == "海外"
    if age_entry is not None and age_entry <= 3:
        return (0.60, "転入前中央") if jra else (1.00, "転入前地方")
    return (0.30, "転入前中央") if jra else (0.50, "転入前地方")


def saga_state(runs, birth, asof, lag, races, trace=False):
    """asof の lag 日前までを時系列に再現。→ (value, by_age, resident, labels)"""
    cutoff = asof - dt.timedelta(days=lag)
    rs = sorted([r for r in runs if (d := _date(r.get("d"))) and d < cutoff], key=lambda r: str(r.get("d")))
    if not rs:
        return 0, Counter(), False, Counter()
    age = (lambda d: (d.year - birth.year) if birth else None)
    saga_dates = sorted(_date(r.get("d")) for r in rs if r.get("tr") == "佐賀")
    first = _date(rs[0].get("d"))
    events = [("run", _date(r.get("d")), r) for r in rs]
    for y in range(first.year, cutoff.year + 1):
        for md, kind in ((1, "jan"), (8, "aug")):
            e = dt.date(y, md, 1)
            if first < e < cutoff:
                events.append((kind, e, None))
    events.sort(key=lambda t: (t[1], 0 if t[0] != "run" else 1))
    value, by_age, removed = 0, Counter(), set()
    resident, pending, labels = False, [], Counter()
    last_saga = None

    def add(amount, a, label):
        nonlocal value
        amount = _thou(amount)
        if amount <= 0:
            return
        value += amount
        by_age[a] += amount
        labels[label] += amount

    def cut(amount):
        nonlocal value
        value = max(0, value - _thou(amount))

    def next_saga_after(d):
        for x in saga_dates:
            if x > d:
                return x
        return None

    for kind, d, r in events:
        a = age(d)
        if kind == "jan":
            if resident and a in (6, 7, 8) and (a - 4) not in removed:
                cut(by_age[a - 4])
                removed.add(a - 4)
            continue
        if kind == "aug":
            if resident and a == 3:
                cut(value * 0.5)
            elif resident and a in (4, 5):
                cut(500_000)
            continue
        prize = int(r.get("prize") or 0)
        if r.get("tr") == "佐賀":
            if not resident:
                for p in pending:                     # 転入(入厩時格付)= 転入前の走をまとめて換算
                    rate, label = saga_rate_entry(p, saga_entry_age(a, d))
                    add(int(p.get("prize") or 0) * rate, age(_date(p.get("d"))), label)
                pending = []
                a = saga_cut_age(a, d)
                if a == 4 and d.month >= 8:
                    cut(500_000)
                elif a == 5:
                    cut(500_000 if d.month <= 7 else 1_000_000)
                elif a is not None and a >= 6:
                    ages = {6: (2,), 7: (2, 3)}.get(a, (2, 3, 4))
                    cut(sum(by_age[x] for x in ages if x not in removed) + 1_000_000)
                    removed.update(ages)
                resident = True
            rate, label = saga_rate_resident(r, races.get(_rkey(r)))
            add(prize * rate, a, label)
            last_saga = d
        else:
            nx = next_saga_after(d)
            away = resident and last_saga and nx and (nx - last_saga).days <= SAGA_AWAY_DAYS
            if away:
                rate = 0.50 if "認定" in str(r.get("name") or "") else 0.10
                add(prize * rate, a, "遠征")
            else:
                resident = False                      # 転出(戻ったら新規馬として換算)
                pending.append(r)
        if trace:
            print(f"  {d} {kind:3} {str(r.get('tr') if r else ''):4} {str(r.get('prize') if r else ''):>8} → value {value:>10,} resident={resident} pending={len(pending)}")
    if not resident and pending:
        # 転入前(または転出中)の馬= 「asof に転入したら」の値。⛔画面では note で断る
        for p in pending:
            rate, label = saga_rate_entry(p, saga_entry_age(age(asof), asof))
            add(int(p.get("prize") or 0) * rate, age(_date(p.get("d"))), label)
        a = saga_cut_age(age(asof), asof)
        if a == 4 and asof.month >= 8:
            cut(500_000)
        elif a == 5:
            cut(500_000 if asof.month <= 7 else 1_000_000)
        elif a is not None and a >= 6:
            ages = {6: (2,), 7: (2, 3)}.get(a, (2, 3, 4))
            cut(sum(by_age[x] for x in ages if x not in removed) + 1_000_000)
        if trace:
            print(f"  (転入したら) value {value:>10,}")
    return value, by_age, resident, labels


def saga_calc(lines, runs, asof, lag, birth, age_at, races):
    value, by_age, resident, _labels = saga_state(runs, birth, asof, lag, races, trace=os.environ.get('TRACE') == str(runs and runs[0].get('_name')))
    age = age_at(asof)
    out = {"prefix": "saga", "src": "calc", "asof": asof.isoformat(), "basis": "prize", "value": value,
           "window": "初出走〜", "lag": lag}
    if age == 2:
        out["cls"], out["next"] = "２歳", None
    elif age == 3 and (asof.month <= 3 or (asof.month <= 7 and value <= 3_000_000)):
        out["cls"] = "３歳"
        out["next"] = {"cls": GENERAL, "need": 3_001_000, "gap": 3_001_000 - value} if asof.month >= 4 else None
    else:
        cls = classify(lines, value)
        out["cls"] = cls
        nx = next_line(lines, cls)
        out["next"] = {"cls": nx[0], "need": nx[1], "gap": nx[1] - value} if nx else None
    notes = []
    if not resident:
        notes.append("転入前の走を佐賀の換算率で数えた値(要領 第4-1(3)④)")
    if asof.month <= 7 and age in (3, 4, 5):
        notes.append({3: "8月の一般格編入で 50%減額", 4: "8月競馬で 50万円減額", 5: "8月競馬で 50万円減額"}[age] + "の見込み")
    if age in (5, 6, 7) and by_age.get(age - 3):
        notes.append(f"翌1月に{age - 3}歳時の {by_age[age - 3] // 10000}万円が減額される見込み")
    if notes:
        out["note"] = "・".join(notes)
    return out


SAGA_SINGLE = re.compile(r"^(Ａ１|Ａ２|Ｂ|Ｃ１|Ｃ２|２歳|３歳)$")


def verify_saga(lines, rows, births, races, since, lags):
    rep = {}
    order = ["Ａ１", "Ａ２", "Ｂ", "Ｃ１", "Ｃ２"]
    for lag in lags:
        ok, ng, kinds = Counter(), Counter(), Counter()
        samples = defaultdict(list)
        for r in rows:
            runs = r.get("runs") or []
            b = _date(births.get(r["code"]))
            if not b:
                continue
            age_at = (lambda d, b=b: d.year - b.year)
            if runs:
                runs[0]["_name"] = r.get("horse_name")
            for x in runs:
                d = _date(x.get("d"))
                if not d or d < since or x.get("tr") != "佐賀":
                    continue
                actual = norm_cls(x.get("cls"))
                if not SAGA_SINGLE.match(actual):
                    continue
                race = races.get(_rkey(x))
                if not race or race.get("race_kind") != "普通":     # ⛔特別・重賞は上の級にも希望投票できる=格の証拠にしない
                    continue
                c = saga_calc(lines, runs, d, lag, b, age_at, races)
                pred = c["cls"]
                if pred == actual:
                    ok[actual] += 1
                else:
                    ng[actual] += 1
                    earlier = [y for y in runs if (dd := _date(y.get("d"))) and dd < d and y.get("tr") == "佐賀"]
                    if not earlier:
                        k = "転入初戦"
                    elif actual.endswith("歳") or pred.endswith("歳"):
                        k = "2歳3歳の編入"
                    elif actual in order and pred in order:
                        k = "実際が上" if order.index(actual) < order.index(pred) else "実際が下"
                    else:
                        k = "他"
                    kinds[k] += 1
                    if len(samples[k]) < 6:
                        samples[k].append((r.get("horse_name"), d.isoformat(), actual, pred, c["value"], age_at(d)))
        rep[lag] = {"ok": ok, "ng": ng, "kinds": kinds, "samples": samples}
    return rep


def fetch_saga(url, key, since):
    today = dt.datetime.now(JST).date()
    q = urllib.parse.quote
    runs = sb_all(url, key, f"nar_runs?select=horse_name,birth_date,race_date&track=eq.{q('佐賀')}"
                            f"&race_date=gte.{since.isoformat()}")
    names = sorted({r["horse_name"] for r in runs})
    entered = {r["horse_name"] for r in runs if r["race_date"] >= today.isoformat()}
    codes = []
    for i in range(0, len(names), 80):
        inq = ",".join('"' + n + '"' for n in names[i:i + 80])
        codes += sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date&horse_name=in.({q(inq)})")
    cs = sorted({c["code"] for c in codes})
    led = []
    for i in range(0, len(cs), 100):
        led += sb_all(url, key, f"{T_PRIZE}?select=code,horse_name,age,last_cls,local_prize,runs,calc&code=in.({','.join(cs[i:i + 100])})")
    births = {c["code"]: c.get("birth_date") for c in codes}
    races = sb_all(url, key, f"nar_races?select=race_date,race_no,race_name,race_kind&track=eq.{q('佐賀')}"
                             f"&race_date=gte.2022-11-01")
    return led, births, entered, race_map(races)


def main_saga(a):
    consts = load_consts(a.node)
    system = next(s for s in consts["SYSTEMS"] if s["id"] == "saga")
    lines = saga_lines(system)
    log("線(class.js):", lines)
    since = _date(a.since)
    if a.local:
        d = json.load(open(a.local, encoding="utf-8"))
        rows, births = d["ledger"], {c["code"]: c.get("birth_date") for c in d["codes"]}
        entered, races = set(), race_map(d["races"])
    else:
        if a.env:
            load_env(a.env)   # ⛔#465 クラウドは環境変数だけ(--env 無しで 他場.env を探して SystemExit していた)
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        rows, births, entered, races = fetch_saga(url, key, since)
    log(f"台帳 {len(rows)} 頭(佐賀の走が {since} 以降にある馬)・レース {len(races)}")
    if a.verify:
        lags = [a.lag] if a.lag is not None else [0, 3, 7, 10]
        rep = verify_saga(lines, rows, births, races, since, lags)
        print_report(rep, f"佐賀 検算(オラクル= 次に走ったレースの格組・{since} 以降の佐賀の走)")
        return 0
    if a.apply:
        lag = a.lag if a.lag is not None else SAGA_LAG
        today = dt.datetime.now(JST).date()
        out = []
        for r in rows:
            runs = r.get("runs") or []
            local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
            last_tr = local[0].get("tr") if local else None
            if last_tr != "佐賀" and r.get("horse_name") not in entered:
                continue
            b = _date(births.get(r["code"]))
            if not b:
                continue
            age_at = (lambda d, b=b: d.year - b.year)
            c = saga_calc(lines, runs, today, lag, b, age_at, races)
            if c and c["cls"] != "２歳":
                out.append({"code": r["code"], "calc": c})
        log(f"佐賀 calc を書く: {len(out)} 頭(lag={lag})")
        for i in range(0, len(out), 200):
            st, msg = upsert(url, key, T_PRIZE, "code", out[i:i + 200])
            if st not in (200, 201):
                log("upsert 失敗", st, msg)
                return 1
        log("完了")
        return 0
    return 0


# ---------------------------------------------------------------- 東海(笠松・名古屋。令和8年度 番組要綱・番組賞金は東海地区で共通)
# 番組賞金= 東海在籍中の収得賞金×換算率の通算(状態機械)。
#  在籍中の率(名古屋 10(2)・笠松 (2)): ダートグレード/ネクストスター 30%・ＪＲＡ認定と2・3歳重賞 40%・2歳新馬 50%・
#     2・3歳準重賞 50%(笠松)/P競走 60%・古馬重賞 60〜70%・その他 100%。他地区の交流= 50%(ダートグレード 30%)・中央= 30%。
#  転入(名古屋 6(3)・笠松 5(1)オ): 収得賞金×転入換算表(年齢 2〜4/5〜6/7歳以上 × 出所: 中央 35/25/20(笠松 30/20/15)・
#     認定/南関/ダートグレード 50/40/30(笠松 45/35/25)・兵庫高知 80/60/50・他の地方 100/80/60)+中央歴があれば 70万円。
#     一般でＡ級なら段(450〜900万→450万・〜1,800万→650万・〜3,000万→1,000万・以上→1,500万)。
#  再転入(9か月未満・笠松 6/名古屋 7): 転出前の番組賞金+転出中の賞金の換算。
#  2歳・3歳の編入(名古屋 10(6)・笠松 (4)): 2歳 450万/3歳 440万に達したら 控除 200万(生え抜き)/100万(地方転入)/70万(中央歴)。
#     10月(第13回名古屋後)の3歳一斉編入= 50%/30%/20%(上限 200/100/70万)。
#  四半期調整(名古屋 10(7)・笠松 10(6)): 6/9/12/3月末の開催後、一般格の馬の番組賞金 25% から前回調整以降の収得ぶんを引いた額を控除。
#     前回調整以降に一般格で勝った馬・調整額を超えて収得した馬は控除しない。転入前の成績は調整の対象外。
#  ⚠近似: ①調整日= 7/1・10/1・1/1・4/1 ②競走区分は nar_races の種別と名前で読む(SPⅠ/Ⅱ・P競走の別は無い= 古馬重賞 60%・2・3歳重賞 40%)
#         ③転出/遠征= 東海の走の間が 270 日以内なら遠征 ④転入直後の初回調整は飛ばす
TOKAI_TRACKS = ("笠松", "名古屋")
TOKAI_PREFIX = {"笠松": "kasamatsu", "名古屋": "nagoya"}
NANKAN_TRACKS = ("浦和", "船橋", "大井", "川崎")
HYOGO_KOCHI = ("園田", "姫路", "高知")
TOKAI_AWAY_DAYS = int(os.environ.get("TOKAI_AWAY", "365"))   # 転出/遠征の境(検算で 365 が最良)
TOKAI_ENTRY = {   # 出所 → (2〜4歳, 5〜6歳, 7歳以上)
    "名古屋": {"jra": (0.35, 0.25, 0.20), "mid": (0.50, 0.40, 0.30), "hk": (0.80, 0.60, 0.50), "nar": (1.00, 0.80, 0.60)},
    "笠松": {"jra": (0.30, 0.20, 0.15), "mid": (0.45, 0.35, 0.25), "hk": (0.80, 0.60, 0.50), "nar": (1.00, 0.80, 0.60)},
}
TOKAI_A_STEP = ((30_000_000, 15_000_000), (18_000_000, 10_000_000), (9_000_000, 6_500_000), (4_500_000, 4_500_000))
TOKAI_CUT = {"native": 2_000_000, "local": 1_000_000, "jra": 700_000}
TOKAI_CUT_RATE = {"native": 0.50, "local": 0.30, "jra": 0.20}
TOKAI_Y2, TOKAI_Y3 = 4_500_000, 4_400_000
# 検算(2026-09-03・docs/s79_p3_verify_tokai_20260903.md)= 採用 "jqeti"・転出 365 日・lag 3 → 97.66%
#   (実際の級ごと: ３歳 99.9 / Ｃ級 98.6 / Ｂ級 93.0。計算した級ごとの精度: Ｃ級 96.9 / Ｂ級 96.5 = 画面に出す判断の物差し)。
#   j=+70万(中央歴) q=四半期調整 e=編入控除 t=岐阜↔愛知の移籍は換算し直し i=孤立した1走は転入でない
#   (試して落ちたもの: f=転入直後の初回調整を飛ばす p=調整の基礎から転入額を除く r=四半期に走った馬だけ調整 n z)
TOKAI_V = os.environ.get("TOKAI_V", "jqeti")
TOKAI_PARKED = False
TOKAI_ADJ = {}        # 場 → 調整日の一覧(四半期末の月の最終開催日の翌日。tokai_adj_dates で作る)
TOKAI_BLOCKS = {}     # 場 → [(開催初日, 最終日)](tokai_adj_dates で作る)


def tokai_adj_dates(races):
    """(track, date, no) → row の辞書から、場ごとの調整日= 6/9/12/3 月の最終開催日+1 を作る。
    ⚠公式は名古屋= 第7/13/19/26回の終了後・笠松= 月末開催の終了後。開催回の数え方が公式と一致しないので月で読む。"""
    days = defaultdict(set)
    for (tr, d, _no) in races:
        days[tr].add(_date(d))
    out = {}
    for tr, ds in days.items():
        blocks = []                                # 連続する開催日を 1 開催に(2 日以内の空きは同じ開催)
        for d in sorted(ds):
            if blocks and (d - blocks[-1][1]).days <= 2:
                blocks[-1][1] = d
            else:
                blocks.append([d, d])
        TOKAI_BLOCKS[tr] = [(a, b) for a, b in blocks]
        last = {}
        for a, b in blocks:                        # 開催の月= **終了日**の月(3/31 始まりの開催は 4 月= 新年度の第1回)
            if b.month in (6, 9, 12, 3):
                k = (b.year, b.month)
                if k not in last or b > last[k]:
                    last[k] = b
        out[tr] = sorted(v + dt.timedelta(days=1) for v in last.values())
    return out


def tokai_lines(system):
    return saga_lines(system)


def _is_jra(run):
    tr = str(run.get("tr") or "")
    return bool(run.get("jra")) or tr.startswith("Ｊ") or tr == "海外"


def _dg(name):
    return bool(re.search(r"Ｊｐｎ|Jpn|ＪＢＣ|JBC|ネクストスター", name))


def tokai_rate_resident(run, race):
    name = str((race or {}).get("race_name") or run.get("name") or "")
    kind = str((race or {}).get("race_kind") or "")
    young = bool(re.search(r"[２３]歳", name))
    if _dg(name):
        return 0.30, "ダートグレード"
    if "認定" in name or "Ｊ認" in name:
        return 0.40, "認定"
    if "新馬" in name:
        return 0.50, "新馬"
    if kind == "重賞":
        return (0.40, "2歳3歳重賞") if young else (0.60, "古馬重賞")
    if kind == "準重賞" and young:
        return 0.50, "2歳3歳準重賞"
    return 1.00, "東海"


def tokai_rate_away(run):
    name = str(run.get("name") or "")
    if _is_jra(run):
        return 0.30, "中央遠征"
    return (0.30, "ダートグレード遠征") if _dg(name) else (0.50, "他地区遠征")


def tokai_rate_entry(run, age_entry, track):
    tbl = TOKAI_ENTRY[track]
    col = 0 if age_entry is None or age_entry <= 4 else (1 if age_entry <= 6 else 2)
    tr = str(run.get("tr") or "")
    name = str(run.get("name") or "")
    if _is_jra(run):
        mul = float(os.environ.get("TOKAI_JMUL", "1"))
        return tbl["jra"][col] * mul, "転入前中央"
    if tr in NANKAN_TRACKS or "認定" in name or "Ｊ認" in name or _dg(name):
        return tbl["mid"][col], "転入前南関等"
    if tr in HYOGO_KOCHI:
        return tbl["hk"][col], "転入前兵庫高知"
    return tbl["nar"][col], "転入前地方"


def tokai_cutoff(asof, lag, track=None):
    """編成に使う成績の締め。TOKAI_BLOCKLAG=K なら「asof の K 日以上前に終わった直近の開催の最終日+1」(場= track)。"""
    k = os.environ.get("TOKAI_BLOCKLAG")
    if k and track in TOKAI_BLOCKS:
        lim = asof - dt.timedelta(days=int(k))
        ends = [b for _a, b in TOKAI_BLOCKS[track] if b <= lim]
        if ends:
            return max(ends) + dt.timedelta(days=1)
    return asof - dt.timedelta(days=lag)


def tokai_state(runs, birth, asof, lag, races, trace=False, track=None):
    """→ (value, resident, origin, young, entry_track)"""
    cutoff = tokai_cutoff(asof, lag, track)
    rs = sorted([r for r in runs if (d := _date(r.get("d"))) and d < cutoff], key=lambda r: str(r.get("d")))
    if not rs:
        return 0, False, "native", True, None
    age = (lambda d: (d.year - birth.year) if birth else None)
    tk_dates = sorted(_date(r.get("d")) for r in rs if r.get("tr") in TOKAI_TRACKS)
    tk_seq = sorted(((_date(r.get("d")), r.get("tr")) for r in rs if r.get("tr") in TOKAI_TRACKS))
    home = None                                    # 所属(岐阜=笠松 / 愛知=名古屋)

    def next_tk_track(d):
        for x, t in tk_seq:
            if x > d:
                return t
        return None

    def next_any_track(d):
        for p in rs:
            if _date(p.get("d")) > d:
                return p.get("tr")
        return None

    def prev_track(d):
        t = None
        for p in rs:
            if _date(p.get("d")) < d:
                t = p.get("tr")
        return t

    def fresh_value(before, track, a):
        """転入馬格付け= それまでの全収得賞金を track の換算表(年齢 a の列)で換算 + 中央歴 70万 → Ａ級の段"""
        v = 0
        for p in before:
            rate, _label = tokai_rate_entry(p, a, track)
            v += _thou(int(p.get("prize") or 0) * rate)
        if any(_is_jra(p) for p in before) and "j" in TOKAI_V and                 ("z" not in TOKAI_V or any(_is_jra(p) and int(p.get("prize") or 0) > 0 for p in before)):
            v += int(os.environ.get("TOKAI_JADD", "700000"))
        return v
    first = _date(rs[0].get("d"))
    events = [("run", _date(r.get("d")), r) for r in rs]
    if "m" in TOKAI_V or not TOKAI_ADJ:
        for y in range(first.year, cutoff.year + 1):
            for md in (1, 4, 7, 10):
                e = dt.date(y, md, 1)
                if first < e < cutoff:
                    events.append(("adj", e, None))
    else:
        for tr, ds in TOKAI_ADJ.items():
            for e in ds:
                if first < e < cutoff:
                    events.append(("adj", e, tr))
    events.sort(key=lambda t: (t[1], 0 if t[0] != "run" else 1))
    recent = []                                    # 直近の東海の走の場(所属の推定)
    value = 0
    resident, pending, last_tk, entry_track, entry_date = False, [], None, None, None
    young = True                                   # 2歳格/3歳格にいるか(一般格に入ったら False)
    gained, won = 0, False                         # 前回調整以降の一般格での収得・勝ち
    ran_q = False                                  # 前回調整以降に一般格で走ったか
    entry_value = 0                                # 転入時の換算額(調整の対象外にする読み方 p)
    has_jra, has_other = False, False
    tk_ever = False
    origin = "native"

    def next_tk_after(d):
        for x in tk_dates:
            if x > d:
                return x
        return None

    def a_step(v):
        for lo, val in TOKAI_A_STEP:
            if v >= lo:
                return val
        return v

    def cur_young(d, v):
        a = age(d)
        if a == 2:
            return v < TOKAI_Y2
        if a == 3 and d.month <= 9:
            return v < TOKAI_Y3
        return False

    for kind, d, r in events:
        a = age(d)
        if kind == "adj":
            if r is not None and home is not None and r != home:
                continue                           # 他県の調整日(所属でない場)は飛ばす
            if "q" in TOKAI_V and resident and not young and entry_date and ("f" not in TOKAI_V or entry_date < d - dt.timedelta(days=90))                     and ("r" not in TOKAI_V or ran_q):
                base = max(0, value - entry_value) if "p" in TOKAI_V else value
                if "n" in TOKAI_V:
                    base = max(0, base - gained)       # 読み方 n: 前回以降の収得ぶんは 25% の基礎からも除く
                adj = _thou(base * 0.25)
                if not won and gained < adj:
                    value = max(0, value - (adj - gained))
            gained, won, ran_q = 0, False, False
            if d.month in (9, 10) and resident and young and a == 3:  # 3歳の一斉編入(9月末の開催後)
                cut = min(_thou(value * TOKAI_CUT_RATE[origin]), TOKAI_CUT[origin]) if "e" in TOKAI_V else 0
                value = max(0, value - cut)
                young = False
            if trace:
                print(f"  {d} adj  → value {value:>10,} young={young}")
            continue
        prize = int(r.get("prize") or 0)
        if _is_jra(r):
            has_jra = True
        elif r.get("tr") not in TOKAI_TRACKS:
            has_other = True
        if r.get("tr") in TOKAI_TRACKS:
            if resident and "t" in TOKAI_V and home and r.get("tr") != home and next_tk_track(d) == r.get("tr")                     and not (a is not None and a <= 3 and d.month <= 9):
                # 岐阜↔愛知の移籍(交流の1走でなく続けて走る)= 転入馬として換算し直す(名古屋 6(3)・笠松 5(1)オ。2歳・3歳9月までは引き継ぐ)
                before = [p for p in rs if _date(p.get("d")) < d]
                value = fresh_value(before, r.get("tr"), a)
                origin = "jra" if has_jra else ("local" if has_other else "native")
                young = cur_young(d, value)
                if not young and value >= 4_500_000:
                    value = a_step(value)
                home, entry_date, entry_track = r.get("tr"), d, r.get("tr")
                gained, won, ran_q = 0, False, False
                if trace:
                    print(f"  {d} 移籍 → {r.get('tr')} 換算し直し value {value:>10,}")
            if not resident:
                track = r.get("tr")
                # (b) 孤立した 1 走(前後が東海以外・ＪＲＡ交流など)は転入ではない= 他場の走として持ち越す
                prev_tr = prev_track(d)
                if "i" in TOKAI_V and prev_tr not in TOKAI_TRACKS and next_any_track(d) not in TOKAI_TRACKS                         and next_any_track(d) is not None:
                    pending.append(r)
                    if trace:
                        print(f"  {d} 交流 {track}(転入でない)")
                    continue
                re_entry = tk_ever and last_tk and (d - last_tk).days < TOKAI_AWAY_DAYS
                if re_entry:
                    for p in pending:
                        rate, label = tokai_rate_entry(p, a, track)
                        value += _thou(int(p.get("prize") or 0) * rate)
                else:
                    origin = "jra" if has_jra else ("local" if has_other else "native")
                    value = fresh_value([p for p in rs if _date(p.get("d")) < d], track, a)   # (a) 全走を換算
                pending = []
                young = cur_young(d, value)
                if not young and not re_entry:
                    value = a_step(value) if value >= 4_500_000 else value
                resident, entry_track, entry_date = True, track, d
                home = track
                entry_value = value
                gained, won = 0, False
                tk_ever = True
            recent = (recent + [r.get("tr")])[-5:]
            rate, label = tokai_rate_resident(r, races.get((r.get("tr"),) + _rkey(r)) if races else None)
            got = _thou(prize * rate)
            value += got
            if young and not cur_young(d, value):                        # 線に達した→ 編入(控除)
                value = max(0, value - (TOKAI_CUT[origin] if "e" in TOKAI_V else 0))
                young = False
            elif not young:
                gained += got
                ran_q = True
                if r.get("fin") == 1:
                    won = True
            last_tk = d
        else:
            nx = next_tk_after(d)
            away = resident and last_tk and nx and (nx - last_tk).days <= TOKAI_AWAY_DAYS
            if away:
                rate, label = tokai_rate_away(r)
                got = _thou(prize * rate)
                value += got
                if not young:
                    gained += got
            else:
                if resident:
                    resident = False
                pending.append(r)
        if trace:
            print(f"  {d} run  {str(r.get('tr')):4} {prize:>9,} → value {value:>10,} res={resident} young={young} pend={len(pending)}")
    if not resident and pending:
        a = age(asof)
        track = entry_track or "名古屋"
        re_entry = tk_ever and last_tk and (asof - last_tk).days < TOKAI_AWAY_DAYS
        if not re_entry:
            value = 0
            origin = "jra" if has_jra else ("local" if has_other else "native")
        for p in pending:
            rate, label = tokai_rate_entry(p, a, track)
            value += _thou(int(p.get("prize") or 0) * rate)
        if not re_entry and has_jra and "j" in TOKAI_V:
            value += int(os.environ.get("TOKAI_JADD", "700000"))
        young = cur_young(asof, value)
        if not young and not re_entry:
            value = a_step(value) if value >= 4_500_000 else value
        if trace:
            print(f"  (転入したら) value {value:>10,} young={young}")
    return value, resident, origin, young, entry_track


def tokai_calc(lines, runs, asof, lag, birth, age_at, races, prefix):
    tr_on = os.environ.get("TRACE") and runs and runs[0].get("_name") == os.environ.get("TRACE")
    value, resident, origin, young, entry_track = tokai_state(runs, birth, asof, lag, races, trace=bool(tr_on),
                                                              track={v: k for k, v in TOKAI_PREFIX.items()}.get(prefix))
    age = age_at(asof)
    out = {"prefix": prefix, "src": "calc", "asof": asof.isoformat(), "basis": "prize", "value": value,
           "window": "東海転入〜", "lag": lag}
    if age == 2 and young:
        out["cls"] = "２歳"
        out["next"] = {"cls": GENERAL, "need": TOKAI_Y2, "gap": TOKAI_Y2 - value}
    elif age == 3 and young:
        out["cls"] = "３歳"
        out["next"] = {"cls": GENERAL, "need": TOKAI_Y3, "gap": TOKAI_Y3 - value}
    else:
        cls = classify(lines, value)
        out["cls"] = cls
        nx = next_line(lines, cls)
        out["next"] = {"cls": nx[0], "need": nx[1], "gap": nx[1] - value} if nx else None
    notes = []
    if not resident:
        notes.append("転入前の走を東海の換算表で数えた値(要綱の転入馬格付け)")
    if young:
        notes.append("編入のとき " + {"native": "200万円", "local": "100万円", "jra": "70万円"}[origin] + " が控除されます")
    else:
        notes.append("四半期ごとの調整(25%)の見込みは出していません")
    out["note"] = "・".join(notes)
    return out


TOKAI_CLS = re.compile(r"^(Ａ|Ｂ|Ｃ|２歳|３歳)")


def tokai_actual(cls):
    m = TOKAI_CLS.match(str(cls or "").translate(FULL))
    if not m:
        return None
    c = m.group(1)
    return c + "級" if c in ("Ａ", "Ｂ", "Ｃ") else c


def verify_tokai(lines, rows, births, races, since, lags):
    rep = {}
    order = ["Ａ級", "Ｂ級", "Ｃ級"]
    for lag in lags:
        ok, ng, kinds = Counter(), Counter(), Counter()
        samples = defaultdict(list)
        for r in rows:
            runs = r.get("runs") or []
            b = _date(births.get(r["code"]))
            if not b:
                continue
            if os.environ.get("TRACE") and r.get("horse_name") != os.environ.get("TRACE"):
                continue
            if runs:
                runs[0]["_name"] = r.get("horse_name")
            age_at = (lambda d, b=b: d.year - b.year)
            for x in runs:
                d = _date(x.get("d"))
                if not d or d < since or x.get("tr") not in TOKAI_TRACKS:
                    continue
                race = races.get((x.get("tr"),) + _rkey(x))
                if not race or race.get("race_kind") != "普通":
                    continue
                actual = tokai_actual(x.get("cls"))
                if not actual:
                    continue
                c = tokai_calc(lines, runs, d, lag, b, age_at, races, TOKAI_PREFIX[x.get("tr")])
                pred = c["cls"]
                if pred == actual:
                    ok[actual] += 1
                else:
                    ng[actual] += 1
                    earlier = [y for y in runs if (dd := _date(y.get("d"))) and dd < d and y.get("tr") in TOKAI_TRACKS]
                    if not earlier:
                        k = "転入初戦"
                    elif actual.endswith("歳") or pred.endswith("歳"):
                        k = "2歳3歳の編入"
                    elif actual in order and pred in order:
                        k = "実際が上" if order.index(actual) < order.index(pred) else "実際が下"
                    else:
                        k = "他"
                    kinds[k] += 1
                    if len(samples[k]) < 6:
                        samples[k].append((r.get("horse_name"), d.isoformat(), x.get("tr"), actual, pred, c["value"], age_at(d)))
        rep[lag] = {"ok": ok, "ng": ng, "kinds": kinds, "samples": samples}
    return rep


_RBT = {}


def races_by_track(races, track):
    """(track, date, no) → row の辞書から、その場ぶんの (date, no) → row を作る(メモ)。"""
    if track not in _RBT:
        _RBT[track] = {(k[1], k[2]): v for k, v in races.items() if k[0] == track}
    return _RBT[track]


def fetch_tokai(url, key, since):
    today = dt.datetime.now(JST).date()
    q = urllib.parse.quote
    led, births, entered, races = [], {}, set(), {}
    seen = set()
    for tr in TOKAI_TRACKS:
        runs = sb_all(url, key, f"nar_runs?select=horse_name,birth_date,race_date&track=eq.{q(tr)}"
                                f"&race_date=gte.{since.isoformat()}")
        names = sorted({r["horse_name"] for r in runs})
        entered |= {r["horse_name"] for r in runs if r["race_date"] >= today.isoformat()}
        codes = []
        for i in range(0, len(names), 80):
            inq = ",".join('"' + n + '"' for n in names[i:i + 80])
            codes += sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date&horse_name=in.({q(inq)})")
        cs = sorted({c["code"] for c in codes} - seen)
        seen |= set(cs)
        for i in range(0, len(cs), 100):
            led += sb_all(url, key, f"{T_PRIZE}?select=code,horse_name,age,last_cls,local_prize,runs,calc&code=in.({','.join(cs[i:i + 100])})")
        births.update({c["code"]: c.get("birth_date") for c in codes})
        rr = sb_all(url, key, f"nar_races?select=race_date,race_no,race_name,race_kind&track=eq.{q(tr)}&race_date=gte.2022-11-01")
        for r in rr:
            if r.get("race_no") is not None:
                races[(tr, str(r["race_date"])[:10], int(r["race_no"]))] = r
    return led, births, entered, races


def main_tokai(a):
    consts = load_consts(a.node)
    system = next(s for s in consts["SYSTEMS"] if s["id"] == "nagoya")
    lines = tokai_lines(system)
    log("線(class.js):", lines)
    since = _date(a.since)
    if a.local:
        rows, births, races, seen = [], {}, {}, set()
        for f, tr in zip(a.local.split(","), TOKAI_TRACKS):
            d = json.load(open(f, encoding="utf-8"))
            for r in d["ledger"]:
                if r["code"] not in seen:
                    rows.append(r)
                    seen.add(r["code"])
            births.update({c["code"]: c.get("birth_date") for c in d["codes"]})
            for r in d["races"]:
                if r.get("race_no") is not None:
                    races[(tr, str(r["race_date"])[:10], int(r["race_no"]))] = r
        entered = set()
    else:
        if a.env:
            load_env(a.env)   # ⛔#465 クラウドは環境変数だけ(--env 無しで 他場.env を探して SystemExit していた)
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        rows, births, entered, races = fetch_tokai(url, key, since)
    log(f"台帳 {len(rows)} 頭(東海の走が {since} 以降にある馬)・レース {len(races)}")
    TOKAI_ADJ.update(tokai_adj_dates(races))
    log("調整日:", {k: [x.isoformat() for x in v if x.year >= 2025] for k, v in TOKAI_ADJ.items()})
    if a.verify:
        lags = [a.lag] if a.lag is not None else [0, 3, 7]
        rep = verify_tokai(lines, rows, births, races, since, lags)
        print_report(rep, f"東海(笠松・名古屋) 検算(オラクル= 次に走った普通競走の格・{since} 以降)")
        return 0
    if a.apply:
        if TOKAI_PARKED and os.environ.get("TOKAI_FORCE") != "1":
            log("東海は検算が 95% 未満(Ｂ級 86.9%)なので calc を書かない(docs/s79_p3_verify_tokai_20260903.md)")
            return 0
        lag = a.lag if a.lag is not None else TOKAI_LAG
        today = dt.datetime.now(JST).date()
        out = []
        for r in rows:
            runs = r.get("runs") or []
            local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
            last_tr = local[0].get("tr") if local else None
            if last_tr not in TOKAI_TRACKS and r.get("horse_name") not in entered:
                continue
            b = _date(births.get(r["code"]))
            if not b:
                continue
            tr = last_tr if last_tr in TOKAI_TRACKS else "名古屋"
            age_at = (lambda d, b=b: d.year - b.year)
            c = tokai_calc(lines, runs, today, lag, b, age_at, races, TOKAI_PREFIX[tr])
            if c:
                out.append({"code": r["code"], "calc": c})
        log(f"東海 calc を書く: {len(out)} 頭(lag={lag})")
        for i in range(0, len(out), 200):
            st, msg = upsert(url, key, T_PRIZE, "code", out[i:i + 200])
            if st not in (200, 201):
                log("upsert 失敗", st, msg)
                return 1
        log("完了")
        return 0
    return 0


# ---------------------------------------------------------------- 兵庫(園田・姫路。令和8年度 番組要綱 第5 格付・別表1)
# ポイント制(3歳以上。令和8年7月4日から。それまでは4歳以上+3歳単独)。2歳は番組賞金順(格付なし= calc を書かない)。
#  加算(第5-3): 普通・重賞 1着100/2着24/3着12/4着8/5着6、グレード競走 100/34/18/10/8。他場交流も含む。同着は按分。
#  昇級(第5-2(2)): 合計が現級の上限を超えたら昇級し、**昇級クラスの最下限ポイントに戻す**(重賞で昇級したときは戻さない)。
#  重賞1着(第5-2(5))= ポイントに関係なく1クラス上。格上挑戦で1着= そのクラスの最下限に昇級。
#  降級(第5-2(3)): 格付修正(概ね2か月ごと)で、同一クラスの近3走の着順合計の多い順に降級= **点では決まらない(順位)**。
#     降級馬の点= 前クラスの最下限−60(Ｃ３へは60・3歳Ｃ２へは90)。Ａ１とＣ３は対象外。
#  転入(別表1): クラスは所属と勝数で決まる表・点は各クラスの最下限(3歳Ｃ２は49)。
# ⛔読み方: 降級は順位で決まるので**予測しない**。走歴の格組(単独クラスの普通・特別競走)を合図に状態を合わせ、
#   昇級だけをポイントで予測する。オラクル= 次に走った単独クラスの走の格組(昇級の予測と、降級を写した後の追従)。
HYOGO_TRACKS = ("園田", "姫路")
HYOGO_PREFIX = {"園田": "sonoda", "姫路": "himeji"}
HYOGO_PTS = {1: 100, 2: 24, 3: 12, 4: 8, 5: 6}
HYOGO_PTS_G = {1: 100, 2: 34, 3: 18, 4: 10, 5: 8}
HYOGO_OLD_LABEL = re.compile(r"^(Ａ１|Ａ２|Ｂ１|Ｂ２|Ｃ１|Ｃ２|Ｃ３)[一二三四五]?$")
HYOGO_Y3_LABEL = re.compile(r"^(Ａ|Ｂ|Ｃ１|Ｃ２)[一二三]?$")
HYOGO_Y3_END = dt.date(2026, 7, 4)     # 令和8年度: 7/4 から 3歳以上(3歳単独の終わり)


def hyogo_tables(system):
    """class.js の '760 以上' / '630〜759' → old=[(cls, lo, hi)] 上から、y3= 3歳単独の表。"""
    old, y3 = [], []
    for cls, text in system["lines"]:
        m = re.findall(r"\d+", text)
        if not m:
            continue
        lo = int(m[0])
        hi = int(m[1]) if len(m) > 1 else None
        name = cls.translate(FULL)
        if name.startswith("3歳") or name.startswith("３歳"):
            y3.append((name.replace("3歳", "").replace("３歳", ""), lo, hi))
        else:
            old.append((name, lo, hi))
    return old, y3


def _cls_of_pts(table, pts):
    for cls, lo, _hi in table:
        if pts >= lo:
            return cls
    return table[-1][0]


def _lo(table, cls):
    return next(lo for c, lo, _ in table if c == cls)


def _hi(table, cls):
    return next(hi for c, _, hi in table if c == cls)


def _up(table, cls):
    names = [c for c, _, _ in table]
    i = names.index(cls)
    return names[i - 1] if i > 0 else None


def hyogo_label(run, race):
    """→ (table_key 'old'|'y3', cls) / 単独クラスでなければ None。"""
    cls = str(run.get("cls") or "").translate(FULL)
    name = str((race or {}).get("race_name") or run.get("name") or "")
    kind = str((race or {}).get("race_kind") or "")
    if kind == "重賞" or "重賞" in cls or "交流" in cls or "認定" in cls or "初出" in cls:
        return None
    young = bool(re.search(r"[２３]歳", name)) and "以上" not in name
    m = HYOGO_OLD_LABEL.match(cls)
    if m and not young:
        return ("old", m.group(1))
    m = HYOGO_Y3_LABEL.match(cls)
    if m and (young or m.group(1) in ("Ａ", "Ｂ")):
        return ("y3", m.group(1))
    return None


def _graded(name):
    return bool(re.search(r"Ｊｐｎ|Jpn|ＪＢＣ|JBC|ＧＩ|GI|ＧＩＩ|ＧＩＩＩ|G1|G2|G3", name))


def hyogo_state(runs, birth, asof, lag, races, trace=False):
    """→ dict(cls, table, pts, resident, synced, note)"""
    cutoff = asof - dt.timedelta(days=lag)
    rs = sorted([r for r in runs if (d := _date(r.get("d"))) and d < cutoff], key=lambda r: str(r.get("d")))
    age = (lambda d: (d.year - birth.year) if birth else None)
    st = {"cls": None, "table": None, "pts": 0, "resident": False, "synced": False, "via_graded": False}
    tables = hyogo_state.tables
    # 同期に使う走(単独クラスの普通・特別)の並び= 格上挑戦(次で元の級に戻る)を見分けるための先読み
    labels = []
    for r in rs:
        if r.get("tr") in HYOGO_TRACKS:
            lab = hyogo_label(r, races.get((r.get("tr"),) + _rkey(r)))
            labels.append((str(r.get("d"))[:10], lab))
    def next_label(d):
        for x, lab in labels:
            if x > d and lab:
                return lab
        return None

    for r in rs:
        d = _date(r.get("d"))
        tr = r.get("tr")
        race = races.get((tr,) + _rkey(r)) if tr in HYOGO_TRACKS else None
        a = age(d)
        if tr in HYOGO_TRACKS:
            lab = hyogo_label(r, race)
            if lab:
                key, cls = lab
                table = tables[key]
                if st["cls"] is None or st["table"] != key:
                    # 初回(転入・2歳→3歳・3歳→古馬)= その走の格組に合わせる。点は、在籍中に積んだ点がその級の幅に
                    # 収まっていればそのまま(2歳の走の点も数える)・外れていれば最下限(別表1。3歳Ｃ２の転入は 49)
                    lo, hi = _lo(table, cls), _hi(table, cls)
                    inside = st["resident"] and st["pts"] >= lo and (hi is None or st["pts"] <= hi)
                    pts = st["pts"] if inside else (49 if (key == "y3" and cls == "Ｃ２" and not st["resident"]) else lo)
                    st.update(cls=cls, table=key, pts=pts)
                    st["synced"] = True
                    st["resident"] = True
                elif cls != st["cls"]:
                    names = [c for c, _, _ in table]
                    if names.index(cls) < names.index(st["cls"]):
                        # 上の級の走= 格上挑戦(次の走で元に戻る)か、こちらが見落とした昇級か
                        nl = next_label(str(d))
                        if nl and nl[0] == key and nl[1] == st["cls"] and r.get("fin") != 1:
                            pass                                  # 格上挑戦
                        else:
                            st.update(cls=cls, pts=max(st["pts"], _lo(table, cls)))
                    else:
                        # 降級(格付修正)= 1段ごとに 前クラスの最下限−60(Ｃ３へは60・3歳Ｃ２へは90)。2段落ちたら2回
                        cur = st["cls"]
                        while cur != cls:
                            nxt = names[names.index(cur) + 1]
                            if key == "old" and nxt == "Ｃ３":
                                st["pts"] = 60
                            elif key == "y3" and nxt == "Ｃ２":
                                st["pts"] = 90
                            else:
                                st["pts"] = max(0, _lo(table, cur) - 60)
                            cur = nxt
                        st["cls"] = cls
            st["resident"] = True
        elif not st["resident"]:
            continue                                          # 転入前の走は点にしない(別表1で格付)
        # 着順の点(在籍中・他場交流含む)
        fin = r.get("fin")
        if isinstance(fin, int) and 1 <= fin <= 5 and not st["cls"] and st["resident"]:
            name = str((race or {}).get("race_name") or r.get("name") or "")
            st["pts"] += (HYOGO_PTS_G if _graded(name) else HYOGO_PTS)[fin]     # 2歳(格付なし)の点も積む
        if isinstance(fin, int) and 1 <= fin <= 5 and st["cls"]:
            name = str((race or {}).get("race_name") or r.get("name") or "")
            pts = (HYOGO_PTS_G if _graded(name) else HYOGO_PTS)[fin]
            st["pts"] += pts
            table = tables[st["table"]]
            kind = str((race or {}).get("race_kind") or "")
            if fin == 1 and (kind == "重賞" or "重賞" in str(r.get("cls") or "")):
                up = _up(table, st["cls"])
                if up:
                    st["cls"] = up                            # 重賞1着= 点に関係なく1つ上(点は戻さない)
                    st["via_graded"] = True
            else:
                hi = _hi(table, st["cls"])
                if hi is not None and st["pts"] > hi:
                    up = _up(table, st["cls"])
                    if up:
                        st["cls"], st["pts"] = up, _lo(table, up)   # 昇級= 最下限に戻す
        if trace:
            print(f"  {d} {str(tr):4} fin={fin} → {st['table']} {st['cls']} pts={st['pts']}")
    return st


def hyogo_calc(tables, runs, asof, lag, birth, age_at, races, prefix):
    hyogo_state.tables = {"old": tables[0], "y3": tables[1]}
    st = hyogo_state(runs, birth, asof, lag, races, trace=bool(os.environ.get("TRACE") and runs and runs[0].get("_name") == os.environ.get("TRACE")))
    age = age_at(asof)
    if age is not None and age <= 2:
        return None
    if not st["cls"]:
        return None
    key = st["table"]
    # 3歳単独→古馬(令和8年度は 7/4 から 3歳以上): 編入後の級は点の写しでは決まらない(実測: 3歳Ａ→Ｃ１/Ｂ２/Ｃ２に散る)。
    # ⛔推定しない= 編入後に古馬の格組で走るまで calc を出さない
    if key == "y3" and (age >= 4 or asof >= HYOGO_Y3_END):
        return None
    cls = st["cls"]
    table = tables[0] if key == "old" else tables[1]
    hi = _hi(table, cls)
    up = _up(table, cls)
    out = {"prefix": prefix, "src": "calc", "asof": asof.isoformat(), "basis": "point", "value": st["pts"],
           "window": "在籍中の着順ポイント", "lag": lag, "cls": ("3歳" if key == "y3" else "") + cls}
    out["next"] = {"cls": ("3歳" if key == "y3" else "") + up, "need": hi + 1, "gap": hi + 1 - st["pts"]} if up and hi is not None else None
    # 表示方針(検算 2026-09-03): 線を越えている計算(gap<=0)は初期ポイントの不確かさが出やすい= 出さない(hide)。
    # 公式の直近の格組と計算の級が違うときも出さない(apply 側で last_cls と突き合わせる)
    out["hide"] = bool(out["next"] and out["next"]["gap"] <= 0)
    notes = ["降級は格付修正(概ね2か月ごと)で近3走の着順順で決まるので予測していません"]
    if key == "y3":
        notes.append("3歳単独の表(古馬クラス編入まで)")
    out["note"] = "・".join(notes)
    return out


def verify_hyogo(tables, rows, births, races, since, lags):
    rep = {}
    for lag in lags:
        ok, ng, kinds = Counter(), Counter(), Counter()
        samples = defaultdict(list)
        for r in rows:
            runs = r.get("runs") or []
            b = _date(births.get(r["code"]))
            if not b:
                continue
            if os.environ.get("TRACE") and r.get("horse_name") != os.environ.get("TRACE"):
                continue
            if runs:
                runs[0]["_name"] = r.get("horse_name")
            age_at = (lambda d, b=b: d.year - b.year)
            prev = None                                   # 直前の単独クラスの格組(同じ表)= 降級の検出に使う
            for x in sorted(runs, key=lambda y: str(y.get("d"))):
                d = _date(x.get("d"))
                if not d or x.get("tr") not in HYOGO_TRACKS:
                    continue
                race = races.get((x.get("tr"),) + _rkey(x))
                lab = hyogo_label(x, race)
                if not lab or not race or race.get("race_kind") not in ("普通", "特別"):
                    continue
                demoted = False
                if prev and prev[0] == lab[0]:
                    names = [c for c, _, _ in (tables[0] if lab[0] == "old" else tables[1])]
                    demoted = names.index(lab[1]) > names.index(prev[1])
                prev_lab, prev = prev, lab
                if d < since:
                    continue
                if demoted:
                    kinds["降級(予測しない・除外)"] += 1        # 格付修正の降級= 順位で決まる。オラクルから外す
                    continue
                if lab[0] == "y3" and d >= HYOGO_Y3_END:
                    kinds["3歳限定戦(7/4 以降・除外)"] += 1   # 3歳以上に編入した後の3歳限定戦= 出走資格であって格ではない
                    continue
                actual = ("3歳" if lab[0] == "y3" else "") + lab[1]
                c = hyogo_calc(tables, runs, d, lag, b, age_at, races, HYOGO_PREFIX[x.get("tr")])
                if not c:
                    continue
                pred = c["cls"]
                # 画面に出す条件(表示方針)= 計算の級が直前の格組と同じ & 線を越えていない(next.gap > 0)。その精度を別に数える
                prev_actual = ("3歳" if prev_lab[0] == "y3" else "") + prev_lab[1] if prev_lab else None
                if prev_actual == pred and c.get("next") and c["next"]["gap"] > 0:
                    kinds["表示対象"] += 1
                    if pred == actual:
                        kinds["表示対象で一致"] += 1
                if pred == actual:
                    ok[actual] += 1
                else:
                    order = [("" if i == 0 else "3歳") + cc for i, t in enumerate(tables) for cc, _, _ in t]
                    if pred in order and actual in order and order.index(pred) - order.index(actual) == 1 and x.get("fin") != 1                             and nxt_same(runs, x, tables, races) :
                        kinds["1級上に格上挑戦(次で戻る・除外)"] += 1     # 要綱 第5-2(4)= 1つ上の競走には出られる
                        continue
                    ng[actual] += 1
                    if pred not in order or actual not in order or pred.startswith("3歳") != actual.startswith("3歳"):
                        k = "表の切替(3歳↔古馬)"
                    else:
                        k = "実際が上" if order.index(actual) < order.index(pred) else "実際が下"
                    kinds[k] += 1
                    if len(samples[k]) < 6:
                        samples[k].append((r.get("horse_name"), d.isoformat(), actual, pred, c["value"], age_at(d)))
        rep[lag] = {"ok": ok, "ng": ng, "kinds": kinds, "samples": samples}
    return rep


def nxt_same(runs, x, tables, races):
    """x の次の単独クラスの走が、x の1つ下(= 元の級)に戻っているか。"""
    d0 = str(x.get("d"))
    lab0 = hyogo_label(x, races.get((x.get("tr"),) + _rkey(x)))
    for y in sorted(runs, key=lambda y: str(y.get("d"))):
        if str(y.get("d")) <= d0 or y.get("tr") not in HYOGO_TRACKS:
            continue
        lab = hyogo_label(y, races.get((y.get("tr"),) + _rkey(y)))
        if not lab:
            continue
        if lab[0] != lab0[0]:
            return False
        names = [c for c, _, _ in (tables[0] if lab[0] == "old" else tables[1])]
        return names.index(lab[1]) == names.index(lab0[1]) + 1
    return False


def fetch_hyogo(url, key, since):
    today = dt.datetime.now(JST).date()
    q = urllib.parse.quote
    led, births, entered, races, seen = [], {}, set(), {}, set()
    for tr in HYOGO_TRACKS:
        runs = sb_all(url, key, f"nar_runs?select=horse_name,birth_date,race_date&track=eq.{q(tr)}"
                                f"&race_date=gte.{since.isoformat()}")
        names = sorted({r["horse_name"] for r in runs})
        entered |= {r["horse_name"] for r in runs if r["race_date"] >= today.isoformat()}
        codes = []
        for i in range(0, len(names), 80):
            inq = ",".join('"' + n + '"' for n in names[i:i + 80])
            codes += sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date&horse_name=in.({q(inq)})")
        cs = sorted({c["code"] for c in codes} - seen)
        seen |= set(cs)
        for i in range(0, len(cs), 100):
            led += sb_all(url, key, f"{T_PRIZE}?select=code,horse_name,age,last_cls,local_prize,runs,calc&code=in.({','.join(cs[i:i + 100])})")
        births.update({c["code"]: c.get("birth_date") for c in codes})
        rr = sb_all(url, key, f"nar_races?select=race_date,race_no,race_name,race_kind&track=eq.{q(tr)}&race_date=gte.2022-11-01")
        for r in rr:
            if r.get("race_no") is not None:
                races[(tr, str(r["race_date"])[:10], int(r["race_no"]))] = r
    return led, births, entered, races


def main_hyogo(a):
    consts = load_consts(a.node)
    system = next(s for s in consts["SYSTEMS"] if s["id"] == "hyogo")
    tables = hyogo_tables(system)
    log("表(class.js) 古馬:", tables[0])
    log("表(class.js) 3歳:", tables[1])
    since = _date(a.since)
    if a.local:
        rows, births, races, seen = [], {}, {}, set()
        for f, tr in zip(a.local.split(","), HYOGO_TRACKS):
            d = json.load(open(f, encoding="utf-8"))
            for r in d["ledger"]:
                if r["code"] not in seen:
                    rows.append(r)
                    seen.add(r["code"])
            births.update({c["code"]: c.get("birth_date") for c in d["codes"]})
            for r in d["races"]:
                if r.get("race_no") is not None:
                    races[(tr, str(r["race_date"])[:10], int(r["race_no"]))] = r
        entered = set()
    else:
        if a.env:
            load_env(a.env)   # ⛔#465 クラウドは環境変数だけ(--env 無しで 他場.env を探して SystemExit していた)
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        rows, births, entered, races = fetch_hyogo(url, key, since)
    log(f"台帳 {len(rows)} 頭(兵庫の走が {since} 以降にある馬)・レース {len(races)}")
    if a.verify:
        lags = [a.lag] if a.lag is not None else [0, 3, 7]
        rep = verify_hyogo(tables, rows, births, races, since, lags)
        print_report(rep, f"兵庫(園田・姫路) 検算(オラクル= 次に走った単独クラスの普通・特別競走の格組・{since} 以降)")
        return 0
    if a.apply:
        lag = a.lag if a.lag is not None else HYOGO_LAG
        today = dt.datetime.now(JST).date()
        out = []
        for r in rows:
            runs = r.get("runs") or []
            local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
            last_tr = local[0].get("tr") if local else None
            if last_tr not in HYOGO_TRACKS and r.get("horse_name") not in entered:
                continue
            b = _date(births.get(r["code"]))
            if not b:
                continue
            tr = last_tr if last_tr in HYOGO_TRACKS else "園田"
            age_at = (lambda d, b=b: d.year - b.year)
            c = hyogo_calc(tables, runs, today, lag, b, age_at, races, HYOGO_PREFIX[tr])
            if not c:
                continue
            # 公式の直近の格組(last_cls)と計算の級が違う馬は出さない(表示方針)
            lab = hyogo_label({"cls": r.get("last_cls"), "name": ""}, None)
            official = (("3歳" if lab[0] == "y3" else "") + lab[1]) if lab else None
            if c.get("hide") or (official and official != c["cls"]):
                c["hide"] = True
                c["next"] = None
            out.append({"code": r["code"], "calc": c})
        log(f"兵庫 calc を書く: {len(out)} 頭(lag={lag})")
        for i in range(0, len(out), 200):
            st, msg = upsert(url, key, T_PRIZE, "code", out[i:i + 200])
            if st not in (200, 201):
                log("upsert 失敗", st, msg)
                return 1
        log("完了")
        return 0
    return 0


# ---------------------------------------------------------------- 検算(オラクル A= 次に走ったレースの格組)
SINGLE = re.compile(r"^(Ａ|Ｂ|Ｃ１|Ｃ２|Ｃ３|２歳|３歳)$")
FULL = str.maketrans("0123456789", "０１２３４５６７８９")


def norm_cls(c):
    c = str(c or "").translate(FULL)
    c = re.sub(r"[上下]$", "", c)           # Ｃ３上/下 は格組に出ない
    return c


def verify_kochi(lines, rows, births, since, lags):
    """rows= 台帳(runs 付き)。高知の走(格組が単独)ごとに、その直前までの計算と実際の格組を比べる。"""
    rep = {}
    for lag in lags:
        ok, ng = Counter(), Counter()
        kinds = Counter()
        samples = defaultdict(list)
        for r in rows:
            runs = r.get("runs") or []
            b = _date(births.get(r["code"]))
            age_at = (lambda d, b=b, r=r: (d.year - b.year) if b else None)
            for x in runs:
                d = _date(x.get("d"))
                if not d or d < since or x.get("tr") != "高知":
                    continue
                actual = norm_cls(x.get("cls"))
                if not SINGLE.match(actual):
                    continue
                c = kochi_calc(lines, runs, d, lag, age_at)
                pred = norm_cls(c["cls"])
                if pred == actual:
                    ok[actual] += 1
                else:
                    ng[actual] += 1
                    # 分類: 転入(高知の走がこれが初めて)/上に格付(実際が上)/下に格付/3歳の扱い
                    earlier = [y for y in runs if (dd := _date(y.get("d"))) and dd < d and y.get("tr") == "高知"]
                    if not earlier:
                        k = "転入初戦"
                    elif actual.endswith("歳") or pred.endswith("歳"):
                        k = "2歳3歳の編入"
                    else:
                        order = [norm_cls(cc) for cc, _, _ in lines]
                        k = "実際が上" if order.index(actual) < order.index(pred) else "実際が下"
                    kinds[k] += 1
                    if len(samples[k]) < 5:
                        samples[k].append((r.get("horse_name"), d.isoformat(), actual, pred, c["value"]))
        rep[lag] = {"ok": ok, "ng": ng, "kinds": kinds, "samples": samples}
    return rep


def print_report(rep, title):
    print(f"# {title}")
    for lag, r in rep.items():
        tot = sum(r["ok"].values()) + sum(r["ng"].values())
        hit = sum(r["ok"].values())
        print(f"\n## lag={lag}日: 一致 {hit}/{tot} = {hit / tot * 100:.2f}%")
        print("| 格組 | 走数 | 一致 | 一致率 |\n|---|---|---|---|")
        for cls in sorted(set(r["ok"]) | set(r["ng"])):
            n = r["ok"][cls] + r["ng"][cls]
            print(f"| {cls} | {n} | {r['ok'][cls]} | {r['ok'][cls] / n * 100:.1f}% |")
        print("不一致の分類:", dict(r["kinds"]))
        for k, s in r["samples"].items():
            print(f"  {k}:", s)


# ---------------------------------------------------------------- DB
def sb_all(url, key, path, page=1000):
    out, lo = [], 0
    while True:
        raw = http_get(f"{url}/rest/v1/{path}", {"apikey": key, "Authorization": f"Bearer {key}",
                                                  "Accept": "application/json", "Range": f"{lo}-{lo + page - 1}"})
        rows = json.loads(raw.decode("utf-8"))
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def fetch_kochi(url, key, since):
    """高知の台帳= ①最後の地方の走が高知の馬 ②今日以降に高知の出馬表に載っている馬(転入)。"""
    today = dt.datetime.now(JST).date()
    q = urllib.parse.quote
    runs = sb_all(url, key, f"nar_runs?select=horse_name,birth_date,race_date&track=eq.{q('高知')}"
                            f"&race_date=gte.{since.isoformat()}")
    names = sorted({r["horse_name"] for r in runs})
    entered = {r["horse_name"] for r in runs if r["race_date"] >= today.isoformat()}
    codes = []
    for i in range(0, len(names), 80):
        inq = ",".join('"' + n + '"' for n in names[i:i + 80])
        codes += sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date&horse_name=in.({q(inq)})")
    cs = sorted({c["code"] for c in codes})
    led = []
    for i in range(0, len(cs), 100):
        led += sb_all(url, key, f"{T_PRIZE}?select=code,horse_name,age,last_cls,local_prize,runs,calc&code=in.({','.join(cs[i:i + 100])})")
    births = {c["code"]: c.get("birth_date") for c in codes}
    return led, births, entered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="kochi")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--env", default=None)
    ap.add_argument("--local", default=None, help="pull_kochi.py が吐いた JSON(検算をオフラインで)")
    ap.add_argument("--since", default="2026-04-01", help="検算に使う高知の走の始まり(令和8年度の線が効く範囲)")
    ap.add_argument("--lag", type=int, default=None, help="編成日= レース日の何日前か(既定 KOCHI_LAG)")
    ap.add_argument("--node", default=None)
    a = ap.parse_args()
    if a.prefix == "obihiro":
        return main_obihiro(a)
    if a.prefix == "saga":
        return main_saga(a)
    if a.prefix in ("tokai", "kasamatsu", "nagoya"):
        return main_tokai(a)
    if a.prefix in ("hyogo", "sonoda", "himeji"):
        return main_hyogo(a)
    if a.prefix != "kochi":
        raise SystemExit("対応= kochi / obihiro(設計 §6 の順に足す)")
    consts = load_consts(a.node)
    system = next(s for s in consts["SYSTEMS"] if s["id"] == "kochi")
    lines = prize_lines(system)
    log("線(class.js):", [(c, lo, hi) for c, lo, hi in lines])
    since = _date(a.since)

    if a.local:
        d = json.load(open(a.local, encoding="utf-8"))
        rows, births = d["ledger"], {c["code"]: c.get("birth_date") for c in d["codes"]}
        entered = set()
    else:
        if a.env:
            load_env(a.env)   # ⛔#465 クラウドは環境変数だけ(--env 無しで 他場.env を探して SystemExit していた)
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        rows, births, entered = fetch_kochi(url, key, since)
    log(f"台帳 {len(rows)} 頭(高知の走が {since} 以降にある馬)")

    if a.verify:
        lags = [a.lag] if a.lag is not None else [0, 3, 7, 10, 14]
        rep = verify_kochi(lines, rows, births, since, lags)
        print_report(rep, f"高知 検算(オラクル= 次に走ったレースの格組・{since} 以降の高知の走)")
        return 0

    if a.apply:
        lag = a.lag if a.lag is not None else KOCHI_LAG
        today = dt.datetime.now(JST).date()
        out = []
        for r in rows:
            runs = r.get("runs") or []
            local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
            last_tr = local[0].get("tr") if local else None
            if last_tr != "高知" and r.get("horse_name") not in entered:
                continue
            b = _date(births.get(r["code"]))
            age_at = (lambda d, b=b, r=r: (d.year - b.year) if b else r.get("age"))
            c = kochi_calc(lines, runs, today, lag, age_at)
            if last_tr != "高知":
                c["note"] = ("転入前の場の走を高知の換算率で数えた値(要領 4.(2))" + ("・" + c["note"] if c.get("note") else ""))
            out.append({"code": r["code"], "calc": c})
        log(f"高知 calc を書く: {len(out)} 頭(lag={lag})")
        for i in range(0, len(out), 200):
            st, msg = upsert(url, key, T_PRIZE, "code", out[i:i + 200])
            if st not in (200, 201):
                log("upsert 失敗", st, msg)
                return 1
        log("完了")
        return 0
    ap.print_help()
    return 0


def main_obihiro(a):
    consts = load_consts(a.node)
    system = next(s for s in consts["SYSTEMS"] if s["id"] == "obihiro")
    tables = obi_lines(system)
    log("線(class.js) 5歳以上/3・4歳340万以上:", tables[0])
    log("線(class.js) 3・4歳340万未満:", tables[1])
    since = _date(a.since)
    if a.local:
        d = json.load(open(a.local, encoding="utf-8"))
        rows, births = d["ledger"], {c["code"]: c.get("birth_date") for c in d["codes"]}
        entered, races = set(), race_map(d["races"])
    else:
        if a.env:
            load_env(a.env)   # ⛔#465 クラウドは環境変数だけ(--env 無しで 他場.env を探して SystemExit していた)
        url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        rows, births, entered, races = fetch_obihiro(url, key, since)
    log(f"台帳 {len(rows)} 頭(帯広の走が {since} 以降にある馬)・レース {len(races)}")

    if a.verify:
        lags = [a.lag] if a.lag is not None else [0, 3, 5, 7, 10, 14]
        rep = verify_obihiro(tables, rows, births, races, since, lags)
        print_report(rep, f"帯広ばんえい 検算(オラクル= 次に走ったレース名の級・{since} 以降の帯広の走)")
        return 0

    if a.apply:
        lag = a.lag if a.lag is not None else OBI_LAG
        today = dt.datetime.now(JST).date()
        out = []
        for r in rows:
            runs = r.get("runs") or []
            local = [x for x in runs if not x.get("jra") and x.get("fin") is not None]
            last_tr = local[0].get("tr") if local else None
            if last_tr != "帯広" and r.get("horse_name") not in entered:
                continue
            b = _date(births.get(r["code"]))
            age_at = (lambda d, b=b, r=r: (d.year - b.year) if b else r.get("age"))
            c = obi_calc(tables, runs, today, lag, age_at, races)
            if c:
                out.append({"code": r["code"], "calc": c})
        log(f"帯広 calc を書く: {len(out)} 頭(lag={lag})")
        for i in range(0, len(out), 200):
            st, msg = upsert(url, key, T_PRIZE, "code", out[i:i + 200])
            if st not in (200, 201):
                log("upsert 失敗", st, msg)
                return 1
        log("完了")
        return 0
    return 0


KOCHI_LAG = 0   # 検算(--verify)で決める。docs/s79_p3_verify_20260903.md 参照
OBI_LAG = 0     # 検算(--verify --prefix obihiro)で決める
SAGA_LAG = 0    # 検算(--verify --prefix saga)で決める
TOKAI_LAG = 3   # 検算(--verify --prefix tokai): lag 3〜8 で 97.66% の台地・0 は 97.47%
HYOGO_LAG = 0   # 検算(--verify --prefix hyogo): 0 が最良(7 で 93.1%)。表示方針つき精度 99.0%

if __name__ == "__main__":
    sys.exit(main())
