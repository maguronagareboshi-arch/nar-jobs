# -*- coding: utf-8 -*-
"""§56.4 / 56-3 運営の確認 —— 利用者の**メモとマイホース**の一覧を**手元に落とす**ためのジョブ。

公開サイトに管理画面を作らない(§56.4 の再判断: §58 の管理者経路にも載せない)。
GitHub Actions の workflow_dispatch で手で起動し、artifact として落とす。

  python cloud/viewer_export.py --env pipeline/.env.nar --out out    # ドライラン(掃除もしない)
  python cloud/viewer_export.py --out out --purge-tries              # 本番(workflow はこちら)

出すもの(--out の中):
  notes.csv                メモ一覧(端末ハッシュ・馬・本文・日時)
  horses.csv               マイホースの一覧(端末ハッシュ・馬・馬名・登録日時)= §56.13 2-3
  by_device.csv            端末ごとの件数(⭐メモ何件・馬何頭が1行で分かる)
  by_horse.csv             馬ごとの**メモ**の件数
  by_horse_registered.csv  馬ごとの**登録**の数(⭐人気の馬・登録した端末数の多い順)= §56.13 2-3
  counts.json              4表の行数と、掃除した行数

⛔**device_id は出さない**。実質パスワード(§56.2)= 持っていればその端末の行を書き換えられる。
  代わりに `md5(device_id)` の**先頭8文字**だけを出す(同じ端末をまとめて見る目的はこれで足りる)。
  ⚠ハッシュは Python 側で作る= 生の device_id は artifact にもログにも出さない。
  ⛔**作り方は全ファイル共通**(`short()` 1か所)= 同じ端末は notes.csv と horses.csv で**同じハッシュ**になる
  (突き合わせられないと「その端末が何をしているか」が読めない)。
⛔このジョブは**読むだけ+掃除だけ**。メモ本文は1文字も書き換えない(UPDATE も INSERT もしない)。
⛔掃除の対象は `nar_viewer_claim_tries` の**1時間より古い行**だけ(#237 の増え続ける経路を受ける)。
  ⚠この「1時間」は DB 側 `viewer_handover_claim` の掃除と同じ値(揃えて直すこと)。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
UA = "unified-viewer/1.0 (+maguronagareboshi@gmail.com)"
PAGE = 1000                      # ⛔PostgREST の 1000 行上限(#8/#92)= 必ず範囲で刻んで読む
TRIES_KEEP_HOURS = 1             # ⚠DB 側 viewer_handover_claim の掃除と同じ値
HASH_LEN = 8                     # §56.4「substr(md5(device_id),1,8)」


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def req(base, key, path, method="GET", prefer=None):
    headers = {
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Accept": "application/json", "Accept-Encoding": "gzip",
    }
    if prefer:
        headers["Prefer"] = prefer
    r = urllib.request.Request(base + path, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=90) as x:
        raw = x.read()
        if x.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return x.status, raw.decode("utf-8"), x.headers


def rows_all(base, key, table, select, order):
    """1000行ずつ全部読む(⛔silent cap を踏まない)。"""
    out, off = [], 0
    while True:
        _, body, _ = req(base, key,
                         f"/rest/v1/{table}?select={select}&order={order}&limit={PAGE}&offset={off}")
        part = json.loads(body)
        out += part
        if len(part) < PAGE:
            return out
        off += PAGE
        if off > 200000:                       # 念のための止め(想定外に増えていたら気づけるように)
            log(f"⚠{table} が 20万行を超えた。読むのをここで止めた")
            return out


def count_of(base, key, table, filt=""):
    _, _, h = req(base, key, f"/rest/v1/{table}?select=*&limit=1{filt}", prefer="count=exact")
    cr = h.get("Content-Range") or ""
    return int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1].isdigit() else None


def short(device_id):
    """⛔device_id は出さない= md5 の先頭8文字だけにする(同じ端末をまとめる目的には足りる)。"""
    return hashlib.md5(str(device_id).encode("utf-8")).hexdigest()[:HASH_LEN]


def write_csv(path, cols, rows):
    # Excel が日本語をそのまま開けるように BOM 付き。改行やカンマを含む本文は csv が引用符で包む
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    log(f"{os.path.basename(path)}: {len(rows):,}行")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--out", default="viewer-export")
    ap.add_argument("--purge-tries", action="store_true",
                    help="nar_viewer_claim_tries の古い行を消す(付けないと数えるだけ)")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        return 2
    os.makedirs(a.out, exist_ok=True)
    now = dt.datetime.now(JST)

    # ---- ①メモ一覧(⛔device_id は読むが、出すのはハッシュだけ) ----
    notes = rows_all(base, key, "nar_viewer_notes",
                     "device_id,horse_id,body,created_at,updated_at", "updated_at.desc")
    log(f"メモ {len(notes):,}件")
    rows = [[short(n.get("device_id")), n.get("horse_id"), n.get("body"),
             n.get("created_at"), n.get("updated_at")] for n in notes]
    write_csv(os.path.join(a.out, "notes.csv"),
              ["device_hash", "horse_id", "body", "created_at", "updated_at"], rows)

    # ---- ②マイホースの一覧(§56.13 2-3。⛔ハッシュの作り方はメモと同じ `short()`) ----
    horses = rows_all(base, key, "nar_viewer_horses",
                      "device_id,horse_id,name,added_at", "added_at.desc,horse_id.asc")
    log(f"登録した馬 {len(horses):,}件")
    write_csv(os.path.join(a.out, "horses.csv"),
              ["device_hash", "horse_id", "name", "added_at"],
              [[short(h.get("device_id")), h.get("horse_id"), h.get("name"), h.get("added_at")]
               for h in horses])

    # ---- ③端末ごとの件数(⛔メモが0件でも**馬があれば載せる**= 馬だけの利用者を落とさない) ----
    # ⚠first/last は「その端末が最初/最後に**何かを保存した**時刻」= メモと馬の両方から取る
    by_dev = {}

    def dev_of(device_id):
        return by_dev.setdefault(short(device_id), {"n": 0, "h": 0, "first": None, "last": None})

    def stamp(e, *times):
        for t in times:
            t = str(t or "")
            if not t:
                continue
            if e["first"] is None or t < e["first"]:
                e["first"] = t
            if e["last"] is None or t > e["last"]:
                e["last"] = t

    for n in notes:
        e = dev_of(n.get("device_id"))
        e["n"] += 1
        stamp(e, n.get("created_at"), n.get("updated_at"))
    for h in horses:
        e = dev_of(h.get("device_id"))
        e["h"] += 1
        stamp(e, h.get("added_at"))
    write_csv(os.path.join(a.out, "by_device.csv"), ["device_hash", "notes", "horses", "first", "last"],
              [[d, v["n"], v["h"], v["first"], v["last"]]
               for d, v in sorted(by_dev.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["h"], kv[0]))])

    # ---- ④馬ごとの**メモ**の件数 ----
    by_horse = {}
    for n in notes:
        h = str(n.get("horse_id") or "")
        e = by_horse.setdefault(h, {"n": 0, "devs": set()})
        e["n"] += 1
        e["devs"].add(short(n.get("device_id")))
    write_csv(os.path.join(a.out, "by_horse.csv"), ["horse_id", "notes", "devices"],
              [[h, v["n"], len(v["devs"])]
               for h, v in sorted(by_horse.items(), key=lambda kv: (-kv[1]["n"], kv[0]))])

    # ---- ⑤⭐人気の馬(登録した端末数の多い順)。§56.13 2-3 ----
    # ⚠(device_id, horse_id) が主キー= 1端末1行なので「行数=登録した端末数」。
    #   馬名は**いちばん新しい行**のものを採る(端末ごとに違うことは普通ないが、揃わないときの決め方を固定する)
    by_reg = {}
    for h in horses:                                   # ⛔読み出しは added_at の新しい順
        hid = str(h.get("horse_id") or "")
        e = by_reg.setdefault(hid, {"devs": set(), "name": ""})
        e["devs"].add(short(h.get("device_id")))
        if not e["name"]:
            e["name"] = str(h.get("name") or "")
    write_csv(os.path.join(a.out, "by_horse_registered.csv"), ["horse_id", "name", "devices"],
              [[hid, v["name"], len(v["devs"])]
               for hid, v in sorted(by_reg.items(), key=lambda kv: (-len(kv[1]["devs"]), kv[0]))])

    # ---- ⑤掃除(#237: 存在しないコードを試すたびに増える行。⛔1時間より古いものだけ) ----
    cut = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=TRIES_KEEP_HOURS)).isoformat()
    path = f"/rest/v1/nar_viewer_claim_tries?last_at=lt.{urllib.parse.quote(cut, safe='')}"
    old = count_of(base, key, "nar_viewer_claim_tries",
                   f"&last_at=lt.{urllib.parse.quote(cut, safe='')}")
    purged = 0
    if a.purge_tries:
        _, body, h = req(base, key, path, method="DELETE", prefer="return=representation")
        try:
            purged = len(json.loads(body))
        except Exception:
            purged = -1
        log(f"掃除: {TRIES_KEEP_HOURS}時間より古い試行行を {purged} 行消した")
    else:
        log(f"掃除はしない(--purge-tries を付けると消す)。古い試行行は {old} 行")

    # ---- ⑥4表の行数 ----
    # ⛔既存の鍵の**意味は変えない**(`devices`=メモを書いた端末数・`horses`=メモが付いた馬の種類数)。
    #   §56.13 2-3 のぶんは**別の鍵で足す**(読み違えると「登録が0なのに馬が2」に見えるため)
    note_devs = len({short(n.get("device_id")) for n in notes})
    counts = {
        "generated_at": now.isoformat(),
        "notes": count_of(base, key, "nar_viewer_notes"),
        "handover": count_of(base, key, "nar_viewer_handover"),
        "claim_tries": count_of(base, key, "nar_viewer_claim_tries"),
        "devices": note_devs,
        "horses": len(by_horse),
        "viewer_horses": count_of(base, key, "nar_viewer_horses"),
        "horse_devices": len({short(h.get("device_id")) for h in horses}),
        "horse_ids": len(by_reg),
        "devices_total": len(by_dev),
        "claim_tries_purged": purged if a.purge_tries else 0,
        "note": "device_id は出していない(md5 の先頭8文字だけ)。§56.4",
        "legend": {
            "notes": "表 nar_viewer_notes の行数", "devices": "メモを書いた端末の数",
            "horses": "メモが付いた馬の種類数",
            "viewer_horses": "表 nar_viewer_horses の行数(=登録の総数)",
            "horse_devices": "マイホースを登録している端末の数", "horse_ids": "登録された馬の種類数",
            "devices_total": "メモか馬のどちらかを保存している端末の数",
        },
    }
    io.open(os.path.join(a.out, "counts.json"), "w", encoding="utf-8").write(
        json.dumps(counts, ensure_ascii=False, indent=1) + "\n")
    log("行数: メモ %s / 登録 %s / 引き継ぎ %s / 試行 %s"
        % (counts["notes"], counts["viewer_horses"], counts["handover"], counts["claim_tries"]))
    log("端末: メモを書いた %d ・馬を登録した %d ・どちらか %d / 馬: メモ付き %d 種・登録 %d 種"
        % (counts["devices"], counts["horse_devices"], counts["devices_total"],
           counts["horses"], counts["horse_ids"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
