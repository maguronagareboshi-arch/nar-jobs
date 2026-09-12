# -*- coding: utf-8 -*-
"""本体 cloud: 展開の見立て(全15場・§99a 位置だけ)。

各馬の**直近5走の1番目のコーナー通過順**(公式・§41-B)から 逃げ/先行/差し/追込 の型を推定し、
レースごとに1枚ぶんの材料を nar_meta `tenkai:YYYY-MM-DD` へ入れる。画面(js/pages/race.js)は
出馬表タブの一番上にカードを出す。

  出力 = {"built":"2026-09-05T07:20+09:00",
          "races": {"saga-1": {"n":10,"k":8,
                               "lead":[3],"front":[1,7],"mid":[2,5,9],"back":[4,8],"none":[6,10],
                               "h":{"3":{"s":"逃げ","p":0.12,"m":4}, …},
                               "w":"単騎(3番)・前が手薄"}, …}}
  - 型が1頭も付かないレースは races に入れない(画面はカードごと出さない=推定を薄めない)
  - §99b(2026-09-05)で **テン**(`h[馬番].ten` 秒・`tn` 走数)と **ペース見込み**(`pace`/`pace_by`/`pace_ten`)を
    **足した**。⛔§99a のキー(n/k/lead/front/mid/back/none/h の s,p,m/w)は1バイトも変えていない
  - ⛔帯広ばは対象外(コーナーの通過順が無い)
  - ⛔`SHOW_TRACKS` に無い場は races に**入れない**(画面で隠すのでなく配らない)

  py -3.12 -X utf8 cloud/tenkai.py --env pipeline/.env.nar                # ドライラン(今日+明日)
  py -3.12 -X utf8 cloud/tenkai.py --env pipeline/.env.nar --apply        # nar_meta へ upsert
  py -3.12 -X utf8 cloud/tenkai.py --env pipeline/.env.nar --days 2026-09-05,2026-09-06
  py -3.12 -X utf8 cloud/tenkai.py --env pipeline/.env.nar --backtest 30  # 検品(場ごとの的中率)
  py -3.12 -X utf8 cloud/tenkai.py --env pipeline/.env.nar --backtest 60 --pace  # §99b ペース見込みの検品
  py -3.12 -X utf8 cloud/tenkai.py --selftest                             # 通過順の読み方だけ(通信なし)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
  ⛔#465: --env が無いときは**環境変数だけ**で動く(手元の .env を探しに行かない)。
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔1000行キャップ(#8): 全取得はページングで回す。⛔updated_at を必ず送る(#155)。
⛔URL 長(#365): in.() は 80 件ずつに割る。
"""
import argparse
import datetime as dt
import io
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = "nar-jobs/1.0"
META_PREFIX = "tenkai:"
BANEI = "帯広ば"
JST = dt.timezone(dt.timedelta(hours=9))
# ⛔cloud/baba.py と同じ表(§5.4: 1か所で決まっているものを2か所に複製しない…が、cloud 同士は
#   互いを import しない約束なので写す。**中身は baba.py と1文字も違わない**)
TRACK2PREFIX = {"門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa",
                "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
                "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji",
                "高知": "kochi", "佐賀": "saga"}
# 出す場。⛔画面で隠すのでなく**配らない**。初期値= 14場全部。--backtest の結果で主担当が絞る
SHOW_TRACKS = set(TRACK2PREFIX)

# ⛔閾値は定数1か所。小サンプルから動かさない(バックテストで出す/出さないを場ごとに決めるだけ)
LEAD_P = 0.2            # これ以下の位置なら「その走は前に行った」
FRONT_P = 0.4           # 平均位置がこれ以下なら 先行
MID_P = 0.7             # これ以下なら 差し / それより後ろは 追込
MIN_RUNS = 2            # 通過順の読めた走がこれ未満なら型を付けない
PAST_DAYS = 365         # 過去走を見る窓
N_RUNS = 5              # 見る走の数
SAME_TRACK_MIN = 3      # 同じ場の走がこれ以上あれば同じ場だけで見る
CHUNK = 80              # in.() の分割
WINDOW_STEP = 30        # --backtest の取得を割る窓(日)。⛔1年を一息に引くと重い/500 が返る
THIN_FRONT = 0.25       # (逃げ+先行)/k がこれ以下なら「前が手薄」
THICK_FRONT = 0.5       # これ以上なら「前が多い」
BACKTEST_GATE = 0.5     # 1角先頭率がこれ未満の場は SHOW_TRACKS から外す(主担当が判断)

