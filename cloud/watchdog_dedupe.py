# -*- coding: utf-8 -*-
"""nar-watchdog の「同じ赤のメールは 1 日 1 通」(2026-10-03 監査 B-1: 同じ警告で毎時メールが来た)。

  python3 cloud/watchdog_dedupe.py   … env NEEDS(= toJSON(needs))から赤の理由を集め、nar_meta 'watchdog_last_red' と比べる

各 job は点検の手順を continue-on-error にして outputs red(true/false)・reasons(JSON の配列)を出す。
  赤なし                         → 保存を消して exit 0(次に赤になったら 1 通目として出る)
  同じ JST 日付で理由が全部既出 → ::warning:: 今日は通知済み・exit 0(メールが出ない)
  それ以外(初回・新しい理由・日付が変わった)→ 保存して exit 1(= 所有者へ失敗メール)
⛔標準ライブラリだけ。nar_meta が読めない/書けないときは「初回」とみなして鳴らす側に倒す。
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beat  # noqa: E402

META_KEY = "watchdog_last_red"


# ---------------------------------------------------------------- 純関数(通信なし)
def summarize(text):
    """::error:: の文言 → 日時や数字を除いた要約(数字の並びは # 1 字に)。"""
    s = re.sub(r"\d+", "#", str(text or ""))
    return re.sub(r"\s+", " ", s).strip()


def collect(needs):
    """toJSON(needs) の dict → 要約した理由の集合(並べた list)。"""
    out = set()
    for job, v in sorted((needs or {}).items()):
        v = v or {}
        o = v.get("outputs") or {}
        red = str(o.get("red", "")).lower() == "true" or v.get("result") in ("failure", "cancelled")   # 時間切れの取り消しも赤
        if not red:
            continue
        try:
            rs = json.loads(o.get("reasons") or "[]")
        except (TypeError, ValueError):
            rs = []
        rs = [summarize(r) for r in rs if summarize(r)]
        out.update(rs or [f"{job} が赤"])
    return sorted(out)


def decide(prev, today, reasons):
    """prev= 前回の保存({date, reasons} か None)・today= JST の 'YYYY-MM-DD'・reasons= 今回の要約。
    戻り= (action, save)。action は 'clear'(赤なし= 消す)/'silent'(通知済み)/'notify'(鳴らす)。
    save は notify のときに保存する値(同じ日なら前回分との和)。"""
    reasons = sorted(set(reasons or []))
    if not reasons:
        return "clear", None
    prev = prev if isinstance(prev, dict) else None
    same_day = bool(prev) and prev.get("date") == today
    old = set(prev.get("reasons") or []) if same_day else set()
    if same_day and set(reasons) <= old:
        return "silent", None
    return "notify", {"date": today, "reasons": sorted(old | set(reasons))}


# ---------------------------------------------------------------- 通信(beat.py と同じ REST)
def _read():
    got = beat._req(f"nar_meta?select=value&key=eq.{META_KEY}")
    return (got[0]["value"] if got else None) or None


def _send(method, path, rows=None, prefer="return=minimal"):
    url, key = beat._env()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    data = None if rows is None else json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method=method,
                                 headers={"apikey": key, "Authorization": "Bearer " + key,
                                          "Content-Type": "application/json", "Prefer": prefer})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def _save(value):
    _send("POST", "nar_meta?on_conflict=key",
          [{"key": META_KEY, "value": value, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}],
          prefer="resolution=merge-duplicates,return=minimal")


def _clear():
    _send("DELETE", f"nar_meta?key=eq.{META_KEY}")


def main():
    needs = json.loads(os.environ.get("NEEDS") or "{}")
    reasons = collect(needs)
    today = dt.datetime.now(beat.JST).date().isoformat()
    try:
        prev = _read()
    except Exception as e:                          # noqa: BLE001
        print(f"⚠nar_meta {META_KEY} が読めない(初回とみなす): {type(e).__name__}", flush=True)
        prev = None
    action, save = decide(prev, today, reasons)
    for r in reasons:
        print("赤の理由:", r)
    if action == "clear":
        print("赤なし= 保存を消す")
        if prev is not None:
            try:
                _clear()
            except Exception as e:                  # noqa: BLE001
                print(f"⚠nar_meta {META_KEY} を消せない: {type(e).__name__}", flush=True)
        return 0
    if action == "silent":
        print(f"::warning::今日は通知済み({today}・同じ理由 {len(reasons)} 件)= メールは出さない")
        return 0
    try:
        _save(save)
    except Exception as e:                          # noqa: BLE001
        print(f"⚠nar_meta {META_KEY} が書けない(次も鳴る): {type(e).__name__}", flush=True)
    print(f"::error::新しい赤 {len(reasons)} 件= 通知する")
    return 1


if __name__ == "__main__":
    sys.exit(main())
