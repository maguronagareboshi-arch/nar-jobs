# -*- coding: utf-8 -*-
"""競馬ブックWeb 地方版スクレイパー CLI（門別中心・他場も可）

使い方（プロジェクトルート = 他場/ で実行）:
  python scraper/fetch.py day 20260701                      # 門別の成績+出馬表を取得
  python scraper/fetch.py day 20260701 --what seiseki       # 成績のみ
  python scraper/fetch.py range 20260401 20260430           # 期間まとめて（過去分の蓄積用）
  python scraper/fetch.py race 2026064205010701 --what seiseki
  オプション: --track 門別 / --no-login / --refresh / --push

出力: data/json/seiseki/{race_id}.json, data/json/syutuba/{race_id}.json
--push を付けると Supabase (chihou_* テーブル) へupsert。
"""

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from keibabook import KeibabookClient, LoginError
from parsers import (parse_cyokyo, parse_danwa, parse_nittei, parse_nouryoku, parse_seiseki,
                     parse_syutuba, race_id_parts, seiseki_is_masked)

ROOT = Path(__file__).resolve().parent.parent
# cloud(2026-09-29): 保存先は KB_DATA_DIR(Actions の一時フォルダ)。⛔repo の中に頁・取得物を置かない
DATA = Path(os.environ["KB_DATA_DIR"]) if os.environ.get("KB_DATA_DIR") else ROOT / "data"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_env():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def save_json(kind, race_id, obj):
    d = DATA / "json" / kind
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{race_id}.json"
    f.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return f


def make_client(args):
    load_env()
    client = KeibabookClient(
        login_id=os.environ.get("KEIBABOOK_LOGIN_ID"),
        password=os.environ.get("KEIBABOOK_PASSWORD"),
        data_dir=DATA,
        wait_seconds=float(os.environ.get("FETCH_WAIT_SECONDS", "2.5")),
    )
    logged_in = False
    if not args.no_login:
        if not client.login_id:
            print("! .env に KEIBABOOK_LOGIN_ID が無いため非ログインで動きます（前半3F等は取れません）")
        else:
            try:
                how = client.ensure_login()
                logged_in = True
                print("ログインOK" + ("（保存済みCookieを再利用）" if how == "cookie" else "（新規ログイン+SSO）"))
            except LoginError as e:
                print(f"! ログイン失敗: {e}")
                sys.exit(1)
    return client, logged_in


def fetch_race(client, race_id, what, refresh=False, push=False, logged_in=False):
    """1レース分を取得・保存。成績が伏せ字のままなら警告。"""
    out = {}
    if "seiseki" in what:
        path = client.seiseki_path(race_id)
        html = client.get(path, refresh=refresh)
        parsed = parse_seiseki(html, race_id)
        if parsed["results"] and seiseki_is_masked(parsed):
            # 古いキャッシュ or セッション切れの可能性。再ログインして1回だけ取り直す
            if logged_in:
                client.ensure_login()
                html = client.get(path, refresh=True)
                parsed = parse_seiseki(html, race_id)
            if seiseki_is_masked(parsed):
                # 伏せ字のままのHTMLをキャッシュに残さない（次回取り直せるように）
                client.drop_cache(path)
                print(f"  ! {race_id}: 前半3Fが伏せ字のまま（未ログイン or 地方版会員でない）")
        if not parsed["results"]:
            # 未発走・中止などで結果が無いページもキャッシュしない
            client.drop_cache(path)
            print(f"  ! {race_id}: 結果なし（未発走?）スキップ")
            return out
        f = save_json("seiseki", race_id, parsed)
        # Keep the compact exact-date linker index current without rescanning
        # the multi-year result archive.  Bootstrap/recovery remains an
        # explicit admin command; if an installed index cannot be verified,
        # fail here instead of silently serving stale provenance.
        result_index = DATA / "derived" / "nouryoku_official_result_index_v1.json"
        if result_index.exists():
            from update_nouryoku_result_index import update_index_files

            update_index_files(result_index, [f])
        n = len(parsed["results"])
        got3f = sum(1 for r in parsed["results"] if r["first3f"] is not None)
        print(f"  seiseki {race_id}: {n}頭 前半3F取得{got3f}頭 -> {f.name}")
        out["seiseki"] = parsed
    # 未来・当日のレースは出馬表/調教が更新されうるので取り直す
    is_upcoming = race_id_parts(race_id)["date"] >= dt.date.today().strftime("%Y%m%d")
    if "syutuba" in what:
        html = client.get(client.syutuba_path(race_id), refresh=refresh or is_upcoming)
        parsed = parse_syutuba(html, race_id)
        f = save_json("syutuba", race_id, parsed)
        print(f"  syutuba {race_id}: {len(parsed['entries'])}頭 -> {f.name}")
        out["syutuba"] = parsed
    if "cyokyo" in what:
        html = client.get(client.cyokyo_path(race_id), refresh=refresh or is_upcoming)
        parsed = parse_cyokyo(html, race_id)
        f = save_json("cyokyo", race_id, parsed)
        n_works = sum(len(h["works"]) for h in parsed["horses"])
        print(f"  cyokyo  {race_id}: {len(parsed['horses'])}頭 {n_works}本 -> {f.name}")
        out["cyokyo"] = parsed
    if "nouryoku" in what:
        html = client.get(client.nouryoku_path(race_id), refresh=refresh or is_upcoming)
        parsed = parse_nouryoku(html, race_id)
        if not parsed["horses"]:
            # 能力表は古いレースだと削除されている（2023年以前）。空ページは保存しない
            client.drop_cache(client.nouryoku_path(race_id))
            print(f"  ! nouryoku {race_id}: データなし（掲載期間終了）スキップ")
        else:
            f = save_json("nouryoku", race_id, parsed)
            n_runs = sum(len(h["runs"]) for h in parsed["horses"])
            print(f"  nouryoku {race_id}: {len(parsed['horses'])}頭 過去走{n_runs}本 -> {f.name}")
            out["nouryoku"] = parsed
    if "danwa" in what:
        html = client.get(client.danwa_path(race_id), refresh=refresh or is_upcoming)
        parsed = parse_danwa(html, race_id)
        if not parsed["horses"]:
            client.drop_cache(client.danwa_path(race_id))
            print(f"  ! danwa {race_id}: データなし（掲載期間終了 or 未掲載）スキップ")
        else:
            f = save_json("danwa", race_id, parsed)
            n_c = sum(1 for h in parsed["horses"] if h["comment"])
            print(f"  danwa   {race_id}: {len(parsed['horses'])}頭 コメント{n_c}件 -> {f.name}")
            out["danwa"] = parsed
    if push and out:
        from supabase_push import push_race
        push_race(out)
        print(f"  supabase: {race_id} をupsertしました")
    return out


