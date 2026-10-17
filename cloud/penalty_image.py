#!/usr/bin/env python3
"""制裁 1 件ごとの X 用の画像(1200x630 PNG・見本 mock/penalties/v4_detail.html の .og・2026-10-17 了承)。

  --start / --end YYYY-MM-DD   開催日の範囲(既定= JST 今日を含む直近 3 日)
  --rows-json FILE             nar_penalties の行(JSON 配列)を DB の代わりに読む(手元の試し用)
  --out DIR                    手元に DIR/penalty/<penalty_id 先頭12字>.png で書く
  --upload                     公開バケット share の penalty/<penalty_id 先頭12字>.png へ upsert
                               (今ある中身と sha256 が同じなら上げ直さない)

画面側は og:image にこの URL を使い、無ければサイト共通の og.png に戻る。
字・REST・上げ方は cloud/share_image.py を使い回す(⛔写して増やさない)。
長い期間は月ごとに引いて、月ごとに件数をログに出す(過去分は penalties-backfill の手押しで作る)。
書く文字は行と公式の文(detail)にあるものだけ。⛔日数・名前・馬を推測しない。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import unicodedata

from PIL import Image, ImageDraw

import share_image as si

W, H = 1200, 630
BG, FG, SUB, FOOT = "#F6F2E8", "#262119", "#5A5344", "#6E6554"
BAR_BG, BAR_FG, BAR_URL = "#10151E", "#EDEFF4", "#FFB627"
BAR_H = 82
X0 = 48                                   # 左右の余白(見本の 4%)
KIND_COL = {"騎乗停止": ("#F2D9D5", "#B0342B"), "出走停止": ("#DBE2F0", FG), "過怠金": ("#EEE2C4", FG)}
KIND_OTHER = ("#EFEADC", FG)
ROLE = {"jockey": "騎手", "trainer": "調教師", "horse": "馬"}
# 日数を札に付けるのは「止められる期間」そのものの種類だけ(戒告の日数は賞典停止の日数なので付けない)
DAYS_KINDS = ("騎乗停止", "出走停止")
WEEK = "月火水木金土日"
COLS = ("penalty_id,track,race_date,race_no,person_kind,person_name,horse_name,kind,cause,prize_suspended,"
        "suspension_from,suspension_through,suspension_days,detail")
_NG = r"\s、。,()（）「」『』【】:：・号番は"


def show_track(track):
    return si.SHOW_NAME.get(track, track or "")


def full_name(row):
    """detail の頭の正式名(「騎手◯◯は」「◯◯騎手は」「調教師◯◯は」「◯◯調教師は」)。取れなければ person_name。
    馬は horse_name。取れた名前の 1 字目が person_name と違うときは使わない。"""
    pk = row.get("person_kind")
    if pk == "horse":
        return row.get("horse_name") or row.get("person_name") or ""
    pn = row.get("person_name") or ""
    role = ROLE.get(pk)
    det = unicodedata.normalize("NFKC", row.get("detail") or "")
    if role in ("騎手", "調教師"):
        for pat in (role + r"([^%s]{2,10}?)は" % _NG, r"([^%s]{2,10})%sは" % (_NG, role)):
            m = re.search(pat, det)
            if m and (not pn or m.group(1)[0] == pn[0]):
                return m.group(1)
    return pn


def days_count(row):
    """日数が書いてあるときだけ数を返す(suspension_days の数 → detail の「実効N日間」→「N日間」)。"""
    sd = row.get("suspension_days")
    if sd:
        return len(sd)
    det = unicodedata.normalize("NFKC", row.get("detail") or "")
    m = re.search(r"実効(\d+)日間", det) or re.search(r"(\d+)日間", det)
    return int(m.group(1)) if m else None


def kind_label(row):
    k = row.get("kind") or ""
    if k in DAYS_KINDS:
        n = days_count(row)
        if n:
            return "%s %d日間" % (k, n)
    return k


def md(s):
    d = dt.date.fromisoformat(str(s)[:10])
    return "%d/%d" % (d.month, d.day)


def period_text(row):
    """期間の行。suspension_days → 日を並べる・from〜through・through だけ= 「M/D まで◯◯できない」。"""
    head = "賞典停止" if row.get("prize_suspended") else "停止"
    sd = row.get("suspension_days")
    fr, th = row.get("suspension_from"), row.get("suspension_through")
    if sd:
        return "%s %s" % (head, "・".join(md(x) for x in sd))
    if fr and th:
        return "%s %s〜%s" % (head, md(fr), md(th))
    if th:
        if row.get("prize_suspended"):
            return "賞典停止 %s まで" % md(th)
        if row.get("person_kind") == "horse":
            return "%s まで出走できない" % md(th)
        return "停止 %s まで" % md(th)
    return None


def when_text(row):
    d = dt.date.fromisoformat(str(row["race_date"])[:10])
    s = "%d年%d月%d日(%s) %s" % (d.year, d.month, d.day, WEEK[d.weekday()], show_track(row.get("track")))
    if row.get("race_no"):
        s += " %dR" % row["race_no"]
    if row.get("horse_name") and row.get("person_kind") != "horse":
        s += "・" + row["horse_name"]
    return s


def lines(row):
    """描く文字(試験で見る)。"""
    return {"kind": kind_label(row), "role": ROLE.get(row.get("person_kind"), ""), "name": full_name(row),
            "when": when_text(row), "period": period_text(row),
            "cause": ("理由 " + row["cause"]) if row.get("cause") else None}


def _text(d, x, cy, s, f, fill, anchor="ls"):
    d.text((x, si.baseline(f, cy)), s, font=f, fill=fill, anchor=anchor)


def render(row):
    t = lines(row)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    maxw = W - X0 * 2
    # 上の帯
    d.rectangle([0, 0, W - 1, BAR_H - 1], fill=BAR_BG)
    f32, f27 = si.font(32), si.font(27)
    _text(d, X0, BAR_H / 2, "地方競馬ウォッチ　制裁", f32, BAR_FG)
    _text(d, W - X0, BAR_H / 2, "yukochi.com", f27, BAR_URL, "rs")
    # 種類の札
    bg, fg = KIND_COL.get(row.get("kind") or "", KIND_OTHER)
    ks, kf = si.fit_text(d, t["kind"], 56, maxw - 58, 30)
    kw = d.textlength(ks, font=kf)
    ky0, kh = 126, 80
    d.rectangle([X0, ky0, X0 + kw + 58, ky0 + kh], fill=bg)
    _text(d, X0 + 29, ky0 + kh / 2, ks, kf, fg)
    # 役+名前
    cy = 227 + 56
    x = X0
    if t["role"]:
        fr = si.font(40)
        _text(d, x, cy + 14, t["role"], fr, SUB)
        x += d.textlength(t["role"], font=fr) + 24
    ns, nf = si.fit_text(d, t["name"], 88, W - X0 - x, 40)
    _text(d, x, cy, ns, nf, FG)
    # いつ・どこ
    ws, wf = si.fit_text(d, t["when"], 42, maxw, 24)
    _text(d, X0, 365 + 28, ws, wf, SUB)
    # 期間・理由
    y = 454 + 28
    for s in (t["period"], t["cause"]):
        if not s:
            continue
        ps, pf = si.fit_text(d, s, 44, maxw, 24)
        _text(d, X0, y, ps, pf, FG)
        y += 64
    _text(d, W - X0, H - 32, "主催者の成績表より", si.font(24), FOOT, "rs")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def rel_path(row):
    return "penalty/%s.png" % row["penalty_id"][:12]


# ---------- データ ----------
def months(start, end):
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end)
    while a <= b:
        nxt = (a.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        yield a.isoformat(), min(b, nxt - dt.timedelta(days=1)).isoformat()
        a = nxt


def load_rows(rest, start, end):
    out, off, step = [], 0, 1000
    while True:
        part = rest.rows("nar_penalties", select=COLS, race_date="gte." + start, **{
            "and": "(race_date.lte.%s)" % end, "order": "race_date.asc,penalty_id.asc",
            "limit": step, "offset": off})
        out += part
        if len(part) < step:
            return out
        off += step


def run(rows, rest, out_dir, do_upload, label):
    made = up = same = fail = 0
    for row in rows:
        try:
            png = render(row)
            made += 1
            if out_dir:
                name = rel_path(row) if row.get("penalty_id") else "penalty/row%d.png" % made
                p = os.path.join(out_dir, *name.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(png)
            if do_upload:
                if si.upload(rest, rel_path(row), png):
                    up += 1
                else:
                    same += 1
        except Exception as e:  # 1 件の失敗で残りを止めない(件数に出す)
            fail += 1
            si.log("⚠ %s %s %sR %s: %s" % (row.get("race_date"), row.get("track"), row.get("race_no"),
                                           row.get("person_name"), e))
    si.log("penalty_image %s: 作成 %d・上げた %d・同じで省略 %d・失敗 %d" % (label, made, up, same, fail))
    return fail


def main():
    today = dt.datetime.now(si.JST).date()
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=(today - dt.timedelta(days=2)).isoformat())
    ap.add_argument("--end", default=today.isoformat())
    ap.add_argument("--rows-json")
    ap.add_argument("--out")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    if not a.out and not a.upload:
        ap.error("--out か --upload のどちらかが要る")
    if a.rows_json:
        if a.upload:
            ap.error("--rows-json の行は上げない(手元の試し用)")
        with open(a.rows_json, encoding="utf-8") as f:
            return 1 if run(json.load(f), None, a.out, False, a.rows_json) else 0
    rest = si.Rest()
    fail = 0
    for s, e in months(a.start, a.end):
        fail += run(load_rows(rest, s, e), rest, a.out, a.upload, "%s〜%s" % (s, e))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