# ---- §99b テン(前半3F)とペース見込み。⛔前半3F があるのはこの6場だけ
TEN_TRACKS = ("高知", "門別", "大井", "船橋", "川崎", "浦和")
# ペース見込みを出す場。⛔`--backtest 60 --pace` のゲートに届かない場は外す(2026-09-05 実測):
#   大井65%(123R) 門別61%(115R) 船橋55%(80R) 高知68%(34R) は通過 /
#   **川崎・浦和は chihou_results.first3f がほとんど無い**(1年で 390走・378走。大井は13,392走)ので
#   テンの付く馬が足りず測れない= pace を出さない。テン(小バッジ)はある馬にだけ出る
# ⛔Fable 2026-09-05: 高知は外す。60日のバックテストで「いつも速い」と言うだけ(74%)に負ける(68%)=
#   情報量が無い(n=34・8/3〜9/4 休催で標本が薄い)。高知の開催が 60 日たまったら --backtest --pace で測り直して戻す。
#   テンの小バッジは高知でも出る(PACE_TRACKS はペース見込みだけ)
PACE_TRACKS = {"monbetsu", "ooi", "funabashi"}
TEN_MIN_RUNS = 3        # テンを出す最少走数(⛔3走未満は出さない)
TEN_STD_MIN = 30        # 場×距離の標準を出す最少標本(小サンプルから基準を作らない)
KOCHI_BAND = 0.4        # 高知は ±0.4 秒(kochi-pace-definition)。他場は場ごとの四分位
CHIHOU_MIN_DIST = 1200  # ⛔1200m 未満の chihou_results.first3f は「距離−600m 通過」で別物(js/data.js 296行)
PACE_GATE_HIT = 0.45    # 見込みと実際の一致率がこれ未満の場は pace を出さない
PACE_GATE_OPP = 0.15    # 逆(速い↔遅い)がこれを超える場も出さない

STYLES = ("逃げ", "先行", "差し", "追込")
SLOT = {"逃げ": "lead", "先行": "front", "差し": "mid", "追込": "back"}


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None):
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(r, timeout=120) as x:
        return x.status, x.read().decode("utf-8")


N_REQ = [0]


def rows_all(base, key, path):
    """⛔offset で送るので `order=` は**一意**にすること(2026-09-05 実測: race_date だけで並べると
    39,475 行中 1,951 行が重複し、同じだけ抜ける。しかも引くたびに中身が変わる)。"""
    out, off = [], 0
    while True:
        N_REQ[0] += 1
        _, body = req(base, key, f"{path}&limit=1000&offset={off}")
        c = json.loads(body)
        out.extend(c)
        if len(c) < 1000:
            return out
        off += 1000


def rows_window(base, key, tmpl, lo, hi, step=WINDOW_STEP):
    """`tmpl` の {lo}/{hi} を **30日の窓**に割って集める(⛔深い offset を作らない)。"""
    out = []
    a = dt.date.fromisoformat(lo)
    end = dt.date.fromisoformat(hi)
    while a <= end:
        b = min(a + dt.timedelta(days=step - 1), end)
        out.extend(rows_all(base, key, tmpl.format(lo=a.isoformat(), hi=b.isoformat())))
        a = b + dt.timedelta(days=1)
    return out


def ten_year_days(base, key, upto):
    """⛔Fable 2026-09-05: 標準(場×距離の中央値)と四分位の材料は**過去 1 年の全開催日**にする。
    Opus 版は「その日の出走馬の直近5走が触った日」だけで組んでいたので、標準が日ごとに揺れた
    (独立オラクル 高知 1400m で 0.05 秒ずれ)。1 日 1 行(race_no=1)で引くので 12 要求ほど。"""
    lo = (dt.date.fromisoformat(upto) - dt.timedelta(days=365)).isoformat()
    rows = rows_window(base, key, "/rest/v1/nar_races?select=track,race_date&race_no=eq.1&track=in.(%s)"
                       "&race_date=gte.{lo}&race_date=lte.{hi}&order=race_date.asc,track.asc" % q_in(TEN_TRACKS),
                       lo, upto)
    return {(r["track"], r["race_date"]) for r in rows}


def q_in(values):
    """in.() の中身。⛔文字列は " で囲む(馬名に , は無いが公式表記に空白が入る)"""
    return urllib.parse.quote(",".join('"%s"' % str(v).replace('"', "") for v in values),
                              safe='(),"')


def chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------- 通過順の読み方

def corner_ranks(order):
    """1コーナーぶんの並び → {馬番: 順位}。⛔js/data.js `cornerRanks()` の**そのままの写し**。

    同着(並走)は先頭の順位を共有し、次はその頭数ぶん飛ぶ。知らない字が出たら読めない(=None)。
    ⛔同じ規則が JS と Python の2か所にあるので、tests/tenkai_corner_test.mjs と --selftest に
      **同じ5例**を置いて両方が同じ答えを出すことを確かめる。
    """
    s = str(order or "").strip()
    if not s:
        return None
    out, rank, i = {}, 1, 0
    while i < len(s):
        ch = s[i]
        if ch in ",-= 　":
            i += 1
            continue
        if ch == "(":
            end = s.find(")", i)
            if end < 0:
                return None                       # 閉じない=読めない
            nums = []
            for x in s[i + 1:end].split(","):
                x = x.strip()
                if not x.isdigit() or int(x) <= 0:
                    return None
                nums.append(int(x))
            if not nums:
                return None
            for n in nums:
                out.setdefault(n, rank)
            rank += len(nums)
            i = end + 1
            continue
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == i:
            return None                           # 知らない字=読めない(推定しない)
        out.setdefault(int(s[i:j]), rank)
        rank += 1
        i = j
    return out or None