def cmd_day(client, date, args, logged_in=False):
    # 日程は当日・未来なら更新されうるので毎回取り直す
    is_past = date < dt.date.today().strftime("%Y%m%d")
    try:
        html = client.get(client.nittei_path(date), refresh=not is_past or args.refresh)
    except Exception as e:
        print(f"{date}: 日程ページ取得失敗 ({e})")
        return
    meets = parse_nittei(html)
    # 日程ページは前後の日も表示するので、この日のレースIDだけに絞る
    mmdd = date[4:8]
    for m in meets:
        m["races"] = [r for r in m["races"] if r["race_id"][12:16] == mmdd]
    targets = [m for m in meets if args.track in m["track"] and m["races"]] if args.track \
        else [m for m in meets if m["races"]]
    if not targets:
        print(f"{date}: {args.track or '対象場'} の開催なし")
        return
    for meet in targets:
        print(f"{date} {meet['track']} {len(meet['races'])}R", flush=True)
        for race in meet["races"]:
            try:
                fetch_race(client, race["race_id"], args.what, refresh=args.refresh,
                           push=args.push, logged_in=logged_in)
            except Exception as e:
                print(f"  ! {race['race_id']}: 取得失敗 ({e})")


def main():
    ap = argparse.ArgumentParser(description="keibabook chihou scraper")
    ap.add_argument("command", choices=["day", "range", "race"])
    ap.add_argument("arg1", help="day: YYYYMMDD / range: 開始日 / race: レースID(16桁)")
    ap.add_argument("arg2", nargs="?", help="range: 終了日YYYYMMDD")
    ap.add_argument("--track", default="門別", help="対象の場名（部分一致、既定: 門別）")
    ap.add_argument("--what", default="seiseki,syutuba", help="seiseki,syutuba,cyokyo,nouryoku,danwa のカンマ区切り")
    ap.add_argument("--no-login", action="store_true", help="ログインせず公開部分のみ取得")
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    ap.add_argument("--push", action="store_true", help="Supabaseへupsertする")
    args = ap.parse_args()
    args.what = [w.strip() for w in args.what.split(",") if w.strip()]

    client, logged_in = make_client(args)

    if args.command == "race":
        fetch_race(client, args.arg1, args.what, refresh=args.refresh,
                   push=args.push, logged_in=logged_in)
    elif args.command == "day":
        cmd_day(client, args.arg1, args, logged_in=logged_in)
    elif args.command == "range":
        if not args.arg2:
            ap.error("range には終了日が必要です")
        d = dt.datetime.strptime(args.arg1, "%Y%m%d").date()
        end = dt.datetime.strptime(args.arg2, "%Y%m%d").date()
        while d <= end:
            cmd_day(client, d.strftime("%Y%m%d"), args, logged_in=logged_in)
            d += dt.timedelta(days=1)


if __name__ == "__main__":
    main()
