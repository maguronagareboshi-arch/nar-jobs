# -*- coding: utf-8 -*-
"""§238a 派生表 nar_run_facts の**規則の正本**(通信なし・純関数だけ)。

今まで同じ規則が 3 か所に写されていた:
  ・`cloud/tenkai.py corner_ranks()` / `first_corner()` / `style_of()`(展開の見立て)
  ・`pipeline/sql/ai_feat_20260908.sql public.nar_corner_ranks()` と t_cmap/t_corner(予想 AI の材料)
  ・`js/data.js cornerRanks()`(画面)
ここが**1 つの正本**。cloud/run_facts.py がこれを呼んで表に焼き、読み手は表を読むだけにする(置換は §238a2)。

⛔規則を変えていないこと(3 写しとの違い)は tests/run_facts_check.py が 12 か月ぶんで確かめる。
⛔推定しない= 読めない字が出たらそのコーナーごと捨てる・欠けは None(0 で埋めない)。

  py -3.12 -X utf8 pipeline/facts.py --selftest      # 通信なしの自己診断(3 写しの既知の入出力例)
"""
import datetime as dt
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# ---- 脚質の閾値。⛔cloud/tenkai.py の LEAD_P/FRONT_P/MID_P/MIN_RUNS/PAST_DAYS/N_RUNS/
#      SAME_TRACK_MIN と**同じ数**(小さい標本から動かさない)。
LEAD_P = 0.2            # これ以下の位置なら「その走は前に行った」
FRONT_P = 0.4           # 平均位置がこれ以下なら 先行
MID_P = 0.7             # これ以下なら 差し / それより後ろは 追込
MIN_RUNS = 2            # 位置の読めた走がこれ未満なら型を付けない
PAST_DAYS = 365         # 過去走を見る窓
N_RUNS = 5              # 見る走の数
SAME_TRACK_MIN = 3      # 同じ場の走がこれ以上あれば同じ場だけで見る

STYLES = ("逃げ", "先行", "差し", "追込")
# 予想 AI(ai_feat)の数の割り当て。⛔学習と推論で同じものを使う
STYLE_CODE = {"逃げ": 0, "先行": 1, "差し": 2, "追込": 3}
FIRST3F_SRC_ORDER = ("own", "paper", "kb", "est")   # ⛔優先順(設計 §238)

BANEI = "帯広ば"


# ---------------------------------------------------------------- 1) 通過順の読み方