SELFTEST = [
    ("7,9,(2,10)-11,6-(1,3,8),5-4",
     {7: 1, 9: 2, 2: 3, 10: 3, 11: 5, 6: 6, 1: 7, 3: 7, 8: 7, 5: 10, 4: 11}),
    ("(2,7)-11", {2: 1, 7: 1, 11: 3}),
    ("3=4,1", {3: 1, 4: 2, 1: 3}),
    ("", None),
    ("3,x", None),
]


def selftest(quiet=False):
    """⛔JS(tests/tenkai_corner_test.mjs)と**同じ5例**。本番でも毎回通してから走る(黙って通る)"""
    bad = 0
    for src, want in SELFTEST:
        got = corner_ranks(src)
        ok = got == want
        bad += 0 if ok else 1
        if not quiet or not ok:
            log("  %s %-32r → %s" % ("OK " if ok else "NG ", src, got))
    if not quiet:
        log("通過順の読み方 selftest: %d/%d" % (len(SELFTEST) - bad, len(SELFTEST)))
    return 0 if not bad else 1


def first_corner(corners):
    """レースの corners(公式・走った順に並んでいる)→ 1番目のコーナーの {馬番: 順位}。

    ⛔並びの先頭を採る。「１コーナー」がある場でもそれが先頭なので同じ。
      (先頭が「正面」「３コーナー」になる場もある= その場でいちばん早い通過点がそれ)
    ⛔order が空の要素は飛ばす(js/data.js cornerList と同じ扱い)。
    """
    for c in (corners or []):
        if not isinstance(c, dict):
            continue
        ranks = corner_ranks(c.get("order"))
        if ranks:
            return ranks
    return None


# ---------------------------------------------------------------- 1頭の型

def style_of(ps):
    """位置(p)の並び → (型, 平均p) または (None, None)。⛔MIN_RUNS 未満は型を付けない。

    逃げ候補= p<=LEAD_P の走が**過半数**(2走なら2走とも= `2*2>2` で同じことになる)。
    """
    if len(ps) < MIN_RUNS:
        return None, None
    m = statistics.fmean(ps)
    if sum(1 for p in ps if p <= LEAD_P) * 2 > len(ps):
        return "逃げ", m
    return ("先行" if m <= FRONT_P else "差し" if m <= MID_P else "追込"), m


def word_of(lead):
    """カードの1行目。⛔価値判断語は使わない(§5)"""
    if not lead:
        w = "逃げ馬不在"
    elif len(lead) == 1:
        w = "単騎(%d番)" % lead[0]
    elif len(lead) == 2:
        w = "2頭(%s番)" % "・".join(str(u) for u in lead)
    else:
        w = "ハナ争い(%s番)" % "・".join(str(u) for u in lead)
    return w


def thickness(n_front, k):
    if not k:
        return ""
    r = n_front / k
    if r <= THIN_FRONT:
        return "・前が手薄"
    if r >= THICK_FRONT:
        return "・前が多い"
    return ""


# ---------------------------------------------------------------- 取得

def fetch_runs_for(base, key, names, lo, hi):
    """horse_name in names・lo <= race_date < hi・着順ありの走。80頭ずつ・ページングつき"""
    out = []
    for part in chunks(sorted(names)):
        out.extend(rows_all(
            base, key,
            "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,horse_name,birth_date"
            f"&horse_name=in.({q_in(part)})&race_date=gte.{lo}&race_date=lt.{hi}&finish=not.is.null"
            "&order=race_date.desc,track.asc,race_no.asc,runner_number.asc"))
    return out


def fetch_corners(base, key, need):
    """need = {(track, race_date)} → {(track, date, race_no): {馬番: 順位}}。場ごと・日付80個ずつ"""
    by_track = {}
    for t, d in need:
        by_track.setdefault(t, set()).add(d)
    out = {}
    for t, dates in sorted(by_track.items()):
        for part in chunks(sorted(dates)):
            rows = rows_all(
                base, key,
                "/rest/v1/nar_races?select=track,race_date,race_no,corners"
                f"&track=eq.{urllib.parse.quote(t)}&race_date=in.({q_in(part)})"
                "&order=race_date.asc,race_no.asc")
            for r in rows:
                ranks = first_corner(r.get("corners"))
                if ranks:
                    out[(r["track"], r["race_date"], r["race_no"])] = ranks
    return out


