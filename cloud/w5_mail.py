# -*- coding: utf-8 -*-
"""5重勝(オッズパークのセレクト5重勝・競馬)の今日の買い目を管理者にメールで送る(2026-11-22・管理者だけ・公開しない)。

決まり(研究 nankan-ai-v3 の src/w5_picks.py と同じ・照合 out/banei_w5_picks_check_1122.md):
  帯広  : 持ち越し 10 万円以上の日だけ・1 日 200 点まで。各 R 1 頭から (当たる率の伸び ÷ 点数の増え) が一番大きい R に 1 頭ずつ足す
          (2026-11-22 ばんえい第 5 版で選び直し)
  佐賀・園田・水沢・笠松: 持ち越しのある日だけ・各 R で AI の上位 3 頭
  盛岡・姫路: 買わない
AI = nar_ai_marks の朝の行(帯広 banei-3・他場 v3n-1)の meta.runners の p1(他場は混ぜる前の p1_raw があればそれ)。
⛔お金は動かさない(買い目を知らせるだけ)。⛔メールの宛先・送り手・鍵はコードに書かない(GitHub の秘密)。

  python cloud/w5_mail.py [--date YYYY-MM-DD] [--dry-run]
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / W5_MAIL_USER(送り手の Gmail)/ W5_MAIL_PASS(その アプリ パスワード)/ W5_MAIL_TO
終了コード: 0 = 送った・対象なし・dry-run / 1 = 送れなかった / 2 = 前提が足りない
"""
import argparse
import datetime as dt
import json
import os
import re
import smtplib
import sys
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.header import Header

JST = dt.timezone(dt.timedelta(hours=9))
LOTO_URL = "https://www.oddspark.com/loto/JResultList.do?kaisaiBi="
# オッズパークの場の番号 → (場名, model, 持ち越しの線, 決まり)
RULE = {"03": ("帯広ば", "banei-3", 100000, ("budget", 200)), "61": ("佐賀", "v3n-1", 1, 3), "51": ("園田", "v3n-1", 1, 3),
        "12": ("水沢", "v3n-1", 1, 3), "42": ("笠松", "v3n-1", 1, 3), "11": ("盛岡", None, 0, 0), "52": ("姫路", None, 0, 0)}


def num(s):
    return int(s.replace(",", ""))


