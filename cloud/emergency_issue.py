# -*- coding: utf-8 -*-
"""緊急のときだけ日本語の issue を立てて持ち主へメールを届ける(2026-11-17)。

持ち主は GitHub の英語の失敗メールが読めない= 便ごとのメールは持ち主が止め、緊急 4 種だけここで issue にする。
リポは public= 本文は平易な日本語だけ(鍵・DB の URL・表の名前・内部の符号は書かない)。

  python3 cloud/emergency_issue.py --kind ai --title "…" --what "…" --impact "…" [--todo "…"] [--dry-run]
      … 同じ種別の issue が開いていれば何もしない(コメントも足さない= メールを増やさない)
  python3 cloud/emergency_issue.py --resolve ai [--dry-run]
      … 開いている同じ種別の issue に「【解決】戻りました(何時何分)」を 1 回付けて閉じる
  python3 cloud/emergency_issue.py --from-needs [--dry-run]
      … nar-watchdog の notify から。env NEEDS(= toJSON(needs))で live/ai/cost を判定して立てる/閉じる
  python3 cloud/emergency_issue.py --test
      … 試しの issue を 1 件立ててすぐ閉じる(持ち主に試しのメールが 1 通届く)

env: GH_TOKEN(GITHUB_TOKEN・issues: write だけ)・GITHUB_REPOSITORY。⛔標準ライブラリだけ・DB は読まない書かない。
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

OWNER = "@maguronagareboshi-arch"   # 持ち主はリポを watch していない= メンションで通知メールを届ける
JST = dt.timezone(dt.timedelta(hours=9))
KINDS = ("site", "live", "ai", "cost")
TODO = "AI の会話で「緊急メール見て」と言うだけで大丈夫です。"

# 種別ごとの決まった文(判定の理由の生の字は本文に入れない)
TEXT = {
    "site": ("【緊急】サイト(yukochi.com)が開けません",
             "サイトのトップか画面の部品が、10 分おきの点検で続けて 2 回開けませんでした。",
             "見ている人はサイトを開けないか、画面が崩れています。"),
    "live": ("【緊急】開催日の出馬表・オッズ・結果が止まっています",
             "{cause}",
             "見ている人の画面で、今日の情報が古いままです。"),
    "ai": ("【緊急】AI 予想が出ていないか、いつもの作りで出ていないレースがあります",
           "{cause}",
           "見ている人の画面で、一部のレースの AI 予想が出ていないか、いつもより当てにならない値で出ています。"),
    "cost": ("【緊急】データの置き場がいっぱいに近づいています",
             "{cause}",
             "このままだと、データの保存が止まり、サイトの更新も止まるおそれがあります。"),
}


# ---------------------------------------------------------------- 判定(純関数・通信なし)
def _red(v):
    v = v or {}
    o = v.get("outputs") or {}
    return str(o.get("red", "")).lower() == "true" or v.get("result") in ("failure", "cancelled")


def _reasons(v):
    try:
        return [str(x) for x in json.loads(((v or {}).get("outputs") or {}).get("reasons") or "[]")]
    except (TypeError, ValueError):
        return []


def _num(v, key):
    try:
        return float(((v or {}).get("outputs") or {}).get(key))
    except (TypeError, ValueError):
        return None


def _ran(needs, jobs):
    """jobs が全部この run で動いた(skipped でない)か。"""
    return all((needs.get(j) or {}).get("result") in ("success", "failure") for j in jobs)


LIVE_JOBS = ("freshness", "odds-live", "heartbeat")
AI_JOBS = ("v3-forecast", "banei")
COST_JOBS = ("db-size",)


def classify(needs, now):
    """toJSON(needs) → {kind: 'open' 理由文(平易) / 'ok' / None(この run では判定しない)}。site は site-up.yml が見る。"""
    needs = needs or {}
    out = {}
    # live: 「当日の画面に出る情報が 1 時間以上止まっている」と言えるものだけ
    cause = []
    age = _num(needs.get("freshness"), "age_min")
    if age is not None and age >= 180:
        cause.append(f"出馬表などのレースの情報が {int(age // 60)} 時間以上 新しくなっていません。")
    st = _num(needs.get("odds-live"), "stale_min")
    if st is not None and st >= 60:
        cause.append("発走の近いレースがあるのに、オッズが 1 時間以上 新しくなっていません。")
    if any(r.startswith("refresh の最終成功が 70 分より古い") for r in _reasons(needs.get("heartbeat"))):
        cause.append("出馬表・結果を取り込む定期の処理が 1 時間以上 成功していません。")
    out["live"] = " ".join(cause) if cause else ("ok" if _ran(needs, LIVE_JOBS) else None)
    # ai: (a) 南関 v3 の見張りの赤(予想の無いレース・直前版の抜け)・ばんえいの朝/直前の版の抜け
    cause = []
    rs = _reasons(needs.get("v3-forecast"))
    feat = [r for r in rs if r.startswith("材料の欠け")]   # v3_watch.FEAT_TAG
    if _red(needs.get("v3-forecast")) and (not rs or len(feat) < len(rs)):
        cause.append("AI 予想の点検で、予想が出ていないレースが見つかりました。")
    if feat:
        cause.append("AI 予想が、いつもの材料がそろわないまま(古い作りか、空の値が多いまま)出ているレースがあります。")
    rs = _reasons(needs.get("banei"))
    if any(("朝の版が" in r or "直前の版が無い" in r) for r in rs):
        cause.append("ばんえいの AI 予想が出ていないレースがあります。")
    if any("控えの模型" in r for r in rs):
        cause.append("ばんえいの AI 予想が、その日の学び直しに失敗し、前の日の模型のまま出ています。")
    # 10 時前は v3 の見張りが今日を見ない= 緑でも「直った」とは言えない
    out["ai"] = " ".join(cause) if cause else ("ok" if _ran(needs, AI_JOBS) and now.hour >= 10 else None)
    # cost: 「このままだと止まる」ものだけ(DB 全体の大きさ・閲覧者が書ける表の上限の半分)
    cause = []
    rs = _reasons(needs.get("db-size"))
    if any(r.startswith("DB の大きさ: DB 全体") for r in rs):
        cause.append("データの置き場の全体の大きさが、注意の線を越えました。")
    if any("上限の半分を超えた" in r for r in rs):
        cause.append("見ている人が書き込める保存の数が、上限の半分を越えました(外から埋められている疑い)。")
    out["cost"] = " ".join(cause) if cause else ("ok" if _ran(needs, COST_JOBS) else None)
    return out


def body(what, impact, todo=TODO):
    return (f"{OWNER}\n\n"
            f"**何が起きたか**: {what}\n\n"
            f"**見ている人への影響**: {impact}\n\n"
            f"**あなたがやること**: {todo}\n")


# ---------------------------------------------------------------- GitHub(issues だけ)
def _api(method, path, data=None):
    repo = os.environ.get("GITHUB_REPOSITORY", "maguronagareboshi-arch/nar-jobs")
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}", method=method,
                                 data=None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                 headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read().decode("utf-8")
    return json.loads(t) if t else None


def open_issue(label):
    got = _api("GET", f"issues?state=open&labels={label}&per_page=10") or []
    got = [i for i in got if "pull_request" not in i]
    return got[0] if got else None


def ensure_label(label):
    try:
        _api("POST", "labels", {"name": label, "color": "d73a4a"})
    except urllib.error.HTTPError as e:
        if e.code != 422:   # 422 = もうある
            raise


def raise_issue(kind, title, what, impact, todo=TODO, dry=False, label=None):
    label = label or f"emergency-{kind}"
    text = body(what, impact, todo)
    if dry:
        print(f"[dry-run] ラベル {label}\n件名: {title}\n本文:\n{text}")
        return None
    cur = open_issue(label)
    if cur:
        print(f"同じ種別の issue #{cur['number']} が開いている= 立てない(メールを増やさない)")
        return cur
    ensure_label(label)
    got = _api("POST", "issues", {"title": title, "body": text, "labels": [label]})
    print(f"issue を立てた: {got['html_url']}")
    return got


def resolve(kind, dry=False, label=None):
    label = label or f"emergency-{kind}"
    n = dt.datetime.now(JST)
    msg = f"【解決】戻りました({n.month} 月 {n.day} 日 {n.hour} 時 {n.minute} 分)"
    if dry:
        print(f"[dry-run] 開いている {label} があれば「{msg}」を付けて閉じる")
        return None
    cur = open_issue(label)
    if not cur:
        return None
    _api("POST", f"issues/{cur['number']}/comments", {"body": msg})
    _api("PATCH", f"issues/{cur['number']}", {"state": "closed", "state_reason": "completed"})
    print(f"issue #{cur['number']} を閉じた: {msg}")
    return cur


def from_needs(needs, now, dry=False):
    for kind, v in classify(needs, now).items():
        print(f"{kind}: {v}")
        if v is None:
            continue
        try:
            if v == "ok":
                resolve(kind, dry)
            else:
                title, what, impact = TEXT[kind]
                raise_issue(kind, title, what.format(cause=v), impact, dry=dry)
        except Exception as e:   # noqa: BLE001  1 種別の失敗で他を止めない
            print(f"::warning::緊急の issue の処理が失敗({kind}): {type(e).__name__} {str(e)[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--title")
    ap.add_argument("--what")
    ap.add_argument("--impact")
    ap.add_argument("--todo", default=TODO)
    ap.add_argument("--resolve", choices=KINDS)
    ap.add_argument("--from-needs", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.from_needs:
        from_needs(json.loads(os.environ.get("NEEDS") or "{}"), dt.datetime.now(JST), a.dry_run)
        return 0
    if a.resolve:
        resolve(a.resolve, a.dry_run)
        return 0
    if a.test:
        got = raise_issue("ai", "【緊急・試し】AI 予想の点検の試しです",
                          "これは試しです。何もしなくて大丈夫です。", "ありません(試しです)。",
                          "何もしなくて大丈夫です。", dry=a.dry_run, label="emergency-test")
        if got:
            _api("PATCH", f"issues/{got['number']}", {"state": "closed", "state_reason": "completed"})
            print(f"試しの issue を閉じた: {got['html_url']}")
        return 0
    if not (a.kind and a.title and a.what and a.impact):
        ap.error("--kind --title --what --impact が要る")
    if not re.match(r"^【緊急", a.title):
        a.title = "【緊急】" + a.title
    raise_issue(a.kind, a.title, a.what, a.impact, a.todo, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
