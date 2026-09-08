# -*- coding: utf-8 -*-
"""統合ビューア cloud: 当日の**全券種**オッズ(枠連複/枠連単/馬連/馬単/ワイド/3連複/3連単)を
公式サイトから取り nar_odds_full へ入れる(§77 W1・設計= docs/proposal_s77_odds_center_20260902.md)。

単複(cloud/odds.py・nar_race_odds)とは別の表・別の窓。こちらは発走が近いレースだけを狭く取る。
  python cloud/odds_full.py                 # 今日(JST)の「発走 60 分前〜10 分後」・最大10レース
  python cloud/odds_full.py --dry-run       # 取得と解析だけ(投入しない・件数と先頭3組を出す)
  python cloud/odds_full.py --dry-run --save-fixtures tests/fixtures/odds   # 生HTMLを保存(W0)
  python cloud/odds_full.py --env pipeline/.env.nar                          # ローカル試験(人間が実行)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(GitHub Secrets)。読むだけの試験は --url/--key で anon も可
終了コード: 0 正常(対象なし・一部の取得失敗も 0=次の実行に任せる)/ 1 投入失敗 / 2 前提の読み取りに失敗

⛔cloud/odds.py は**変更しない**(§76 が history の粒度に依存している)。ここは読むだけで再利用する。
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
from load_nar_official import load_env, upsert                      # noqa: E402
from odds import BABA, http_get, log, pick_targets, sb_get, _num, _text   # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
BASE = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo"
TABLE = "nar_odds_full"
CONFLICT = "track,race_date,race_no,kind"
SLEEP = 1.0            # 1リクエストの間隔(秒)。公式への負荷は odds.py と同じ流儀

# 公式ページ(パス) → そのページから採れる券種。枠連のページだけ1ページで2種
PAGES = [
    ("OddsWakuLenFukuTan", ("wakuren", "wakutan")),
    ("OddsUmLenFuku", ("umaren",)),
    ("OddsUmLenTan", ("umatan",)),
    ("OddsWide", ("wide",)),
    ("Odds3LenFuku", ("sanrenpuku",)),
    ("Odds3LenTan", ("sanrentan",)),
]
KIND_LABEL = {"wakuren": "枠連複", "wakutan": "枠連単", "umaren": "馬連", "umatan": "馬単",
              "wide": "ワイド", "sanrenpuku": "3連複", "sanrentan": "3連単"}
RANKING_KINDS = ("umaren", "umatan", "wide", "sanrenpuku", "sanrentan")
WAKU_MAX = 8           # 枠は 1〜8(公式の全場共通)


# ---------------------------------------------------------------- 組合せ数の理論値

def _nCr(n, r):
    if n < r:
        return 0
    out = 1
    for i in range(r):
        out = out * (n - i) // (i + 1)
    return out


def _nPr(n, r):
    if n < r:
        return 0
    out = 1
    for i in range(r):
        out *= n - i
    return out


# 券種 → (組合せの頭数, 理論値の式)。枠連は枠の数で決まるので**この検算はしない**
COMBO_SIZE = {"umaren": 2, "umatan": 2, "wide": 2, "sanrenpuku": 3, "sanrentan": 3}
COMBO_COUNT = {
    "umaren": lambda n: _nCr(n, 2), "wide": lambda n: _nCr(n, 2), "umatan": lambda n: _nPr(n, 2),
    "sanrenpuku": lambda n: _nCr(n, 3), "sanrentan": lambda n: _nPr(n, 3),
}


def runners_for_count(kind, count, head):
    """組合せ数 count が「何頭ぶんの全通り」かを返す(合わなければ None)。

    ⛔取消馬がいるとその馬を含む組は公式ページに載らない= 組合せ数は **取消後の頭数 m の理論値ちょうど**になる。
      理論値は m について厳密に増えるので、`f(m) == count` を満たす m は高々1つ。
      m == head なら取消なし、m < head なら (head - m) 頭が取消。m が見つからない(=どの頭数の全通りでもない)
      ページは、途中で切れているか読み方が違う=**捨てて次回に任せる**。
    """
    f = COMBO_COUNT.get(kind)
    if f is None or not head or count <= 0:
        return None
    for m in range(COMBO_SIZE[kind], head + 1):
        if f(m) == count:
            return m
    return None


# ---------------------------------------------------------------- 取得

def page_url(path, date, race_no, baba):
    q = urllib.parse.urlencode({"k_raceDate": date.strftime("%Y/%m/%d"), "k_raceNo": race_no,
                                "k_babaCode": baba})
    return f"{BASE}/{path}?{q}"


# ---------------------------------------------------------------- 解析(標準ライブラリだけ)

TITLE_RE = re.compile(r'<h4[^>]*class="[^"]*odd_title[^"]*"[^>]*>(.*?)</h4>', re.S)
TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
RANKING_RE = re.compile(r'<table[^>]*class="[^"]*odd_ranking_table[^"]*"[^>]*>(.*?)</table>', re.S)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def is_final_of(page):
    """見出し(odd_title)に「最終」があれば確定。枠連ページは見出しが2つあるのでどちらかにあれば真。"""
    return any("最終" in _text(m) for m in TITLE_RE.findall(page))


def head_count(page):
    """そのページの `odd_table`(馬番の行列)から出走頭数を数える。読めなければ None。

    ⚠この表は入力UI用でオッズは入っていないが、**馬番の行だけは実在の馬番**が並ぶ(2026-09-02 実測)。
    """
    m = re.search(r'<table[^>]*class="[^"]*odd_table[^"]*"[^>]*>(.*?)</table>', page, re.S)
    if not m:
        return None
    for tr in TR_RE.findall(m.group(1)):
        ths = [_text(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", tr, re.S)]
        if not any("馬番" in x for x in ths):
            continue
        nums = set()
        for td in TD_RE.findall(tr):
            v = _num(_text(td))
            if v is not None:
                nums.add(int(v))
        if nums:
            return len(nums)
    return None


def parse_ranking(page):
    """人気順の表(馬連/馬単/ワイド/3連複/3連単)→ ([(組, オッズ, 人気)], 落とした行数)。

    ⛔表は25件ごとに分かれる(3連単は50表を超える)。**全部の `odd_ranking_table` をつないでから**数える。
    ⛔人気は公式の整数をそのまま写す(同オッズは同順位。自分で振り直さない=§76 と同じ姿勢)。
    """
    out, dropped = [], 0
    for tb in RANKING_RE.findall(page):
        for tr in TR_RE.findall(tb):
            tds = [_text(x) for x in TD_RE.findall(tr)]
            if len(tds) < 3:
                continue                                    # 見出し行(th だけ)
            combo = re.fullmatch(r"(\d+)-(\d+)(?:-(\d+))?", tds[0].replace(" ", ""))
            odds, rank = _num(tds[1]), _num(tds[2])
            if not combo or odds is None or rank is None:
                dropped += 1                                # 取消・「発売前」など数値でない行
                continue
            nums = tuple(int(g) for g in combo.groups() if g is not None)
            out.append((nums, float(odds), int(rank)))
    return out, dropped


def parse_waku(page):
    """枠連のページ → {'wakuren': [[i, j, odds]], 'wakutan': [[i, j, odds]]}。

    ⛔このページの表には class が無いので、見出し(odd_title)の「枠連複」「枠連単」で本文を切る。
    ⛔各表は 行頭の `<th>` が枠 i で、`<td>枠j</td><td>オッズ</td>` が続く。「-」は無し(_num が None)。
      枠連複は i ≤ j の上三角(**同枠のゾロ目は枠に2頭以上いれば値がある**=2026-09-02 大井 5-5 で実測)、
      枠連単は i→j の順序あり。
    ⛔**見出しごと無い場がある**(2026-09-02 実測: 門別・名古屋は枠連単の見出しが無い=その場は売っていない)。
      「売っていない(None)」と「見出しはあるが空=発売前([])」を**言い分ける**(空欄を嘘にしない=§67 B5 の流儀)。
    """
    out = {"wakuren": None, "wakutan": None}
    parts = TITLE_RE.split(page)                            # [前置き, 見出し1, 本文1, 見出し2, 本文2, …]
    for i in range(1, len(parts) - 1, 2):
        head = _text(parts[i])
        kind = "wakuren" if "枠連複" in head else ("wakutan" if "枠連単" in head else None)
        if kind is None:
            continue
        rows = []
        for tb in TABLE_RE.findall(parts[i + 1]):
            th = re.search(r"<th[^>]*>(.*?)</th>", tb, re.S)
            a = _num(_text(th.group(1))) if th else None
            if a is None:
                continue
            for tr in TR_RE.findall(tb):
                tds = [_text(x) for x in TD_RE.findall(tr)]
                if len(tds) < 2:
                    continue
                b, odds = _num(tds[0]), _num(tds[1])
                if b is None or odds is None:
                    continue                                # 「-」= その組は無い
                if not (1 <= int(a) <= WAKU_MAX and 1 <= int(b) <= WAKU_MAX):
                    continue                                # 枠は 1〜8 の外に出ない
                rows.append([int(a), int(b), float(odds)])
        out[kind] = rows
    return out


def combos_json(kind, rows):
    """保存形(設計書 §4.1)。2連系 [[a,b,odds,rank]] / 3連系 [[a,b,c,odds,rank]] / 枠連 [[i,j,odds]]。"""
    if kind in ("wakuren", "wakutan"):
        return rows
    return [list(nums) + [odds, rank] for nums, odds, rank in rows]


# ---------------------------------------------------------------- 1レースぶん

def save_page(save_dir, path, page):
    p = Path(save_dir) / f"{path}.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(page, encoding="utf-8")


def fetch_race(date, target, save_dir=None):
    """1レースの6ページを取り、券種ごとの行にする。→ (rows, stats, 頭数)。rows は upsert 用の dict。"""
    now_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    st = {"ok": 0, "ng": 0, "empty": 0, "absent": 0, "reject": 0, "final": 0}
    head = None
    if save_dir:
        # W0 の見本一式は単複(既存 cloud/odds.py の担当ページ)も揃える。⛔ここでは解析も投入もしない
        try:
            time.sleep(SLEEP)
            save_page(save_dir, "OddsTanFuku",
                      http_get(page_url("OddsTanFuku", date, target["race_no"], target["baba"]))
                      .decode("utf-8", "replace"))
        except Exception as e:
            log(f"    見本の取得失敗 OddsTanFuku: {type(e).__name__}: {str(e)[:120]}")
    for pi, (path, kinds) in enumerate(PAGES):
        if pi:
            time.sleep(SLEEP)
        url = page_url(path, date, target["race_no"], target["baba"])
        try:
            page = http_get(url).decode("utf-8", "replace")
        except Exception as e:
            st["ng"] += 1
            log(f"    取得失敗 {path}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if save_dir:
            save_page(save_dir, path, page)
        is_final = is_final_of(page)
        head = head_count(page) or head
        if kinds[0] in ("wakuren", "wakutan"):
            waku = parse_waku(page)
            for kind in kinds:
                got = waku.get(kind)
                if got is None:
                    st["absent"] += 1
                    log(f"    {KIND_LABEL[kind]} はこの場に無い(見出しごと無い=発売していない)")
                    continue
                if not got:
                    st["empty"] += 1
                    log(f"    発売前/表なし {KIND_LABEL[kind]}")
                    continue
                st["ok"] += 1
                st["final"] += 1 if is_final else 0
                log(f"    {KIND_LABEL[kind]} {len(got)}組{' (最終)' if is_final else ''} 先頭3組 {got[:3]}")
                rows.append({"track": target["track"], "race_date": date.isoformat(),
                             "race_no": target["race_no"], "kind": kind, "observed_at": now_utc,
                             "is_final": is_final, "combos": combos_json(kind, got),
                             "updated_at": now_utc})
            continue
        kind = kinds[0]
        got, dropped = parse_ranking(page)
        if not got:
            st["empty"] += 1
            log(f"    発売前/表なし {KIND_LABEL[kind]}")
            continue
        m = runners_for_count(kind, len(got), head)
        if m is None:
            st["reject"] += 1
            log(f"    ⚠検算落ち {KIND_LABEL[kind]}: {len(got)}組 は {head} 頭以下のどの全通りとも合わない"
                f"(数値でない行 {dropped})→ 捨てて次回に任せる")
            continue
        st["ok"] += 1
        st["final"] += 1 if is_final else 0
        scratched = "" if m == head else f"・取消 {head - m} 頭とみなす"
        log(f"    {KIND_LABEL[kind]} {len(got)}組 = {m}頭の全通り{scratched}"
            f"{' (最終)' if is_final else ''} 先頭3組 {[(list(a), o, r) for a, o, r in got[:3]]}")
        rows.append({"track": target["track"], "race_date": date.isoformat(),
                     "race_no": target["race_no"], "kind": kind, "observed_at": now_utc,
                     "is_final": is_final, "combos": combos_json(kind, got), "updated_at": now_utc})
    return rows, st, head


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="取得・解析だけして投入しない")
    ap.add_argument("--env", help="ローカル試験用 .env(既定は環境変数)")
    ap.add_argument("--url", help="読み取り先の上書き(試験用)")
    ap.add_argument("--key", help="APIキーの上書き(読み取りだけの試験なら anon でよい)")
    ap.add_argument("--date", help="対象日 YYYY-MM-DD(既定=今日。公式は当日分しか返さない)")
    ap.add_argument("--before", type=int, default=60, help="発走の何分前から取るか(既定60)")
    ap.add_argument("--after", type=int, default=10, help="発走の何分後まで取るか(既定10)")
    ap.add_argument("--limit", type=int, default=10, help="1回の実行で取るレース数の上限(既定10)")
    ap.add_argument("--save-fixtures", metavar="DIR",
                    help="取得した生HTMLを DIR/<場>_<R>R/ に保存する(W0。処理したレースぶん全部)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = (args.url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = args.key or os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2

    now = dt.datetime.now(JST)
    date = dt.date.fromisoformat(args.date) if args.date else now.date()
    now_min = now.hour * 60 + now.minute
    try:
        races = sb_get(url, key, f"nar_races?select=track,race_no,post_time&race_date=eq.{date.isoformat()}"
                                 "&order=track.asc,race_no.asc")
    except Exception as e:
        log(f"nar_races の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2
    # 既に全券種の最終が入っているレースを飛ばすための**下読み**。⛔ここは best-effort:
    # 表がまだ無い(SQL 未適用)ときは 404 になるが、取り直すだけで害は無い(upsert は何度流しても同じ)。
    # ⚠**書き込みの失敗は rc 1 のまま**= 表が無ければ投入で必ず落ちる(黙って成功しない)
    try:
        have = sb_get(url, key, f"{TABLE}?select=track,race_no,kind,is_final&race_date=eq.{date.isoformat()}")
    except Exception as e:
        log(f"⚠{TABLE} の下読みに失敗(取り直しになるだけ): {type(e).__name__}: {str(e)[:120]}")
        have = []

    # 全券種の最終オッズが揃ったレースだけ「済み」にする(1種でも欠けていれば取りに行く)
    got_final = {}
    for r in have:
        if r.get("is_final") and r.get("race_no") is not None:
            got_final.setdefault((r.get("track"), int(r.get("race_no"))), set()).add(r.get("kind"))
    all_kinds = {k for _, kinds in PAGES for k in kinds}
    done = [{"track": t, "race_no": n, "is_final": True}
            for (t, n), ks in got_final.items() if all_kinds <= ks]

    targets = pick_targets(races, done, now_min, args.before, args.after, args.limit)
    log(f"{date} 当日のレース {len(races)} / 対象 {len(targets)}"
        f"(発走 {args.before} 分前〜{args.after} 分後・全券種の最終が揃った {len(done)} レースは除く)")
    if not targets:
        return 0

    rows, tot = [], {"ok": 0, "ng": 0, "empty": 0, "absent": 0, "reject": 0, "final": 0}
    for i, t in enumerate(targets):
        if i:
            time.sleep(SLEEP)
        log(f"  {t['track']} {t['race_no']}R(発走まで {t['delta']} 分)")
        save = (Path(args.save_fixtures) / f"{t['track']}_{t['race_no']}R") if args.save_fixtures else None
        got, st, head = fetch_race(date, t, save_dir=save)
        if save:
            log(f"    生HTMLを保存: {save}({head} 頭)")
        rows.extend(got)
        for k in tot:
            tot[k] += st[k]

    log(f"取得 成功 {tot['ok']} / 失敗 {tot['ng']} / 発売前 {tot['empty']} / その場に無い {tot['absent']} / "
        f"検算落ち {tot['reject']} / 最終 {tot['final']}(行 {len(rows)})")
    if args.dry_run:
        log("dry-run: 投入しない")
        return 0
    if not rows:
        return 0
    status, msg = upsert(url, key, TABLE, CONFLICT, rows)
    if status >= 300 or status == 0:
        log(f"投入失敗 status={status} {msg}")
        return 1
    log(f"投入 {len(rows)} 行 -> {TABLE}")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)
