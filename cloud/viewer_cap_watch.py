"""閲覧者が書ける 7 表の行数の見張り(2026-11-14 総合レビュー security #3 の続き)。

本番 DB の各表には insert 前の trigger _viewer_cap で「全体の行数の上限」がある
(nar-viewer pipeline/sql/nar_viewer_cap_20261114.sql)。上限に届くと保存が止まるが、
近づいたことを知らせる物が無かった。ここで行数を数え、上限の半分を超えた表を返す。

数え方= PostgREST の HEAD + Prefer count=exact(行は読まない・送信量はほぼ 0)。
⚠上限の数を変えたら CAPS もそろえる(SQL の trigger の引数と同じ値)。
"""
import os
import urllib.request

CAPS = {
    "nar_viewer_notes": 20000,
    "nar_viewer_horses": 30000,
    "nar_viewer_people": 10000,
    "nar_viewer_reviews": 30000,
    "nar_push_subs": 5000,
    "nar_viewer_handover": 2000,
    "nar_viewer_claim_tries": 2000,
}
WARN_RATIO = 0.5


def count_rows(table, timeout=20):
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
    req = urllib.request.Request(f"{url}/rest/v1/{table}?select=*", method="HEAD",
                                 headers={"apikey": key, "Authorization": "Bearer " + key,
                                          "Prefer": "count=exact", "Range": "0-0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cr = r.headers.get("Content-Range") or ""
    total = cr.rsplit("/", 1)[-1]
    if not total.isdigit():
        raise RuntimeError(f"{table} の行数が読めない(Content-Range={cr!r})")
    return int(total)


def judge(counts, caps=CAPS, ratio=WARN_RATIO):
    """counts= {表: 行数 or 例外の文字}。赤の理由の一覧を返す(空なら異常なし)。"""
    bad = []
    for t, cap in caps.items():
        n = counts.get(t)
        if not isinstance(n, int):
            bad.append(f"閲覧者の表 {t} の行数が読めない({n})")
        elif n >= cap * ratio:
            bad.append(f"閲覧者の表 {t} が上限の半分を超えた({n}/{cap} 行・外から埋められている疑い)")
    return bad


def check():
    counts = {}
    for t in CAPS:
        try:
            counts[t] = count_rows(t)
        except Exception as e:  # 1 表が読めなくても残りは数える
            counts[t] = f"{type(e).__name__}: {e}"
    return counts, judge(counts)


if __name__ == "__main__":
    c, b = check()
    for t, n in c.items():
        print(f"  {t:24s} {n} / {CAPS[t]}")
    for x in b:
        print("::error::" + x)
    raise SystemExit(1 if b else 0)
