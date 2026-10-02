# -*- coding: utf-8 -*-
"""§119a 全15場ぶんの追加データを取る（馬具・前半3F 等 + 調教・厩舎の話）。

設計= docs/proposal_s119_keibabook_extra_20260906.md（統合ビューア側）。
既存の fetch.py（門別・南関の毎日の段）は**触らない**。こちらは「全場ぶんを JSON に出す」だけで、
DB へは投入しない（--push は無い）。投入は Fable が別途おこなう。

  py -3 -u scraper/fetch_kb_all.py --date 20260905 --what seiseki              # 昨日の成績（全場）
  py -3 -u scraper/fetch_kb_all.py --date 20260906 --what syutuba,cyokyo,danwa # 今日（全場）
  py -3 -u scraper/fetch_kb_all.py --since 20260801 --what seiseki             # 遡り（1日ずつ・済みはスキップ）
  py -3 -u scraper/fetch_kb_all.py --date 20260905 --what seiseki --track 高知  # 場を絞る（部分一致）

出力（data/kb_all/）:
  runs_{YYYYMMDD}.json  … 1行1馬。{track, race_date, race_no, umaban, horse_name, kb_race_id,
                           blinker, gear, first3f, avg_f, pace, kimete, start_note}
                           ⚠同じ日に何度流しても**足し合わせる**（朝に出馬表→翌日に成績、の順で埋まる）
  notes_{YYYYMMDD}.json … {race_id: {"cyokyo": …, "danwa": …}}。既存の push_race がそのまま受ける形。
                           ⛔門別・大井・船橋・川崎・浦和（既存5場）は入れない＝ 既存の段が入れているため
  done.tsv              … 日付・what・場数・レース数・馬数・所要秒（--since の冪等の鍵）
                           ⛔§157 6-1: **その日の R が全部そろった日だけ**・**今日は書かない**。
                           取り直しは `--redo`(全部)か `--redo 20260910,20260911`(その日だけ)。

⛔DB には書かない。⛔ログイン情報・待ち時間（2.5秒）は既存の .env / KeibabookClient のまま。
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fetch import DATA, fetch_race, make_client                          # noqa: E402
from parsers import parse_nittei, race_id_parts                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = DATA / "kb_all"
DONE = OUT / "done.tsv"

# レースIDの場コード（6-8桁目）→ **公式の場名**。⛔競馬ブックの見出しは略称なので名前では引かない
#   （2026-09-06 に日程ページ400日ぶんで確かめた。名古→名古屋・帯広→帯広ば だけが違う）
KB_TRACK = {
    "42": "門別", "33": "盛岡", "29": "水沢", "13": "浦和", "12": "船橋", "10": "大井",
    "11": "川崎", "20": "金沢", "19": "笠松", "34": "名古屋", "37": "園田", "39": "姫路",
    "26": "高知", "23": "佐賀", "58": "帯広ば",
}
# 調教・厩舎の話を既存の段（fetch.py --push）が毎日入れている5場。notes には入れない
KB_EXISTING = {"42", "10", "12", "11", "13"}
# runs に出す鍵（⛔この順・この鍵だけ。増やすときは設計書の表と一緒に）
RUN_KEYS = ("track", "race_date", "race_no", "umaban", "horse_name", "kb_race_id",
            "blinker", "gear", "first3f", "avg_f", "pace", "kimete", "start_note",
            "corner4_pos", "comment")  # 2026-10-02: 4 角の内外・寸評(南関特化 AI の材料と「ひとこと」)

# 2026-09-29 X3: 成績頁の備考(決め手・馬装具・発走状況他)が**後から載る**ことがある
#   (園田の水・木= 翌日昼の取得で 3 つとも空→ 9/29 に取り直すと値あり)。
#   着順は揃っても 3 つとも空の R は「まだそろっていない」扱い= done にせず、キャッシュも消して次の便で取り直す。
#   ⛔上限= レース日から BIKOU_RETRY_DAYS 日まで。それを過ぎたら空のままでも済みにする
#   (元から備考の無い場・頁で毎日取り直し続けないため。毎日の便は --since 7 日前= 7 日で打ち切り)。
BIKOU_KEYS = ("決め手", "馬装具", "発走状況他")
BIKOU_RETRY_DAYS = 7


def bikou_pending(parsed):
    """着順はあるのに備考 3 欄(決め手・馬装具・発走状況他)が全部空= 備考がまだ載っていない頁"""
    if not parsed or not parsed.get("results"):
        return False
    extra = (parsed.get("race") or {}).get("extra") or {}
    return all(extra.get(k) is None for k in BIKOU_KEYS)


def bikou_retry_open(date, today_str=None):
    """その日がまだ取り直しの窓の中か(レース日から BIKOU_RETRY_DAYS 日未満)"""
    t = dt.datetime.strptime(today_str or today(), "%Y%m%d").date()
    d = dt.datetime.strptime(date, "%Y%m%d").date()
    return (t - d).days < BIKOU_RETRY_DAYS


def log(msg):
    print(msg, flush=True)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        log(f"! {path.name} が読めないので作り直す")
        return default


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def done_keys():
    """done.tsv に入っている (日付, what) の組"""
    if not DONE.exists():
        return set()
    out = set()
    for line in DONE.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) >= 2:
            out.add((cols[0], cols[1]))
    return out


def done_key(what, track):
    """done.tsv の 2 列目= what に場を付ける(2026-09-06 Fable: 場を絞った日が「全場済み」に見えないように)"""
    return ",".join(what) + (f"@{track}" if track else "")


def mark_done(date, what, meets, races, horses, secs, track=""):
    OUT.mkdir(parents=True, exist_ok=True)
    with DONE.open("a", encoding="utf-8") as f:
        f.write(f"{date}\t{done_key(what, track)}\t{meets}\t{races}\t{horses}\t{secs:.0f}\n")


def track_of(race_id):
    return KB_TRACK.get(race_id[6:8], race_id[6:8])


def row_key(race_id, umaban):
    return f"{race_id}/{umaban}"


def merge_rows(rows, race_id, umaban, values):
    """同じ馬の行を足し合わせる（出馬表の blinker と 成績の gear が別の日に来るため）。
    ⛔None で上書きしない＝ 先に入っている事実を消さない。"""
    key = row_key(race_id, umaban)
    row = rows.setdefault(key, {k: None for k in RUN_KEYS})
    for k, v in values.items():
        if v is not None or row.get(k) is None:
            row[k] = v


def collect_day(client, date, what, track, logged_in, refresh=False):
    """1日ぶん。返り値 = (場数, レース数, 馬数, 結果のそろったレース数)"""
    try:
        html = client.get(client.nittei_path(date), refresh=refresh or date >= today())
    except Exception as e:
        log(f"{date}: 日程ページ取得失敗 ({e})")
        return 0, 0, 0, 0      # 2026-09-12 Fable: 返り値は 4 つ(場・R・馬・そろった R)= 呼び側とそろえる
    meets = parse_nittei(html)
    mmdd = date[4:8]
    for m in meets:
        m["races"] = [r for r in m["races"] if r["race_id"][12:16] == mmdd]
    # 2026-09-06 Fable: --track はカンマ区切りで複数可(部分一致のどれか)
    tracks = [x.strip() for x in (track or "").split(",") if x.strip()]
    meets = [m for m in meets if m["races"] and (not tracks or any(x in m["track"] for x in tracks))]
    if not meets:
        log(f"{date}: {track or '全場'} の開催なし")
        return 0, 0, 0, 0

    runs_path = OUT / f"runs_{date}.json"
    notes_path = OUT / f"notes_{date}.json"
    # ⚠前の回の結果に**足す**（朝の出馬表と翌日の成績が同じ日のファイルに入る）
    rows = {row_key(r["kb_race_id"], r["umaban"]): dict(r)
            for r in read_json(runs_path, {"runs": []})["runs"]}
    notes = read_json(notes_path, {})

    n_races = 0
    n_full = 0          # §157 6-1 結果が取れた R(未発走は数えない)
    # ⛔再ログインして取り直すのは **1 便に 1 回だけ**。1 回で直らなければ以後は諦める=
    #   佐賀のように前半3F が元から無い場で「1 レースごとにログインし直して 40 秒」を起こさない
    #   (2026-09-06 実測)。⛔場ごとの分岐は作らない
    retry_login = [1]
    for meet in meets:
        log(f"{date} {meet['track']} {len(meet['races'])}R")
        for race in meet["races"]:
            rid = race["race_id"]
            try:
                # ⚠logged_in は**渡さない**（既定 False）。前半3F を出していない場（佐賀など）は
                #   seiseki_is_masked が「伏せ字」と判定するので、渡すと 1 レースごとに
                #   ログインし直して取り直し、40 秒以上かかる（2026-09-06 実測）。
                #   ⛔fetch.py は触らない約束なので、呼び方の側で起こさないようにする。
                # §157 6-1 伏せ字だったら**1 便に 1 回だけ**ログインし直して取り直す。
                #   ⛔fetch.py は触らない= 呼び方の側で回数を抑える。
                out = fetch_race(client, rid, what, refresh=refresh, push=False,
                                 logged_in=bool(retry_login[0]))
            except Exception as e:
                log(f"  ! {rid}: 取得失敗 ({e})")
                continue
            n_races += 1
            if "seiseki" in out and bikou_pending(out["seiseki"]) and bikou_retry_open(date):
                # X3: 備考がまだ無い= そろった R に数えない(done にしない)・キャッシュを消して次の便で取り直す
                client.drop_cache(client.seiseki_path(rid))
                log(f"  … {rid}: 着順はあるが備考(決め手・馬装具・発走状況他)が空= 後の便で取り直す")
            elif "seiseki" in out:
                n_full += 1
            if "seiseki" in out:
                # 取り直しても全頭 None のままなら、その便では以後ログインし直さない
                if retry_login[0] and all(r.get("first3f") is None for r in out["seiseki"]["results"]):
                    retry_login[0] = 0
            base = {"track": track_of(rid), "race_date": race_id_parts(rid)["date"],
                    "race_no": race_id_parts(rid)["race_no"], "kb_race_id": rid}
            if "seiseki" in out:
                for r in out["seiseki"]["results"]:
                    merge_rows(rows, rid, r["umaban"], dict(
                        base, umaban=r["umaban"], horse_name=r["horse_name"],
                        gear=r.get("gear"), first3f=r.get("first3f"), avg_f=r.get("avg_f"),
                        pace=r.get("pace"), kimete=r.get("kimete"),
                        start_note=r.get("start_note"),
                        corner4_pos=r.get("corner4_pos"), comment=r.get("comment")))
            if "syutuba" in out:
                for e in out["syutuba"]["entries"]:
                    merge_rows(rows, rid, e["umaban"], dict(
                        base, umaban=e["umaban"], horse_name=e["horse_name"],
                        blinker=e.get("blinker")))
            # ⛔既存5場の調教・厩舎の話は既存の段が入れているので notes に入れない
            if rid[6:8] not in KB_EXISTING:
                got = {k: out[k] for k in ("cyokyo", "danwa") if k in out}
                if got:
                    notes.setdefault(rid, {}).update(got)

    runs = [{k: row.get(k) for k in RUN_KEYS} for row in rows.values()]
    runs.sort(key=lambda r: (str(r["track"]), r["race_no"] or 0, r["umaban"] or 0))
    write_json(runs_path, {"date": date, "runs": runs})
    log(f"{date}: runs {len(runs)} 行 -> {runs_path.name}"
        f"（ブリンカ {sum(1 for r in runs if r['blinker'])} / 馬装具 {sum(1 for r in runs if r['gear'])}"
        f" / 前半3F {sum(1 for r in runs if r['first3f'] is not None)}）")
    if notes:
        write_json(notes_path, notes)
        tracks = sorted({track_of(rid) for rid in notes})
        log(f"{date}: notes {len(notes)} レース {tracks} -> {notes_path.name}")
    return len(meets), n_races, len(runs), n_full


def today():
    return dt.date.today().strftime("%Y%m%d")


def main():
    ap = argparse.ArgumentParser(description="§119a 全15場の馬具・前半3F 等＋調教・厩舎の話")
    ap.add_argument("--date", help="YYYYMMDD（1日だけ）")
    ap.add_argument("--since", help="YYYYMMDD（この日から今日まで1日ずつ）")
    ap.add_argument("--what", default="seiseki",
                    help="seiseki,syutuba,cyokyo,danwa のカンマ区切り（既定: seiseki）")
    ap.add_argument("--track", default="", help="場名の部分一致で絞る（既定: 全場）。カンマ区切りで複数可")
    ap.add_argument("--no-login", action="store_true", help="ログインせず公開部分のみ")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    ap.add_argument("--redo", nargs="?", const="all", default=None,
                    help="done.tsv にある日もやり直す(--redo= 全部 / --redo 20260910,20260911= その日だけ)")
    args = ap.parse_args()
    if not args.date and not args.since:
        ap.error("--date か --since のどちらかが要ります")
    args.what = [w.strip() for w in args.what.split(",") if w.strip()]
    bad = [w for w in args.what if w not in ("seiseki", "syutuba", "cyokyo", "danwa", "nouryoku")]
    if bad:
        ap.error(f"--what に知らない語: {bad}")

    if args.date:
        dates = [args.date]
    else:
        d = dt.datetime.strptime(args.since, "%Y%m%d").date()
        end = dt.date.today()
        dates = []
        while d <= end:
            dates.append(d.strftime("%Y%m%d"))
            d += dt.timedelta(days=1)

    client, logged_in = make_client(args)
    # §157 6-1 `--redo` は全部(all)か、日付をカンマで並べた分だけ
    redo_all = args.redo == "all"
    redo_days = set() if redo_all or not args.redo else {d.strip() for d in args.redo.split(",") if d.strip()}
    already = set() if redo_all else done_keys()
    key = done_key(args.what, args.track)
    n_days = 0
    for date in dates:
        if (date, key) in already and date not in redo_days:
            log(f"{date}: 済み（done.tsv）スキップ")
            continue
        t0 = time.time()
        meets, races, horses, full = collect_day(client, date, args.what, args.track, logged_in,
                                                 refresh=args.refresh)
        secs = time.time() - t0
        # ⛔§157 6-1 「済み」にするのは **その日の R が全部そろった日だけ**、しかも **今日は書かない**。
        #   便は 13:00 に走り、夜のレースは必ず「未発走」なので、0 頭のまま「済み」にすると
        #   翌日から永久に飛ばされる(2026-09-08〜11 で実際に起きた)。
        if races and full == races and date < today():
            mark_done(date, args.what, meets, races, horses, secs, args.track)
            n_days += 1
        elif races:
            log(f"{date}: まだそろっていない（{full}/{races}R）= 済みにしない")
        log(f"{date}: {meets}場 {races}R {horses}頭 {secs / 60:.1f}分")
    log(f"おわり: {n_days} 日ぶん（{key}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
