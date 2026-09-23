# -*- coding: utf-8 -*-
"""定期便の最終成功時刻(表 nar_job_heartbeat・関数 nar_beat)を書く/読む。監査 A1 A2 A8(2026-09-24)。

  python3 cloud/beat.py <job> ok|fail [補足]   … nar_beat(p_job, p_ok, p_note) を REST で呼ぶ
  python3 cloud/beat.py --today <job>         … last_ok が JST の今日なら 1・違えば 0・読めなければ ?
  python3 cloud/beat.py --due <job> <秒>      … last_ok が今日でない かつ (last_try が今日でない or <秒> 以上前) なら 1・違えば 0・読めなければ ?
  python3 cloud/beat.py --dump                … 全行を JSON 1 行で出す(読めなければ空行・exit 3)

⛔標準ライブラリだけ(setup-python の無い便でも python3 で動く)。
⛔表・関数がまだ無い/DB が読めないときも便を落とさない= 書く方は常に exit 0(log だけ残す)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(service_role)。
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
TABLE = "nar_job_heartbeat"


def _env():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return url, key


def _req(path, body=None, timeout=20):
    url, key = _env()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method="GET" if body is None else "POST",
                                 headers={"apikey": key, "Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def beat(job, ok=True, note=None):
    """nar_beat を呼ぶ。失敗しても例外を出さない(True= 書けた)。"""
    try:
        _req("rpc/nar_beat", {"p_job": job, "p_ok": bool(ok), "p_note": note})
        print(f"heartbeat {job} {'ok' if ok else 'fail'}" + (f" ({note})" if note else ""), flush=True)
        return True
    except Exception as e:                          # noqa: BLE001
        print(f"⚠heartbeat {job} が書けない(続行): {type(e).__name__}: {str(e)[:120]}", flush=True)
        return False


def rows():
    """全行 → {job: row}。読めなければ None。"""
    try:
        got = _req(f"{TABLE}?select=job,last_ok,last_try,last_status,note")
        return {r["job"]: r for r in got or []}
    except Exception as e:                          # noqa: BLE001
        print(f"⚠{TABLE} が読めない: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return None


def jst_date(ts):
    """timestamptz の文字列 → JST の日付(空なら None)。"""
    if not ts:
        return None
    t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(JST).date()


def ok_today(job, got=None):
    """last_ok が JST の今日か。True/False・読めなければ None。"""
    got = rows() if got is None else got
    if got is None:
        return None
    r = got.get(job)
    return bool(r) and jst_date(r.get("last_ok")) == dt.datetime.now(JST).date()


def _ts(v):
    if not v:
        return None
    t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(JST)


def due(job, retry_sec, got=None):
    """今日まだ成功していない かつ 最後の試みが今日でない/retry_sec 以上前 → True。読めなければ None。
    ⛔失敗しても retry_sec に 1 回までしか回り直さない(監査 A1)。"""
    got = rows() if got is None else got
    if got is None:
        return None
    r = got.get(job) or {}
    now = dt.datetime.now(JST)
    ok, tr = _ts(r.get("last_ok")), _ts(r.get("last_try"))
    if ok is not None and ok.date() == now.date():
        return False
    return tr is None or tr.date() != now.date() or (now - tr).total_seconds() >= retry_sec


def main(argv):
    if len(argv) >= 3 and argv[0] == "--due":
        v = due(argv[1], int(argv[2]))
        print("?" if v is None else ("1" if v else "0"))
        return 0
    if len(argv) >= 2 and argv[0] == "--today":
        v = ok_today(argv[1])
        print("?" if v is None else ("1" if v else "0"))
        return 0
    if argv and argv[0] == "--dump":
        got = rows()
        if got is None:
            print("")
            return 3
        print(json.dumps(got, ensure_ascii=False))
        return 0
    if len(argv) < 2 or argv[1] not in ("ok", "fail"):
        print("使い方: beat.py <job> ok|fail [補足] / --today <job> / --dump", file=sys.stderr)
        return 0
    beat(argv[0], argv[1] == "ok", " ".join(argv[2:]) or None)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")     # 手元の cp932 でも log の記号で落ちない
        except Exception:                        # noqa: BLE001
            pass
    try:
        rc = main(sys.argv[1:])
    except Exception as e:                       # noqa: BLE001(⛔便を落とさない)
        print(f"heartbeat: 想定外の失敗(続行) {type(e).__name__}", file=sys.stderr)
        rc = 0
    sys.exit(rc)