def corner_ranks(order):
    """1 コーナーぶんの並び → {馬番: 順位}。読めなければ None。

    ⛔`js/data.js cornerRanks()` / `cloud/tenkai.py corner_ranks()` /
      `public.nar_corner_ranks()`(ai_feat SQL)と**同じ規則**:
      ・数字= 馬番。`,` `-` `=` 全角半角の空白は区切り(順位は変えない)。
      ・`( )` は横に並んだ馬= **先頭の順位を共有**し、次はその頭数ぶん飛ぶ。
      ・同じ馬番が 2 度出たら**最初の順位を残す**(setdefault)。
      ・知らない字・閉じない括弧・0 以下の馬番= **そのコーナーごと捨てる**(⛔推定しない)。
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
                return None                       # 閉じない= 読めない
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
            rank += len(nums)                     # 併走は頭数ぶん飛ぶ
            i = end + 1
            continue
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == i:
            return None                           # 知らない字= 読めない
        out.setdefault(int(s[i:j]), rank)
        rank += 1
        i = j
    return out or None


def corner_maps(corners):
    """nar_races.corners(走った順の配列)→ 読めたコーナーだけの [{馬番: 順位}, …](並びは元のまま)。

    ⛔order の空な要素・読めない要素は**飛ばす**(js/data.js cornerList / ai_feat の
      `where m is not null` と同じ扱い)。
    """
    out = []
    for c in (corners or []):
        if not isinstance(c, dict):
            continue
        m = corner_ranks(c.get("order"))
        if m:
            out.append(m)
    return out


def first_corner(corners):
    """レースの corners → 最初に読めたコーナーの {馬番: 順位}(⛔tenkai.py first_corner と同じ)。"""
    maps = corner_maps(corners)
    return maps[0] if maps else None


def corner_slots(corners):
    """レースの corners → (c1, c2, c3, c4) の (順位の表, 並んだ頭数) を 4 つ。無い枠は (None, None)。

    ⛔ai_feat の t_corner と**同じ決め方**= コーナーの名前では引かず**読めた並びの位置**で決める:
      c1= 最初 / c4= 最後 / c3= 最後から 2 番目(読めたのが 2 つ以上)/
      c2= 2 番目(⛔読めたのが **3 つ以上**のときだけ。2 つだと c4 と同じ物になるため None)。
    """
    maps = corner_maps(corners)
    k = len(maps)
    if k == 0:
        return [(None, None)] * 4
    slot1 = (maps[0], len(maps[0]))
    slot4 = (maps[k - 1], len(maps[k - 1]))
    slot2 = (maps[1], len(maps[1])) if k >= 3 else (None, None)
    slot3 = (maps[k - 2], len(maps[k - 2])) if k >= 2 else (None, None)
    return [slot1, slot2, slot3, slot4]


def corner_cells(corners, umaban):
    """1 頭ぶん → [(c1, n1), (c2, n2), (c3, n3), (c4, n4)]。並びに出ない馬(競走中止など)は (None, n)。

    ⛔順位の分母は**そのコーナーに並んだ頭数**(field_size ではない。#466 で 48R 中 6 本ずれた)。
    """
    u = None if umaban is None else int(umaban)
    cells = []
    for m, n in corner_slots(corners):
        cells.append((None, None) if m is None else (m.get(u), n))
    return cells


def position_of(corners, umaban):
    """1 角の位置 p = 順位 ÷ そのコーナーに並んだ頭数。読めなければ None(⛔tenkai.py positions と同じ)。"""
    c1, n1 = corner_cells(corners, umaban)[0]
    if c1 is None or not n1:
        return None
    return c1 / n1


# ---------------------------------------------------------------- 2) 脚質(発走前 as-of)

def style_of(ps):
    """位置 p の並び(新しい順・古い順どちらでもよい)→ (型, 平均 p)。⛔MIN_RUNS 未満は (None, None)。

    ⛔cloud/tenkai.py style_of と同じ式・ai_feat の style 式とも同じ
      (ai_feat は fwd = 1 - p で書いてあるだけ。fwd >= 0.8 ⇔ p <= 0.2・1 - avg(fwd) = avg(p))。
    """
    ps = [p for p in ps if p is not None]
    if len(ps) < MIN_RUNS:
        return None, None
    m = statistics.fmean(ps)
    if sum(1 for p in ps if p <= LEAD_P) * 2 > len(ps):   # 前に行った走が過半数
        return "逃げ", m
    return ("先行" if m <= FRONT_P else "差し" if m <= MID_P else "追込"), m


def pick_past_runs(runs, track, race_date):
    """1 頭の過去走 → 脚質に使う走。⛔tenkai.py pick_runs + 窓の決め方をここに 1 つにまとめた。

    runs= [{'track','race_date','p'}…](p は position_of で出した 1 角の位置・None を含んでよい)。
    ⛔as-of= race_date **より前**の走だけ(同じ日の結果は入れない)・365 日窓・
      同じ場が 3 走以上あればその場だけ・新しい順に 5 走。
    """
    d1 = race_date if isinstance(race_date, dt.date) else dt.date.fromisoformat(str(race_date))
    d0 = d1 - dt.timedelta(days=PAST_DAYS)
    ok = []
    for r in runs:
        d = r["race_date"]
        d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
        if d0 <= d < d1:                          # ⛔当日と未来は入れない
            ok.append(dict(r, race_date=d))
    ok.sort(key=lambda r: (r["race_date"], str(r.get("track") or ""), r.get("race_no") or 0), reverse=True)
    same = [r for r in ok if r.get("track") == track]
    use = same if len(same) >= SAME_TRACK_MIN else ok
    return use[:N_RUNS]


def style_asof(runs, track, race_date):
    """1 頭の過去走 → (style, 平均 p, 使った走の数)。⛔読めた走が 2 走未満なら (None, None, n)。"""
    use = pick_past_runs(runs, track, race_date)
    ps = [r.get("p") for r in use if r.get("p") is not None]
    s, m = style_of(ps)
    return s, m, len(ps)


# ---------------------------------------------------------------- 3) 前半3F の出どころ

def pick_first3f(cands):
    """{'own': 値, 'paper': 値, 'kb': 値, 'est': 値} → (値, 出どころ)。無ければ (None, None)。

    ⛔優先順は FIRST3F_SRC_ORDER 固定(設計 §238= 高知計測 > 紙面 > 専門紙 > 推定)。
    ⛔値が無い出どころは飛ばす。⛔どれも無ければ **両方 None**(first3f_src だけ埋めない)。
    """
    for src in FIRST3F_SRC_ORDER:
        v = (cands or {}).get(src)
        if v is not None:
            return float(v), src
    return None, None


# ---------------------------------------------------------------- 4) 発走直前の単勝

def win_odds_close(ticks, umaban):
    """nar_odds_ticks の行の並び → その馬の発走直前の単勝。無ければ None。

    ⛔`f`(最終)が付いた点があればその中で最後・無ければ `t`(HH:MM)がいちばん遅い点。
    ⛔0 以下は「発売前/取消」なので None(js/data.js getRaceTicks と同じ扱い)。
    """
    u = None if umaban is None else str(int(umaban))
    if u is None:
        return None
    rows = [r for r in (ticks or []) if isinstance(r, dict) and r.get("t")]
    if not rows:
        return None
    finals = [r for r in rows if r.get("f") is True]
    pool = finals or rows
    pool = sorted(pool, key=lambda r: (str(r.get("t")), r.get("id") or 0))
    for r in reversed(pool):
        w = r.get("w")
        if not isinstance(w, dict):
            continue
        v = w.get(u)
        if isinstance(v, dict):                   # 形が変わっても壊れない(値だけ拾う)
            v = v.get("w") or v.get("odds")
        try:
            v = None if v is None else float(v)
        except (TypeError, ValueError):
            v = None
        if v is not None and v > 0:
            return v
    return None


# ---------------------------------------------------------------- 5) 1 頭 1 行に組む

def horse_key(horse_name, birth_date):
    """§126 と同じ鍵。⛔どちらかが空なら None(名前だけで別の馬をつなげない)。"""
    if not horse_name or not birth_date:
        return None
    return "%s|%s" % (str(horse_name), str(birth_date)[:10])


def build_row(race, run, past, first3f_cands, ticks, computed_at, src="official"):
    """1 頭ぶんの派生行(dict)。⛔欠けは None のまま(0 で埋めない)。

    race= nar_races の 1 行 / run= nar_runs の 1 行 / past= その馬の過去走 [{track,race_date,race_no,p}] /
    first3f_cands= {'own'|'paper'|'kb'|'est': 値} / ticks= そのレースの nar_odds_ticks の行。
    """
    track = race["track"]
    date = str(race["race_date"])[:10]
    no = int(race["race_no"])
    u = run.get("runner_number")
    u = None if u is None else int(u)
    # ⛔帯広ばは corners が無い= c1..c4 は None のまま(行は作る)
    cells = corner_cells(race.get("corners"), u) if track != BANEI else [(None, None)] * 4
    s, p, n = style_asof(past, track, date) if track != BANEI else (None, None, 0)
    f3, f3src = pick_first3f(first3f_cands)
    return {
        "race_date": date, "track": track, "race_no": no, "umaban": u,
        "horse_key": horse_key(run.get("horse_name"), run.get("birth_date")),
        "horse_name": run.get("horse_name"),
        "c1": cells[0][0], "n1": cells[0][1],
        "c2": cells[1][0], "n2": cells[1][1],
        "c3": cells[2][0], "n3": cells[2][1],
        "c4": cells[3][0], "n4": cells[3][1],
        "style": s, "style_p": p, "style_n": n,
        "first3f": f3, "first3f_src": f3src,
        "last3f": None if run.get("last3f") is None else float(run["last3f"]),
        "win_odds_close": win_odds_close(ticks, u),
        "src": src, "computed_at": computed_at,
    }


# ---------------------------------------------------------------- 6) 自己診断(通信なし)

# ⛔3 写しの既知の入出力例。tests/tenkai_corner_test.mjs(JS)・cloud/tenkai.py --selftest(Python)・
#   ai_feat SQL の頭のコメントにある同じ 5 例を**そのまま**置く(どれかを直したら 4 つとも直す)。
SELFTEST_RANKS = [
    ("7,9,(2,10)-11,6-(1,3,8),5-4",
     {7: 1, 9: 2, 2: 3, 10: 3, 11: 5, 6: 6, 1: 7, 3: 7, 8: 7, 5: 10, 4: 11}),
    ("(2,7)-11", {2: 1, 7: 1, 11: 3}),
    ("3=4,1", {3: 1, 4: 2, 1: 3}),
    ("", None),
    ("3,x", None),
    ("2,11,(4,6,12),10-(7,9)", {2: 1, 11: 2, 4: 3, 6: 3, 12: 3, 10: 6, 7: 7, 9: 7}),  # ai_feat の例
    ("(1,2", None),                                                                    # 閉じない
]

# c1..c4 の枠の決め方(ai_feat t_corner と同じ)。(コーナー数, 馬番) → (c1,n1,c2,n2,c3,n3,c4,n4)
SELFTEST_SLOTS = [
    # 4 コーナー: c1=最初 / c2=2 番目 / c3=3 番目(最後から 2 番目)/ c4=最後
    ([{"name": "正面", "order": "1,2,3"}, {"name": "2角", "order": "2,1,3"},
      {"name": "3角", "order": "2,3,1"}, {"name": "4角", "order": "3,2,1"}], 1,
     (1, 3, 2, 3, 3, 3, 3, 3)),
    # 2 コーナー: ⛔c2 は None(c4 と同じ物になるため)・c3= 最初と同じ並びの 1 つ前= maps[0]
    ([{"name": "3角", "order": "5,6"}, {"name": "4角", "order": "6,5"}], 5,
     (1, 2, None, None, 1, 2, 2, 2)),
    # 1 コーナーだけ: c1 と c4 が同じ・c2/c3 は None
    ([{"name": "4角", "order": "9,8"}], 8, (2, 2, None, None, None, None, 2, 2)),
    # 読めない要素は飛ばす(order が空・知らない字)
    ([{"name": "正面", "order": ""}, {"name": "3角", "order": "1,x"},
      {"name": "4角", "order": "4,1"}], 1, (2, 2, None, None, None, None, 2, 2)),
    # 並びに出ない馬(競走中止)は順位だけ None・頭数は入る
    ([{"name": "4角", "order": "4,1"}], 7, (None, 2, None, None, None, None, None, 2)),
]

SELFTEST_STYLE = [
    ([0.1, 0.1], ("逃げ", 0.1)),            # p<=0.2 が過半数
    ([0.1, 0.5, 0.1], ("逃げ", None)),      # 2/3 が前= 逃げ(平均は見ない)
    ([0.1, 0.5], ("先行", 0.3)),            # 1/2 は過半数でない → 平均 0.3 <= 0.4
    ([0.5, 0.6], ("差し", 0.55)),
    ([0.8, 0.9], ("追込", 0.85)),
    ([0.1], (None, None)),                  # ⛔1 走では型を付けない
    ([], (None, None)),
]

SELFTEST_FIRST3F = [
    ({"own": 36.1, "paper": 36.5, "kb": 36.8}, (36.1, "own")),
    ({"paper": 36.5, "kb": 36.8}, (36.5, "paper")),
    ({"kb": 36.8, "est": 37.0}, (36.8, "kb")),
    ({"est": 37.0}, (37.0, "est")),
    ({}, (None, None)),                     # ⛔出どころだけ埋めない
]

SELFTEST_ODDS = [
    ([{"t": "14:50", "f": False, "w": {"3": 5.1}}, {"t": "14:58", "f": True, "w": {"3": 4.8}}], 3, 4.8),
    ([{"t": "14:58", "f": True, "w": {"3": 4.8}}, {"t": "14:50", "f": False, "w": {"3": 5.1}}], 3, 4.8),
    ([{"t": "14:50", "f": False, "w": {"3": 5.1}}, {"t": "14:58", "f": False, "w": {"3": 4.9}}], 3, 4.9),
    ([{"t": "14:58", "f": True, "w": {"3": 0}}], 3, None),        # ⛔0 は発売前/取消
    ([{"t": "14:58", "f": True, "w": {"3": 4.8}}], 7, None),      # その馬の値が無い
    ([], 3, None),
]


def selftest(quiet=False):
    """⛔通信なし。run_facts.py は走る前に必ずこれを通す(黙って通る)。"""
    bad = 0

    def check(label, got, want):
        nonlocal bad
        ok = got == want
        bad += 0 if ok else 1
        if not quiet or not ok:
            print("  %s %s → %r" % ("OK " if ok else "NG ", label, got))

    for src, want in SELFTEST_RANKS:
        check("corner_ranks %r" % src, corner_ranks(src), want)
    for corners, u, want in SELFTEST_SLOTS:
        cells = corner_cells(corners, u)
        got = (cells[0][0], cells[0][1], cells[1][0], cells[1][1],
               cells[2][0], cells[2][1], cells[3][0], cells[3][1])
        check("corner_cells %d角 馬番%d" % (len(corners), u), got, want)
    for ps, (w_style, w_mean) in SELFTEST_STYLE:
        s, m = style_of(ps)
        got = (s, None if w_mean is None else (None if m is None else round(m, 6)))
        check("style_of %r" % (ps,), got, (w_style, w_mean))
    for cands, want in SELFTEST_FIRST3F:
        check("pick_first3f %r" % (cands,), pick_first3f(cands), want)
    for ticks, u, want in SELFTEST_ODDS:
        check("win_odds_close 馬番%d" % u, win_odds_close(ticks, u), want)
    # as-of= その日より前だけ・365 日窓・同じ場が 3 走以上ならその場だけ
    past = [
        {"track": "高知", "race_date": "2026-09-01", "race_no": 1, "p": 0.1},
        {"track": "高知", "race_date": "2026-08-01", "race_no": 2, "p": 0.1},
        {"track": "高知", "race_date": "2026-07-01", "race_no": 3, "p": 0.9},
        {"track": "園田", "race_date": "2026-06-01", "race_no": 4, "p": 0.9},
        {"track": "高知", "race_date": "2024-01-01", "race_no": 5, "p": 0.1},   # ⛔365 日より前
        {"track": "高知", "race_date": "2026-09-10", "race_no": 6, "p": 0.1},   # ⛔当日(入れない)
    ]
    check("style_asof 同じ場 3 走", style_asof(past, "高知", "2026-09-10"), ("逃げ", 0.3666666666666667, 3))
    check("style_asof 窓の外だけ", style_asof(past[4:5], "高知", "2026-09-10"), (None, None, 0))
    check("horse_key", horse_key("テスト馬", "2021-04-01"), "テスト馬|2021-04-01")
    check("horse_key 生年なし", horse_key("テスト馬", None), None)
    n = (len(SELFTEST_RANKS) + len(SELFTEST_SLOTS) + len(SELFTEST_STYLE)
         + len(SELFTEST_FIRST3F) + len(SELFTEST_ODDS) + 4)
    if not quiet:
        print("facts selftest: %d/%d" % (n - bad, n))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(selftest(quiet="--quiet" in sys.argv))