def pick_runs(runs, track):
    """1頭の走(新しい順)→ 見る5走。⛔同じ場が3走以上あれば同じ場だけ"""
    same = [r for r in runs if r["track"] == track]
    return (same if len(same) >= SAME_TRACK_MIN else runs)[:N_RUNS]


def same_horse(a_birth, b_birth):
    """同名馬よけ。⛔どちらかが null なら名前だけで通す"""
    return (not a_birth) or (not b_birth) or a_birth == b_birth


def positions(runs, ranks_of):
    """走の並び → 位置 p の並び(読めた走だけ)。p= 順位 ÷ その通過順に並んだ頭数"""
    ps = []
    for r in runs:
        ranks = ranks_of.get((r["track"], r["race_date"], r["race_no"]))
        if not ranks:
            continue
        u = r.get("runner_number")
        if u is None or int(u) not in ranks:
            continue
        ps.append(ranks[int(u)] / len(ranks))
    return ps


def build_races(day_races, day_runs, past_by_horse, ranks_of, ten=None):
    """1日ぶんの races ブロックを組む。

    ⛔`ten`(§99b・(ten_of, std, band))を渡したときだけ `h[馬番].ten/tn` と `pace/pace_by/pace_ten`
      を**足す**。渡さなければ §99a と1バイトも変わらない。
    """
    ten_of, std, band = ten if ten else ({}, {}, {})
    runs_by_race = {}
    for r in day_runs:
        runs_by_race.setdefault((r["track"], r["race_no"]), []).append(r)
    out, k_ratios = {}, []
    for race in day_races:
        t, no = race["track"], race["race_no"]
        if t not in SHOW_TRACKS:
            continue
        rows = sorted(runs_by_race.get((t, no), []), key=lambda x: x.get("runner_number") or 0)
        if not rows:
            continue
        buckets = {s: [] for s in STYLES}
        none, hh = [], {}
        for e in rows:
            u = e.get("runner_number")
            if u is None:
                continue
            u = int(u)
            hist = [x for x in past_by_horse.get(e["horse_name"], [])
                    if same_horse(e.get("birth_date"), x.get("birth_date"))]
            picked = pick_runs(hist, t)
            ps = positions(picked, ranks_of)
            s, m = style_of(ps)
            if not s:
                none.append(u)
                continue
            buckets[s].append(u)
            hh[str(u)] = {"s": s, "p": round(m, 2), "m": len(ps)}
            # §99b テン。⛔3走未満は出さない・型の付いた馬にだけ足す(h の鍵を増やさない)
            tv = ten_values(picked, ten_of, std) if ten_of else []
            if len(tv) >= TEN_MIN_RUNS:
                hh[str(u)]["ten"] = round(statistics.median(tv), 2)
                hh[str(u)]["tn"] = len(tv)
        k = sum(len(v) for v in buckets.values())
        n = len(rows)
        if not k:
            continue                      # 1頭も型が付かない=カードを出さない(推定を薄めない)
        k_ratios.append(k / n)
        lead = sorted(buckets["逃げ"])
        rec = {
            "n": n, "k": k,
            "lead": lead, "front": sorted(buckets["先行"]),
            "mid": sorted(buckets["差し"]), "back": sorted(buckets["追込"]),
            "none": sorted(none), "h": hh,
            "w": word_of(lead) + thickness(len(lead) + len(buckets["先行"]), k),
        }
        if ten_of:
            add_pace(rec, t, hh, band)          # §99b(出せないレースはキーごと置かない)
        out["%s-%d" % (TRACK2PREFIX[t], no)] = rec
    return out, k_ratios