def http(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_loto(html):
    """一覧の頁 → [{jo, races, co}](競馬の 5 レースの組だけ)。"""
    out = []
    for hd, tb in re.findall(r'<h3>(.*?)</h3>\s*<table class="tb70 w100pr">(.*?)</table>', html, re.S):
        rn = re.findall(r'joCode=(\d+)&amp;raceNo=(\d+)', tb)
        if "ico-horse" not in hd or len(rn) != 5:
            continue
        st = re.findall(r'<strong>(.*?)</strong>', tb, re.S)
        co = re.findall(r'[\d,]+', st[0]) if st else []
        out.append({"jo": rn[0][0], "races": [int(r) for _, r in rn], "co": num(co[0]) if co else 0})
    return out


def marks(base, key, track, model, day):
    q = (f"/rest/v1/nar_ai_marks?select=race_no,meta&model=eq.{model}&timing=eq.morning"
         f"&track=eq.{urllib.parse.quote(track)}&race_date=eq.{day}")
    rows = json.loads(http(base + q, {"apikey": key, "Authorization": "Bearer " + key}).decode("utf-8"))
    out = {}
    for r in rows:
        m = r.get("meta") or {}
        raw = m.get("p1_raw") or {}
        out[int(r["race_no"])] = sorted(((float(raw.get(str(x["num"]), x["p1"])), int(x["num"])) for x in m.get("runners", [])),
                                        reverse=True)
    return out


def pick_top(run, k):
    return [n for _, n in run[:k]]


def pick_budget(legs, cap):
    """legs = 5 R の [(p, 馬番), ...](p の大きい順)。⛔研究の src/w5_picks.py の pick_budget と同じ(410 日 1 点ずつ一致)。"""
    pr = []
    for run in legs:
        s = sum(p for p, _ in run) or 1.0
        pr.append([p / s for p, _ in run])
    k = [1] * len(legs)
    while True:
        n = 1
        for v in k:
            n *= v
        P = 1.0
        for i in range(len(legs)):
            P *= sum(pr[i][:k[i]])
        best, bi = -1.0, None
        for i in range(len(legs)):
            if k[i] >= len(pr[i]):
                continue
            n2 = n // k[i] * (k[i] + 1)
            if n2 > cap:
                continue
            v = (P / sum(pr[i][:k[i]]) * sum(pr[i][:k[i] + 1]) - P) / (n2 - n)
            if v > best:
                best, bi = v, i
        if bi is None:
            return [[num_ for _, num_ in legs[i][:k[i]]] for i in range(len(legs))], P
        k[bi] += 1


def build(day, base, key, html):
    """→ (本文, 買う組の数)。"""
    tabs = parse_loto(html)
    if not tabs:
        return None, 0
    lines, buy, total = [f"{day} の 5重勝の買い目(AI の朝の印・管理者だけ)", ""], 0, 0
    for t in tabs:
        track, model, th, rule = RULE.get(t["jo"], (t["jo"], None, 0, 0))
        head = f"■ {track.rstrip('ば')} {t['races'][0]}〜{t['races'][-1]}R 持ち越し {t['co']:,} 円"
        if model is None:
            lines += [head + " → 買わない(この場は外す)", ""]; continue
        if t["co"] < th:
            why = "持ち越しなし" if th <= 1 else f"持ち越し {th:,} 円未満"
            lines += [head + f" → 買わない({why})", ""]; continue
        mk = marks(base, key, track, model, day)
        miss = [r for r in t["races"] if r not in mk]
        if miss:
            lines += [head + f" → AI の朝の行が無い R {miss}(後で手で確かめる)", ""]; continue
        P = None
        if isinstance(rule, tuple):
            sets, P = pick_budget([mk[r] for r in t["races"]], rule[1])
        else:
            sets = [pick_top(mk[r], rule) for r in t["races"]]
        n = 1
        for s in sets:
            n *= len(s)
        buy += 1; total += n * 100
        lines.append(head + f" → 買う {n} 点 {n * 100:,} 円" + (f"(当たる見込み {P * 100:.1f}%)" if P else ""))
        for r, s in zip(t["races"], sets):
            lines.append(f"  {r}R: " + "・".join(map(str, s)))
        lines.append("")
    lines += [f"合計 {total:,} 円", "", "※ 自動で買うことはしない。締め切りは各場の 1 本目の発走前。"]
    return "\n".join(lines), buy


def send(subject, body):
    user, pw, to = (os.environ.get(k, "") for k in ("W5_MAIL_USER", "W5_MAIL_PASS", "W5_MAIL_TO"))
    if not (user and pw and to):
        print("W5_MAIL_USER / W5_MAIL_PASS / W5_MAIL_TO が無い= 送らない")
        return 2
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [a.strip() for a in to.split(",") if a.strip()], msg.as_string())
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD(既定 = 今日 JST)")
    ap.add_argument("--dry-run", action="store_true", help="本文を出すだけ(送らない)")
    a = ap.parse_args()
    day = a.date or dt.datetime.now(JST).date().isoformat()
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    try:
        html = http(LOTO_URL + day.replace("-", "")).decode("cp932", "ignore")
    except Exception as e:
        # ⛔読めない日も黙らない= 管理者に「読めなかった」を送る
        body, n = f"{day}: オッズパークの 5重勝の一覧が読めなかった({type(e).__name__}: {str(e)[:120]})。手で確かめる。", -1
    else:
        try:
            body, n = build(day, base, key, html)
        except Exception as e:
            body, n = f"{day}: AI の朝の印が読めなかった({type(e).__name__}: {str(e)[:120]})。手で確かめる。", -1
    if body is None:
        print(f"{day}: 競馬のセレクト5重勝なし = 送らない"); return 0
    print(body)
    if a.dry_run:
        print("dry-run: 送らない"); return 0
    subject = f"5重勝の買い目 {day}" + ("(読めず)" if n < 0 else f"({n} 場)")
    try:
        rc = send(subject, body)
    except Exception as e:
        print(f"送れなかった: {type(e).__name__}: {str(e)[:200]}"); return 1
    print("送った" if rc == 0 else "送らない")
    return 0 if rc in (0, 2) else 1


if __name__ == "__main__":
    sys.exit(main())
