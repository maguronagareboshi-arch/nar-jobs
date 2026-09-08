# -*- coding: utf-8 -*-
"""§45 能検組の初出走(デビュー)を見落とさない —— 出馬表×能検索引の突合(ユーザーFB② 2026-08-27)。

今日と明日の出馬表(nar_runs。⛔公式の出馬表は翌日ぶんまでしか出ない=#146)に載った馬のうち、
①能検索引(nar_meta 'noken_index')に記録があり ②nar_runs に走った履歴が無い馬(⛔#199: 走った=着順あり or 競走中止・失格。出走取消・競走除外は走っていない=js didRun と同じ定義)
= 「能検上がりの初出走」を nar_meta 'noken_debuts' に書く。/noken ハブの「もうすぐ初出走」が読む。

  python cloud/noken_debuts.py --env pipeline/.env.nar            # ドライラン(表示だけ)
  python cloud/noken_debuts.py --env pipeline/.env.nar --apply    # 書き込み
workflow(nar-refresh.yml)では daily/monthly の両方で回す(3〜4クエリ・数秒・冪等)。

⛔馬名で突き合わせる=同名馬の限界は §26.5 と同じ(解は §38 1-B の血統登録番号)。
⛔「初出走」= nar_runs に結果付きの行が無いこと。取消だけの馬は初出走扱いのまま(走っていないのは事実)。
⛔候補ゼロの日も {days:[]} を**書く**(書かないと画面が古い日を出し続ける)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", body=None):
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json", "Accept-Encoding": "gzip",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(r, timeout=90) as x:
        raw = x.read()
        if x.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return x.status, raw.decode("utf-8")


def rows(base, key, path):
    _, body = req(base, key, path)
    return json.loads(body)


def enc(s):
    return urllib.parse.quote(s, safe="")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2

    today = dt.datetime.now(JST).date()
    dates = [str(today), str(today + dt.timedelta(days=1))]

    got = rows(base, key, "/rest/v1/nar_meta?select=value&key=eq.noken_index")
    horses = (got[0]["value"].get("horses") if got else None) or {}
    log(f"能検索引 {len(horses):,}頭")

    # 今日+明日の出馬表(⛔1日1000行上限に静かに当たらないよう日別に引く=#92。1日は最大でも約1,200行
    #  だが、必要列だけ+レース番号順で引き、1000行ちょうどなら警告を出して落とす)
    cand = []            # (date, track, race_no, horse_name)
    for d in dates:
        rs = rows(base, key, "/rest/v1/nar_runs?select=track,race_no,horse_name"
                             f"&race_date=eq.{d}&order=track.asc,race_no.asc,runner_number.asc&limit=1000")
        if len(rs) >= 1000:
            log(f"⚠ {d} の出馬表が1000行上限に当たった疑い(この日は落とす=嘘の一覧を書かない)")
            continue
        for r in rs:
            nm = str(r.get("horse_name") or "")
            if nm and nm in horses:
                cand.append((d, str(r.get("track")), int(r.get("race_no")), nm))
    log(f"出馬表×索引の当たり {len(cand)}頭({' / '.join(dates)})")

    # 発走時刻(§45 v2 ユーザーFB 2026-08-28)。1日の nar_races は最大 15場×12R=180行なので日別1本で足りる
    ht = {}              # (date, track, race_no) -> 'H:MM'
    if cand:
        for d in dates:
            rs = rows(base, key, "/rest/v1/nar_races?select=track,race_no,post_time"
                                 f"&race_date=eq.{d}&limit=1000")
            for r in rs:
                # post_time は '1420' 型(4桁・区切りなし。2026-08-28 実測)。'14:20' 型が来ても受ける
                m = re.match(r"^(\d{1,2}):?(\d{2})$", str(r.get("post_time") or "").strip())
                if m:
                    ht[(d, str(r.get("track")), int(r.get("race_no")))] = f"{int(m.group(1))}:{m.group(2)}"

    # 走った履歴の有無(結果付きの行があるか)。
    # ⛔#196(2026-08-29 修理): 旧版は in.() 80頭×limit=1000 を**1回だけ**引いていた=チャンクの走行行が
    # 合計1000行を超えると溢れた馬が「履歴なし」になり、**何走もしている転入馬が「もうすぐ初出走」に出た**
    # (実害= 2026-08-28 の笠松7頭・園田3頭。スプリングカムは4走目だった)。PostgREST の1000行静かな上限(#8)の再来。
    # 直し= ①索引の ran(デビュー済みの旗・#187)が付いた馬は照会せず即「走った」 ②残りだけ、
    # horse_name=gt.カーソルで**取り切るまで**ページ送り(js/data.js ranNames と同じ作法)
    debuts = []
    if cand:
        names = sorted({nm for _, _, _, nm in cand})
        seen_run = {n for n in names
                    if any(isinstance(r, dict) and r.get("ran") == 1 for r in (horses.get(n) or []))}
        todo = [n for n in names if n not in seen_run]
        log(f"走った判定: 索引の ran で即断 {len(seen_run)}頭 / 生照会 {len(todo)}頭")
        for i in range(0, len(todo), 80):
            chunk = todo[i:i + 80]
            inlist = ",".join('"' + n.replace('"', '') + '"' for n in chunk)
            frm = None
            for _page in range(20):
                ran_filter = "or=" + enc('(finish.not.is.null,finish_note.in.("競走中止","失格"))')
                rs = rows(base, key, "/rest/v1/nar_runs?select=horse_name"
                                     f"&horse_name=in.({enc(inlist)})&{ran_filter}"
                                     "&order=horse_name.asc&limit=1000"
                                     + (f"&horse_name=gt.{enc(frm)}" if frm else ""))
                got = [str(r.get("horse_name") or "") for r in rs]
                seen_run.update(n for n in got if n)
                if len(rs) < 1000:
                    break
                if not got or got[-1] == frm:
                    log("⚠ ページ送りが進まない(このチャンクは打ち切り=見えた馬だけ除外)")
                    break
                frm = got[-1]
            else:
                log("⚠ ページ送りが20回に達した(異常。このチャンクは見えた馬だけ除外)")
        for d, track, no, nm in cand:
            if nm in seen_run:
                continue
            # ⛔#197(2026-08-29 修理): 索引は**新しい順**なので最新の検査は [0]。旧版の [-1] は最古を出していた
            # (実害は未発= 表示対象の馬は全頭1件だけだったが、ばんえいの再受検馬が来たら最古の検査を出すところだった)
            latest = (horses.get(nm) or [{}])[0] if isinstance(horses.get(nm), list) else {}
            debuts.append({"date": d, "track": track, "no": no, "name": nm,
                           **({"ht": ht[(d, track, no)]} if (d, track, no) in ht else {}),
                           # a/ar/t1(上がり・順位・テン1F)も持たせる=画面が A-1 の統一様式で全部出せる(#150)。
                           # v/s(映像)は入れない=▶は押した1頭だけ索引を引く画面側の設計(§45)のまま
                           "noken": {k: latest.get(k) for k in ("d", "p", "date", "time", "ok", "r", "n", "tr", "a", "ar", "t1")
                                     if latest.get(k) is not None}})
    log(f"初出走(履歴なし) {len(debuts)}頭")
    for x in debuts[:20]:
        log(f"  {x['date']} {x['track']} {x['no']}R {x['name']} 能検 {x['noken'].get('date','-')} {x['noken'].get('time','-')}")

    value = {"built": dt.datetime.now(JST).isoformat(timespec="seconds"),
             "dates": dates, "debuts": debuts}
    if not a.apply:
        log("ドライラン(--apply で書く)"); return 0
    st, _ = req(base, key, "/rest/v1/nar_meta?on_conflict=key", "POST",
                json.dumps([{"key": "noken_debuts", "value": value,
                             "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}]).encode("utf-8"))
    log(f"nar_meta/noken_debuts 更新 {st}")
    return 0 if st in (200, 201) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