def day_block(base, key, date):
    """1日ぶん(出馬表の日)。戻り: (races, メモ文字列)"""
    races = rows_all(base, key, "/rest/v1/nar_races?select=track,race_no,distance_m,field_size"
                                f"&race_date=eq.{date}&order=track.asc,race_no.asc")
    races = [r for r in races if r["track"] != BANEI and r["track"] in TRACK2PREFIX]
    if not races:
        return {}, "レース 0 本"
    runs = rows_all(base, key, "/rest/v1/nar_runs?select=track,race_no,runner_number,horse_name,"
                               f"birth_date&race_date=eq.{date}"
                               "&order=track.asc,race_no.asc,runner_number.asc")
    tracks = {r["track"] for r in races}
    runs = [r for r in runs if r["track"] in tracks]
    names = {r["horse_name"] for r in runs if r.get("horse_name")}
    lo = (dt.date.fromisoformat(date) - dt.timedelta(days=PAST_DAYS)).isoformat()
    past = fetch_runs_for(base, key, names, lo, date)
    by_horse = {}
    for r in past:
        by_horse.setdefault(r["horse_name"], []).append(r)
    for v in by_horse.values():
        v.sort(key=lambda x: (x["race_date"], x["race_no"]), reverse=True)
    # 見る走だけに絞ってから corners を取りに行く(⛔要らない日を引かない)
    need = set()
    for e in runs:
        hist = [x for x in by_horse.get(e["horse_name"], [])
                if same_horse(e.get("birth_date"), x.get("birth_date"))]
        for x in pick_runs(hist, e["track"]):
            need.add((x["track"], x["race_date"]))
    ranks_of = fetch_corners(base, key, need)
    # §99b テン。⛔前半3F のある6場の日だけ旧DBへ行く(他9場は今までどおり通信ゼロ)
    ten = fetch_ten(base, key, {(t, d) for t, d in need if t in TEN_TRACKS} | ten_year_days(base, key, date))
    out, k_ratios = build_races(races, runs, by_horse, ranks_of, ten)
    n_ten = sum(1 for r in out.values() for h in r["h"].values() if h.get("ten") is not None)
    n_pace = sum(1 for r in out.values() if r.get("pace"))
    memo = ("レース %d / 出走 %d / 過去走 %d(馬 %d)・通過順の読めたレース %d / 見立てを出す %d 本"
            "・テン %d頭 / ペース見込み %d本"
            % (len(races), len(runs), len(past), len(names), len(ranks_of), len(out), n_ten, n_pace))
    if k_ratios:
        memo += "・k/N 平均 %.2f" % statistics.fmean(k_ratios)
    return out, memo


# ---------------------------------------------------------------- §99b テンとペース見込み

