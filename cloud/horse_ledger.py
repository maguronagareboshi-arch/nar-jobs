# -*- coding: utf-8 -*-
"""本体 cloud: 馬ごとの「格組」と「収得賞金」(全15場・公式)を keiba.go.jp から取る(DESIGN §79 P1・§38 1-B 第二弾)。

2つの表を育てる(どちらも insert/upsert だけ・冪等・再開可能):
  nar_horse_codes  馬名(+生年)→ 血統登録番号(11桁)。出典= 公式の出馬表 TodayRaceInfo/DebaTable(1レース1本・全出走馬のリンク)
  nar_horse_prize  番号 → 走歴(格組・収得賞金・着順…)と 地方収得賞金の合計。出典= DataRoom/HorseMarkInfo(1頭1本)

  py -3.12 -X utf8 cloud/horse_ledger.py --env pipeline/.env.nar                # ドライラン(今日+明日の出馬表・書かない)
  py -3.12 -X utf8 cloud/horse_ledger.py --env pipeline/.env.nar --apply        # 実弾(日次と同じ)
  py -3.12 -X utf8 cloud/horse_ledger.py --env pipeline/.env.nar --apply --from 2026-04-01 --to 2026-09-02 --max-horses 2000
                                                                               # 過去分の遡り(番号→馬ページ。何度でも再開できる)
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY。終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗・番人が止めた

⛔ 実地で分かったこと(2026-09-03):
 1. **血統登録番号は 11 桁**(調査書 §3.1 の「10桁」は誤り。10桁で引くと「ご指定の馬の情報がありません」)。
 2. HorseMarkInfo の走歴の**収得賞金(地方の走だけ)を足すと RaceHorseInfo の「地方収得賞金」と一致**(メロパール 43走 7,470,000)。
    → 合計のために 2本目(RaceHorseInfo)は引かない。生年月日は nar_runs.birth_date(公式CSV)にある。
 3. 公式の出馬表・成績は**約5か月で消える**(2025-09-05 高知 1R は空 7.7KB)。番号の遡りはそこまで。
    馬ページ自体は全走歴を返すので、番号さえ取れれば 1 年より前の走も入る。
 4. JRA の走は 競馬場 が「Ｊ札幌」のように「Ｊ」で始まる。地方収得の合計からは除く(中央収得は別勘定)。
 5. 着順の欄は 取消/除外/中止 などの字が入る。数字でなければ fin=null・note にその字。
 6. 同じ馬ページに同じ日・同じ場・同じRは1行しか無い=走の鍵は (d,tr,no)。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
from load_nar_official import load_env, upsert            # noqa: E402
from odds import BABA, JST, http_get, log, _text          # noqa: E402

DEBA_URL = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable"
HORSE_URL = "https://www.keiba.go.jp/KeibaWeb/DataRoom/HorseMarkInfo"
SLEEP = 1.0            # 出馬表(1レース1本)
SLEEP_HORSE = 0.5      # 馬ページ(1頭1本・軽い静的ページ。日次 600 頭で 5 分= Actions の分予算を見て決めた)
T_CODES = "nar_horse_codes"
T_PRIZE = "nar_horse_prize"
CODE_RE = re.compile(r'HorseMarkInfo\?k_lineageLoginCode=(\d{11})"[^>]*>\s*([^<]+?)\s*<')


# ---------------------------------------------------------------- 取得と解析

def deba_codes(date, race_no, baba):
    """出馬表 1 ページ → [(code, 馬名)]。ページが無い(5か月超・未発表)なら []。"""
    url = f"{DEBA_URL}?k_raceDate={date:%Y/%m/%d}&k_raceNo={race_no}&k_babaCode={baba}"
    page = http_get(url).decode("utf-8", "replace")
    seen, out = set(), []
    for code, name in CODE_RE.findall(page):
        if code in seen:
            continue
        seen.add(code)
        out.append((code, _text(name)))
    return out


def _int(s):
    s = (s or "").replace(",", "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def _float(s):
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- 読み違いの番人(2026-10-10 監査 高 #1)
# 走歴表は位置で 23 列を展開する。列の意味は thead の見出しで確かめる(colspan を開いて 23 個)。
# 見出しが違う・データ行が 23 セルでない= 様式が変わった→ ParseGuard(便を止める・書かない)。
# 値の範囲(収得賞金・馬体重・負担重量)と前回との比較(走歴が減る・賞金が非0→0)は 1 頭ずつ見て、外れた馬は書かない。
# 外れの馬が GUARD_N 頭に達したら便を止める(2026-10-09 取得の正しい馬ページ 2 頭 194 走で外れ 0)。
HEAD_EXPECT = ["年月日", "競馬場", "R", "競走名", "格組", "距離", "天候・馬場", "天候・馬場", "天候・馬場",
               "頭数", "枠", "馬番", "人気", "着順", "タイム", "差", "上3F", "体重", "騎手(所属)", "重量",
               "調教師", "収得賞金", "1着馬または(2着馬)"]
PRIZE_MAX = 300_000_000        # 円(1走の収得賞金。地方の最高額 1 着 1 億円の 3 倍を上限に)
BW_RANGE = (250, 750)          # kg(平地)
CW_RANGE = (40.0, 75.0)        # kg(平地の負担重量)
BW_RANGE_BAN = (600, 1400)     # ばんえい(帯広)
CW_RANGE_BAN = (400.0, 1100.0)
GUARD_N = 5                    # 外れの馬がこの数に達したら便を止める


class ParseGuard(Exception):
    """馬ページの走歴表の様式が想定と違う(列の増減・見出しの語の変化)。"""


def head_labels(thead_html):
    """thead → 見出しの語の list(colspan を開く)。"""
    out = []
    for attrs, txt in re.findall(r"<th([^>]*)>(.*?)</th>", thead_html, re.S):
        m = re.search(r'colspan="?(\d+)', attrs)
        out += [_text(txt)] * (int(m.group(1)) if m else 1)
    return out


def run_bad(r):
    """1 走の値の範囲の外れ → 理由の list(空= 通す)。"""
    why = []
    p = r.get("prize")
    if p is None or not (0 <= p <= PRIZE_MAX):
        why.append(f"収得賞金 {p!r}")
    ban = "帯広" in (r.get("tr") or "")
    lo, hi = BW_RANGE_BAN if ban else BW_RANGE
    if r.get("bw") is not None and not (lo <= r["bw"] <= hi):
        why.append(f"馬体重 {r['bw']}")
    lo, hi = CW_RANGE_BAN if ban else CW_RANGE
    if r.get("cw") is not None and not (lo <= r["cw"] <= hi):
        why.append(f"負担重量 {r['cw']}")
    return why


def horse_bad(h, old=None):
    """1 頭の番人。h= parse_horse の戻り・old= 台帳の前の行 {n_runs, local_prize}。→ 理由の list(空= 書いてよい)。"""
    why = []
    for r in h["runs"]:
        b = run_bad(r)
        if b:
            why.append(f"{r.get('d')} {r.get('tr')}{r.get('no')}R " + "・".join(b))
            break
    if old:
        on, nn = old.get("n_runs"), len(h["runs"])
        if on is not None and nn < int(on):
            why.append(f"走歴が {on}→{nn} 走に減る")
        op = old.get("local_prize")
        if op and not h["local_prize"]:
            why.append(f"地方収得賞金が {op:,}→0")
    return why


def parse_horse(page):
    """馬ページ → {name, sex, age, status, runs:[…新しい順], local_prize} / 無ければ None。
    走歴表の見出し・列数が想定と違えば ParseGuard。読めない収得賞金は None(0 にしない= horse_bad で止める)。"""
    if "ご指定の馬の情報がありません" in page:
        return None
    m = re.search(r'class="odd_title">(.*?)</h4>', page, re.S)
    name = _text(m.group(1)) if m else None
    sex = re.search(r'class="sex[^"]*">(.*?)</span>', page, re.S)
    age = re.search(r'class="age[^"]*">(.*?)</span>', page, re.S)
    status = re.search(r"</span>\s*</div>\s*</li>\s*<li>\s*<div>\s*([^<\s][^<]*?)\s*</div>", page, re.S)
    tbl = re.search(r'<table class="HorseMarkInfo_table">(.*?)</table>', page, re.S)
    runs = []
    if tbl:
        th = re.search(r"<thead[^>]*>(.*?)</thead>", tbl.group(1), re.S)
        got = head_labels(th.group(1)) if th else []
        if got != HEAD_EXPECT:
            raise ParseGuard(f"走歴表の見出しが違う({len(got)} 列): {'|'.join(got)[:200]}")
        body = re.search(r"<tbody[^>]*>(.*?)</tbody>", tbl.group(1), re.S)
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(1) if body else "", re.S):
            tds = [_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) != len(HEAD_EXPECT):
                raise ParseGuard(f"走歴の行が {len(tds)} セル(見出しは {len(HEAD_EXPECT)}): {'|'.join(tds)[:120]}")
            (d, tr_, no, rname, cls, dist, weather, going, night, head, waku, uma, ninki, fin,
             tm, margin, l3f, bw, jk, cw, trainer, prize, winner) = tds
            try:
                dd = dt.datetime.strptime(d, "%Y/%m/%d").date().isoformat()
            except ValueError:
                continue
            f = _int(fin)
            runs.append({
                "d": dd, "tr": tr_, "no": _int(no), "name": rname, "cls": cls or None,
                "dist": _int(dist), "wx": weather or None, "go": going or None, "nt": bool(night),
                "head": _int(head), "waku": _int(waku), "uma": _int(uma), "pop": _int(ninki),
                "fin": f, "note": (None if f is not None else (fin or None)),
                "time": tm or None, "mg": margin or None, "l3f": _float(l3f), "bw": _int(bw),
                "jk": jk or None, "cw": _float(cw), "trn": trainer or None,
                "prize": _int(prize), "win": winner or None,
                "jra": tr_.startswith("Ｊ") or tr_.startswith("J"),
            })
    local = sum(r["prize"] or 0 for r in runs if not r["jra"])
    return {"name": name, "sex": _text(sex.group(1)) if sex else None, "age": _int(age.group(1)) if age else None,
            "status": _text(status.group(1)) if status else None, "runs": runs, "local_prize": local}


# ---------------------------------------------------------------- DB

T_PROFILES = "nar_horse_profiles"   # 監査 #21 案 乙(同名の別馬を分ける表。DDL 前は無い= 飛ばす)


def profile_code_rows(profiles, codes):
    """code の空いた profiles [{horse_name, birth_date}] に番号を埋める行。
    ⛔同じ (馬名, 生年月日) に番号が 1 つのときだけ(2 つ以上・生年月日の無い番号は埋めない)"""
    by = {}
    for c in codes:
        if c.get("code") and c.get("horse_name") and c.get("birth_date"):
            by.setdefault((c["horse_name"], str(c["birth_date"])[:10]), set()).add(c["code"])
    out = []
    for p in profiles:
        got = by.get((p.get("horse_name"), str(p.get("birth_date") or "")[:10]))
        if got and len(got) == 1:
            out.append({"horse_name": p["horse_name"], "birth_date": str(p["birth_date"])[:10], "code": next(iter(got))})
    return out


def is_404(e):
    return getattr(e, "code", None) == 404 or getattr(getattr(e, "response", None), "status_code", None) == 404


def fill_profile_codes(url, key, codes, apply, read=None, write=None):
    """③ 監査 #21: nar_horse_profiles.code を nar_horse_codes から埋める。戻り値= 終了コード(0 / 1)。
    表がまだ無い(404)・読めないときは警告 1 行で飛ばす(便は止めない)"""
    try:
        profiles = (read or sb_all)(url, key, f"{T_PROFILES}?select=horse_name,birth_date&code=is.null"
                                              "&order=horse_name.asc,birth_date.asc")
    except Exception as e:                       # noqa: BLE001
        if is_404(e):
            log(f"③ ⚠{T_PROFILES} が無い(HTTP404)= 番号の埋めを飛ばす")
        else:
            log(f"③ ⚠{T_PROFILES} が読めない= 番号の埋めを飛ばす: {type(e).__name__}: {str(e)[:120]}")
        return 0
    rows = profile_code_rows(profiles, codes)
    log(f"③ profiles の番号 空き {len(profiles)} / 埋める {len(rows)}")
    if not apply:
        return 0
    for i in range(0, len(rows), 500):
        st, msg = (write or upsert)(url, key, T_PROFILES, "horse_name,birth_date", rows[i:i + 500])
        if st >= 300 or st == 0:
            log(f"投入失敗 {T_PROFILES} status={st} {msg}")
            return 1
    if rows:
        log(f"投入 {len(rows)} 行 -> {T_PROFILES}.code")
    return 0


def sb_all(url, key, path, page=1000):
    """PostgREST を 1000 行ずつ全部読む(Range ヘッダ)。"""
    out, lo = [], 0
    while True:
        raw = http_get(f"{url}/rest/v1/{path}", {"apikey": key, "Authorization": f"Bearer {key}",
                                                  "Accept": "application/json", "Range": f"{lo}-{lo + page - 1}"})
        rows = json.loads(raw.decode("utf-8"))
        out.extend(rows)
        if len(rows) < page:
            return out
        lo += page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--from", dest="d_from", help="遡り: この日から(既定=今日)")
    ap.add_argument("--to", dest="d_to", help="遡り: この日まで(既定=明日)")
    ap.add_argument("--max-races", type=int, default=400, help="出馬表を引く上限(1本 1 秒)")
    ap.add_argument("--max-horses", type=int, default=1500, help="馬ページを引く上限(1本 1 秒)")
    ap.add_argument("--stale-days", type=int, default=3, help="日次: 直近この日数に走った馬を更新候補にする")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    url = (os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    today = dt.datetime.now(JST).date()
    d_from = dt.date.fromisoformat(args.d_from) if args.d_from else today
    d_to = dt.date.fromisoformat(args.d_to) if args.d_to else today + dt.timedelta(days=1)
    lo = min(d_from, today - dt.timedelta(days=args.stale_days))
    try:
        races = sb_all(url, key, f"nar_races?select=track,race_date,race_no&race_date=gte.{d_from}&race_date=lte.{d_to}"
                                 "&order=race_date.asc,track.asc,race_no.asc")
        runs = sb_all(url, key, f"nar_runs?select=track,race_date,race_no,horse_name,birth_date,finish,finish_note"
                                f"&race_date=gte.{lo}&race_date=lte.{d_to}&order=race_date.asc,track.asc,race_no.asc,runner_number.asc")   # #468 一意な並び
        codes = sb_all(url, key, f"{T_CODES}?select=code,horse_name,birth_date")
        ledger = sb_all(url, key, f"{T_PRIZE}?select=code,last_run,asof,n_runs,local_prize")
    except Exception as e:
        log(f"DB の読み取りに失敗: {type(e).__name__}: {str(e)[:200]}")
        return 2
    log(f"{d_from}〜{d_to}: レース {len(races)} / 出走 {len(runs)}(候補窓 {lo}〜) / 番号 {len(codes)} / 台帳 {len(ledger)}")

    # ---- ① 番号: 出走馬の中で番号が無い馬がいるレースだけ出馬表を引く
    code_by_name = {}
    for c in codes:
        code_by_name.setdefault(c["horse_name"], []).append(c)
    by_race = {}
    for r in runs:
        by_race.setdefault((r["track"], r["race_date"], int(r["race_no"])), []).append(r)
    need_races = []
    for r in races:
        k = (r["track"], r["race_date"], int(r["race_no"]))
        ents = by_race.get(k, [])
        if not ents:
            continue
        if any(not code_by_name.get(e["horse_name"]) for e in ents):
            need_races.append(k)
    need_races = need_races[:args.max_races]
    log(f"① 出馬表を引くレース {len(need_races)}")
    new_codes, bad = [], 0
    for i, (track, date, no) in enumerate(need_races):
        baba = BABA.get(track)
        if not baba:
            continue
        if i:
            time.sleep(SLEEP)
        try:
            pairs = deba_codes(dt.date.fromisoformat(date), no, baba)
        except Exception as e:
            bad += 1
            log(f"  取得失敗 {track} {date} {no}R: {type(e).__name__}: {str(e)[:100]}")
            continue
        births = {e["horse_name"]: e.get("birth_date") for e in by_race[(track, date, no)]}
        for code, name in pairs:
            if any(c["code"] == code for c in code_by_name.get(name, [])):
                continue
            row = {"code": code, "horse_name": name, "birth_date": births.get(name), "seen_track": track, "seen_date": date}
            new_codes.append(row)
            code_by_name.setdefault(name, []).append(row)
    log(f"① 新しい番号 {len(new_codes)}(失敗 {bad})")
    if new_codes and args.apply:
        st, msg = upsert(url, key, T_CODES, "code", new_codes)
        if st >= 300 or st == 0:
            log(f"投入失敗 {T_CODES} status={st} {msg}")
            return 1
        log(f"投入 {len(new_codes)} 行 -> {T_CODES}")

    # ---- ② 馬ページ: 窓の中で走った(走る)馬のうち、台帳が無いか、台帳の最終走より新しい走が nar_runs にある馬
    last_by_name = {}
    for r in runs:
        # ⚠結果(着順か取消等の字)が入った走だけ数える= 出馬表の段階の行を「走った」と見なすと、
        #   公式の馬ページにまだ無い走を待って1日じゅう引き直してしまう
        if r["race_date"] <= today.isoformat() and (r.get("finish") is not None or r.get("finish_note")):
            n = r["horse_name"]
            if r["race_date"] > last_by_name.get(n, ""):
                last_by_name[n] = r["race_date"]
    led = {x["code"]: x for x in ledger}
    targets, seen_t = [], set()
    for r in runs:
        for c in code_by_name.get(r["horse_name"], []):
            code = c["code"]
            L = led.get(code)
            last = last_by_name.get(r["horse_name"], "")
            if (L is None or (L.get("last_run") or "") < last) and code not in seen_t:
                seen_t.add(code)
                targets.append(code)
    targets = targets[:args.max_horses]
    log(f"② 馬ページを引く馬 {len(targets)}")
    rows, miss, bad, held = [], 0, 0, []
    for i, code in enumerate(targets):
        if i:
            time.sleep(SLEEP_HORSE)
        try:
            page = http_get(f"{HORSE_URL}?k_lineageLoginCode={code}").decode("utf-8", "replace")
        except Exception as e:
            bad += 1
            log(f"  取得失敗 {code}: {type(e).__name__}: {str(e)[:100]}")
            continue
        try:
            h = parse_horse(page)
        except ParseGuard as e:
            print(f"::error::馬ページの様式が変わった疑いで止める(この回の残り {len(rows)} 行は書かない) {code}: {e}", flush=True)
            return 2
        if h is None or not h["name"]:
            miss += 1
            log(f"  情報なし {code}")
            continue
        why = horse_bad(h, led.get(code))
        if why:
            held.append(code)
            print(f"::warning::{code} {h['name']} を書かない(番人): " + " / ".join(why), flush=True)
            if len(held) >= GUARD_N:
                print(f"::error::番人の外れが {len(held)} 頭= 読み違いの疑いで止める(この回の残り {len(rows)} 行は書かない)", flush=True)
                return 2
            continue
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        rows.append({"code": code, "horse_name": h["name"], "sex": h["sex"], "age": h["age"], "status": h["status"],
                     "local_prize": h["local_prize"], "runs": h["runs"], "n_runs": len(h["runs"]),
                     "last_run": h["runs"][0]["d"] if h["runs"] else None,
                     "last_cls": next((r["cls"] for r in h["runs"] if r["cls"] and not r["jra"]), None),
                     "asof": now, "updated_at": now})
        if len(rows) % 200 == 0 and args.apply:
            st, msg = upsert(url, key, T_PRIZE, "code", rows)
            if st >= 300 or st == 0:
                log(f"投入失敗 {T_PRIZE} status={st} {msg}")
                return 1
            log(f"  投入 {len(rows)} 行 -> {T_PRIZE}(途中)")
            rows = []
    log(f"② 取得 {len(targets) - miss - bad} / 情報なし {miss} / 失敗 {bad} / 番人で保留 {len(held)}")
    if rows:
        log(f"  例: {rows[0]['horse_name']} 走 {rows[0]['n_runs']} 地方収得 {rows[0]['local_prize']:,} 直近の格組 {rows[0]['last_cls']}")
        if args.apply:
            st, msg = upsert(url, key, T_PRIZE, "code", rows)
            if st >= 300 or st == 0:
                log(f"投入失敗 {T_PRIZE} status={st} {msg}")
                return 1
            log(f"投入 {len(rows)} 行 -> {T_PRIZE}")
    # ---- ③ 監査 #21: profiles.code を埋める(同じ (馬名,生年月日) に番号 1 つのときだけ)
    if fill_profile_codes(url, key, [c for cs in code_by_name.values() for c in cs], args.apply):
        return 1
    if not args.apply:
        log("dry-run: 書かない")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    log(f"終了 rc={rc} ({time.time() - t0:.0f}s)")
    sys.exit(rc)
