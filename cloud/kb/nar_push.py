# -*- coding: utf-8 -*-
r"""§157(2026-09-12) 本体(nar-official)への投入口。⛔旧 DB には書かない。

  鍵= C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\.env.nar の
      SUPABASE_URL / SUPABASE_SERVICE_KEY を**その場で読む**。
      ⛔os.environ には入れない・⛔印字しない(push_kb_runs.py と同じ作法)。

  使う側:
    from nar_push import upsert, upsert_meta
    upsert("nar_kb_works", rows, "track,race_date,race_no,umaban")
    upsert_meta("nar_kb_private", "monbetsu_stats", {...})

⛔鍵が無いときは **例外を投げずに False を返す**= 便の途中で落とさない(呼ぶ側が「送らない」を言う)。
"""
import json
import os
import urllib.request
from pathlib import Path

NAR_ENV = Path(r"C:\Users\kouki\OneDrive\デスクトップ\s77-w1\pipeline\.env.nar")
CHUNK = 500


def read_env(path=NAR_ENV):
    """.env を辞書で返す。⛔値はここから外に出さない(呼ぶ側も印字しない)。"""
    # cloud(2026-09-30): 鍵は secrets→環境変数 SUPABASE_URL / SUPABASE_SERVICE_KEY(⛔印字しない)
    if os.environ.get("SUPABASE_URL"):
        return {"SUPABASE_URL": os.environ["SUPABASE_URL"],
                "SUPABASE_SERVICE_KEY": os.environ.get("SUPABASE_SERVICE_KEY", "")}
    env = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def creds():
    """(base, key)。どちらか無ければ (None, None)。"""
    env = read_env()
    base = (env.get("SUPABASE_URL") or "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_KEY") or ""
    return (base, key) if base and key else (None, None)


def _post(url, key, body):
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": key, "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status not in (200, 201, 204):
            raise RuntimeError("HTTP %s" % resp.status)


def upsert(table, rows, on_conflict):
    """行をまとめて upsert。⛔鍵が無ければ False(何も送らない)。"""
    rows = [r for r in (rows or []) if r]
    if not rows:
        return True
    base, key = creds()
    if not base:
        return False
    url = "%s/rest/v1/%s?on_conflict=%s" % (base, table, on_conflict)
    for i in range(0, len(rows), CHUNK):
        _post(url, key, json.dumps(rows[i:i + CHUNK], ensure_ascii=False).encode("utf-8"))
    return True


def upsert_meta(table, key_name, value):
    """`key`/`value` の 1 行だけの表(nar_meta / nar_kb_private)へ。"""
    return upsert(table, [{"key": key_name, "value": value}], "key")