def _chihou():
    """旧DB(keiba_* / chihou_*)の入口。⛔鍵はここに書かず cloud/kochi_results.py の値を借りる
    (匿名キー= js/data.js と同じ公開キー・**読み取りだけ**)。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kochi_results
    return kochi_results.CHIHOU_URL, kochi_results.CHIHOU_ANON


def _kochi_kinds(base, key, days):
    """§98b の nar_meta `kochi_3f_kinds:<日>` → {(日, 'R-馬番'): '実測'|'推定'}。⛔推定は使わない"""
    out = {}
    for part in chunks(days):
        rows = rows_all(base, key, "/rest/v1/nar_meta?select=key,value&key=in.(%s)"
                        % q_in(["kochi_3f_kinds:" + d for d in part]))
        for r in rows:
            d = str(r.get("key") or "")[len("kochi_3f_kinds:"):]
            for k, v in (r.get("value") or {}).items():
                out[(d, k)] = v
    return out


def fetch_ten(base, key, need):
    """need={(場, 日)} → (ten_of, std, band)。⛔旧DBへは**日単位**でまとめて引く(1馬1本にしない)。

    ten_of {(場, 日, R, 馬番): (前半3F 秒, 距離m)} / std {(場, 距離): 中央値} /
    band   {場: [下四分位, 上四分位]}(高知は使わない= ±KOCHI_BAND 固定)
    """
    curl, canon = _chihou()
    ten_of = {}
    # ---- 高知(keiba_*・映像計測)。⛔`kochi_3f_kinds` が「実測」の馬だけ(推定は使わない)
    kd = sorted({d for t, d in need if t == "高知"})
    if kd:
        dist = {}
        for part in chunks(kd):
            for r in rows_all(curl, canon, "/rest/v1/keiba_races?select=race_date,race_no,distance"
                              "&baba_code=eq.31&race_date=in.(%s)"
                              % q_in([d.replace("-", "/") for d in part])):
                dnum = "".join(c for c in str(r.get("distance") or "") if c.isdigit())
                if dnum:
                    dist[(r["race_date"], r["race_no"])] = int(dnum)
        kinds = _kochi_kinds(base, key, kd)
        for part in chunks(kd):
            for r in rows_all(curl, canon, "/rest/v1/keiba_horses?select=race_date,race_no,uma_ban,"
                              "first3f&baba_code=eq.31&race_date=in.(%s)"
                              % q_in([d.replace("-", "/") for d in part])):
                v = str(r.get("first3f") or "").strip()
                if not v:
                    continue
                d = str(r["race_date"]).replace("/", "-")
                if kinds.get((d, "%s-%s" % (r["race_no"], r["uma_ban"]))) != "実測":
                    continue                      # ⛔推定は使わない(§98b の札で見分ける)
                dm = dist.get((r["race_date"], r["race_no"]))
                if dm:
                    try:
                        ten_of[("高知", d, int(r["race_no"]), int(r["uma_ban"]))] = (float(v), dm)
                    except ValueError:
                        pass
    # ---- 門別・南関4(chihou_*・競馬ブック)。⛔1200m 未満は別物なので入れない
    cd = sorted({d for t, d in need if t in TEN_TRACKS and t != "高知"})
    ct = sorted({t for t, _d in need if t in TEN_TRACKS and t != "高知"})
    if cd and ct:
        rmeta = {}
        for part in chunks(cd):
            for r in rows_all(curl, canon, "/rest/v1/chihou_races?select=race_id,track,race_date,"
                              "race_no,distance_m&track=in.(%s)&race_date=in.(%s)"
                              % (q_in(ct), q_in(part))):
                if (r.get("distance_m") or 0) >= CHIHOU_MIN_DIST:
                    rmeta[r["race_id"]] = r
        for part in chunks(sorted(rmeta)):
            for r in rows_all(curl, canon, "/rest/v1/chihou_results?select=race_id,umaban,first3f"
                              "&race_id=in.(%s)" % q_in(part)):
                v, m = r.get("first3f"), rmeta.get(r["race_id"])
                if v is None or not m or r.get("umaban") is None:
                    continue
                ten_of[(m["track"], m["race_date"], int(m["race_no"]), int(r["umaban"]))] = \
                    (float(v), int(m["distance_m"]))
    # ---- 標準(場×距離の中央値)と、場ごとのテンの四分位
    by_dist = {}
    for (t, _d, _no, _u), (v, dm) in ten_of.items():
        by_dist.setdefault((t, dm), []).append(v)
    std = {k: statistics.median(v) for k, v in by_dist.items() if len(v) >= TEN_STD_MIN}
    # ⛔閾値は「そのレースでいちばん速いテン」の分布で切る。**全走をプールした分布**で切ると、
    #   判定する量(逃げ候補の中の最速・実際は1角先頭馬)と別物になり、ほぼ全部「速い」になる
    #   (2026-09-05 実測: プールだと 大井の見込みが 速い85/平均37/遅い1・一致65%に対し
    #    「いつも速い」と言うだけで 76% 当たっていた= 言葉が何も足していない)
    fastest = {}
    for (t, d, no, _u), (v, dm) in ten_of.items():
        base_v = std.get((t, dm))
        if base_v is None:
            continue
        k, x = (t, d, no), v - base_v
        if k not in fastest or x < fastest[k]:
            fastest[k] = x
    pool = {}
    for (t, _d, _no), x in fastest.items():
        pool.setdefault(t, []).append(x)
    band = {}
    for t, xs in pool.items():
        if len(xs) >= TEN_STD_MIN:
            q = statistics.quantiles(sorted(xs), n=4, method="inclusive")
            band[t] = [round(q[0], 2), round(q[2], 2)]
    return ten_of, std, band


def ten_values(runs, ten_of, std):
    """走の並び → テン(秒・場×距離の標準との差)の並び。⛔標準の無い組は出さない"""
    out = []
    for r in runs:
        u = r.get("runner_number")
        if u is None:
            continue
        hit = ten_of.get((r["track"], r["race_date"], int(r["race_no"]), int(u)))
        if not hit:
            continue
        base_v = std.get((r["track"], hit[1]))
        if base_v is None:
            continue
        out.append(hit[0] - base_v)
    return out


def pace_word(track, ten, band, kochi_fixed=True):
    """テン(秒)→ 速い/平均/遅い。⛔高知だけ ±0.4 秒(kochi-pace-definition)・他場は四分位。

     は **--backtest --pace --kochi-q** の測定用(高知も四分位で切ったらどうなるか)。
    ⛔本番の既定は指示文どおり ±0.4 秒のまま。
    """
    if track == "高知" and kochi_fixed:
        lo, hi = -KOCHI_BAND, KOCHI_BAND
    else:
        b = band.get(track)
        if not b:
            return None
        lo, hi = b
    return "速い" if ten <= lo else ("遅い" if ten >= hi else "平均")


def add_pace(rec, track, hh, band):
    """1レース分の pace/pace_by/pace_ten を**足す**(出せないときはキーごと置かない)"""
    if TRACK2PREFIX.get(track) not in PACE_TRACKS:
        return
    cands = rec["lead"] or rec["front"]          # 逃げ候補が0頭なら先行で代用
    best = None
    for u in cands:
        e = hh.get(str(u))
        if e and e.get("ten") is not None and (best is None or e["ten"] < best[1]):
            best = (u, e["ten"])
    if not best:
        return
    w = pace_word(track, best[1], band)
    if w:
        rec["pace"], rec["pace_by"], rec["pace_ten"] = w, best[0], best[1]


# ---------------------------------------------------------------- バックテスト

def backtest(base, key, days, pace=False, kochi_q=False):
    """過去 days 日の完了レースを、その日より前の走だけで組み直して答え合わせする。

    ⛔オラクル= 実際の1番目のコーナーの先頭馬(公式)。⛔本番と同じ関数(style_of / pick_runs)を通す。
    ⛔`--pace`(§99b)= ペース見込みの答え合わせ。実際= そのレースで**実際に1角先頭だった馬**の
      前半3F − 標準 を同じ閾値に通した言葉。3値なので偶然は 33%。
    """
    hi = dt.date.today()
    lo = hi - dt.timedelta(days=days)
    far = (lo - dt.timedelta(days=PAST_DAYS)).isoformat()
    log("バックテスト %s 〜 %s(過去走は %s から)" % (lo, hi - dt.timedelta(days=1), far))
    races = rows_window(base, key,
                        "/rest/v1/nar_races?select=track,race_date,race_no,corners"
                        "&race_date=gte.{lo}&race_date=lte.{hi}"
                        "&order=race_date.asc,track.asc,race_no.asc",
                        far, (hi - dt.timedelta(days=1)).isoformat())
    races = [r for r in races if r["track"] in TRACK2PREFIX]
    ranks_of = {}
    for r in races:
        ranks = first_corner(r.get("corners"))
        if ranks:
            ranks_of[(r["track"], r["race_date"], r["race_no"])] = ranks
    log("  レース %d 本(うち通過順が読めた %d 本)・要求 %d 回" % (len(races), len(ranks_of), N_REQ[0]))
    runs = rows_window(base, key,
                       "/rest/v1/nar_runs?select=track,race_date,race_no,runner_number,"
                       "horse_name,birth_date&race_date=gte.{lo}&race_date=lte.{hi}&finish=not.is.null"
                       "&order=race_date.asc,track.asc,race_no.asc,runner_number.asc",
                       far, (hi - dt.timedelta(days=1)).isoformat())
    runs = [r for r in runs if r["track"] in TRACK2PREFIX]
    log("  走 %d 行・要求 %d 回" % (len(runs), N_REQ[0]))
    by_horse = {}
    for r in runs:
        by_horse.setdefault(r["horse_name"], []).append(r)
    for v in by_horse.values():
        v.sort(key=lambda x: (x["race_date"], x["race_no"]), reverse=True)
    runs_by_race = {}
    for r in runs:
        runs_by_race.setdefault((r["track"], r["race_date"], r["race_no"]), []).append(r)

    ten_of, std, band = {}, {}, {}
    if pace:
        need = {(r["track"], r["race_date"]) for r in races if r["track"] in TEN_TRACKS}
        need |= ten_year_days(base, key, dt.date.today().isoformat())
        ten_of, std, band = fetch_ten(base, key, need)
        log("  テン: %d走 / 標準 %d組 / 場ごとの四分位 %s・要求 %d 回"
            % (len(ten_of), len(std), sorted(band), N_REQ[0]))

    stat = {}
    for (t, d, no), ranks in sorted(ranks_of.items()):
        if d < lo.isoformat():
            continue
        rows = runs_by_race.get((t, d, no)) or []
        if not rows:
            continue
        s = stat.setdefault(t, {"races": 0, "cand_races": 0, "hit": 0, "cand": 0, "cand_hit": 0,
                                "kn": [], "absent": 0, "absent_kind": {}})
        s["races"] += 1
        lead, style, tens = [], {}, {}
        k = 0
        for e in rows:
            u = e.get("runner_number")
            if u is None:
                continue
            u = int(u)
            hist = [x for x in by_horse.get(e["horse_name"], [])
                    if same_horse(e.get("birth_date"), x.get("birth_date"))
                    and (x["race_date"], x["race_no"]) < (d, no)]
            picked = pick_runs(hist, t)
            st, _ = style_of(positions(picked, ranks_of))
            if st:
                k += 1
                style[u] = st
                if st == "逃げ":
                    lead.append(u)
                if pace and t in TEN_TRACKS:
                    tv = ten_values(picked, ten_of, std)
                    if len(tv) >= TEN_MIN_RUNS:
                        tens[u] = statistics.median(tv)
        s["kn"].append(k / len(rows))
        top = [u for u, r in ranks.items() if r == 1]
        if pace and t in TEN_TRACKS:
            cands = lead or [u for u, st2 in style.items() if st2 == "先行"]
            got = [tens[u] for u in cands if u in tens]
            pred = pace_word(t, min(got), band, not kochi_q) if got else None
            act = None
            if top:
                hit = ten_of.get((t, d, no, top[0]))
                b2 = std.get((t, hit[1])) if hit else None
                if b2 is not None:
                    act = pace_word(t, hit[0] - b2, band, not kochi_q)
            if pred and act:
                ps = s.setdefault("pace", {"n": 0, "hit": 0, "opp": 0, "act": {}, "pred": {}})
                ps["n"] += 1
                ps["hit"] += 1 if pred == act else 0
                ps["opp"] += 1 if {pred, act} == {"速い", "遅い"} else 0
                # ⛔「いつも同じ言葉」でどれだけ当たるか(=偶然の下限)も数える。一致率だけ見ない
                ps["act"][act] = ps["act"].get(act, 0) + 1
                ps["pred"][pred] = ps["pred"].get(pred, 0) + 1
        if lead:
            s["cand_races"] += 1
            s["cand"] += len(lead)
            if any(u in lead for u in top):
                s["hit"] += 1
            s["cand_hit"] += sum(1 for u in lead if u in top)
        else:
            s["absent"] += 1
            kind = style.get(top[0], "不明") if top else "不明"
            s["absent_kind"][kind] = s["absent_kind"].get(kind, 0) + 1

    log("")
    log("場      レース  候補あり  1角先頭率   候補ごと   k/N   逃げ不在→実際の先頭の型")
    rows_out = []
    for t in sorted(stat, key=lambda x: -stat[x]["races"]):
        s = stat[t]
        rate = s["hit"] / s["cand_races"] if s["cand_races"] else None
        crate = s["cand_hit"] / s["cand"] if s["cand"] else None
        kn = statistics.fmean(s["kn"]) if s["kn"] else 0
        kinds = "・".join("%s%d" % (k, v) for k, v in sorted(s["absent_kind"].items(),
                                                            key=lambda kv: -kv[1]))
        log("%-6s %5d %8d %9s %10s %6.2f   %s"
            % (t, s["races"], s["cand_races"],
               ("%.0f%%" % (rate * 100)) if rate is not None else "—",
               ("%.0f%%" % (crate * 100)) if crate is not None else "—",
               kn, kinds or "—"))
        rows_out.append((t, rate))
    ng = [t for t, r in rows_out if r is None or r < BACKTEST_GATE]
    log("")
    log("ゲート(1角先頭率 %.0f%%)に届かない場: %s" % (BACKTEST_GATE * 100, "・".join(ng) or "なし"))

    if pace:
        log("")
        log("■ §99b ペース見込み(3値なので偶然は 33%)")
        log("場      レース  一致   逆(速↔遅)  いつも同じ言葉なら  見込みの内訳")
        bad = []
        for t in sorted(stat, key=lambda x: -(stat[x].get("pace", {}).get("n", 0))):
            ps = stat[t].get("pace")
            if not ps or not ps["n"]:
                continue
            hit, opp = ps["hit"] / ps["n"], ps["opp"] / ps["n"]
            base_rate = max(ps["act"].values()) / ps["n"]      # 多数派をいつも言う戦法の一致率
            mix = "・".join("%s%d" % (k, v) for k, v in sorted(ps["pred"].items(), key=lambda x: -x[1]))
            log("%-6s %5d %6.0f%% %8.0f%% %14.0f%%  %s"
                % (t, ps["n"], hit * 100, opp * 100, base_rate * 100, mix))
            if hit < PACE_GATE_HIT or opp > PACE_GATE_OPP:
                bad.append(t)
        no_data = [t for t in TEN_TRACKS if not stat.get(t, {}).get("pace", {}).get("n")]
        log("")
        log("ゲート(一致 %.0f%% 以上・逆 %.0f%% 以下)に届かない場: %s"
            % (PACE_GATE_HIT * 100, PACE_GATE_OPP * 100, "・".join(bad) or "なし"))
        if no_data:
            log("⛔窓に材料が無くて測れなかった場: %s" % "・".join(no_data))
    return 0


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="nar_meta へ upsert(既定はドライラン)")
    ap.add_argument("--days", help="対象日をカンマ区切りで(既定= 今日+明日)")
    ap.add_argument("--backtest", type=int, help="過去N日で答え合わせ(投入しない)")
    ap.add_argument("--pace", action="store_true", help="§99b ペース見込みも答え合わせする")
    ap.add_argument("--kochi-q", action="store_true",
                    help="測定用: 高知も四分位で切る(本番の既定は ±0.4 秒のまま)")
    ap.add_argument("--selftest", action="store_true", help="通過順の読み方だけ試す(通信なし)")
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    if selftest(quiet=True):
        log("⛔通過順の読み方が壊れている。中断")
        return 2

    if a.backtest:
        return backtest(base, key, a.backtest, pace=a.pace, kochi_q=a.kochi_q)

    today = dt.datetime.now(JST).date()
    days = ([d.strip() for d in a.days.split(",") if d.strip()] if a.days
            else [today.isoformat(), (today + dt.timedelta(days=1)).isoformat()])
    rc = 0
    for date in days:
        t0 = dt.datetime.now()
        races, memo = day_block(base, key, date)
        log("■ %s  %s  (%.0f秒 / 要求 %d 回)"
            % (date, memo, (dt.datetime.now() - t0).total_seconds(), N_REQ[0]))
        if not races:
            continue
        if not a.apply:
            k = sorted(races)[0]
            log("   ドライラン(--apply なし)。例 %s: %s"
                % (k, json.dumps(races[k], ensure_ascii=False)[:300]))
            continue
        value = {"built": dt.datetime.now(JST).isoformat(timespec="minutes"), "races": races}
        N_REQ[0] += 1
        st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                    json.dumps([{"key": META_PREFIX + date, "value": value,
                                 "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]
                               ).encode("utf-8"))
        log("   nar_meta/%s%s 更新 %s(%d レース)" % (META_PREFIX, date, st, len(races)))
        if st not in (200, 201):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
