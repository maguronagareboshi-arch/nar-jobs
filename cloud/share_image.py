#!/usr/bin/env python3
"""レース結果の共有画像(払戻板ふう A 案・2026-09-25 了承)を 1200x630 PNG で焼く。

  --date YYYY-MM-DD   既定 JST 今日
  --race N            1 レースだけ(既定= その日の全レース)
  --venue PREFIX      1 場だけ(kochi 等・サイトの /race/<venue>/ と同じ表記)
  --out DIR           手元に DIR/race/<venue>/<date>/<R>.png で書く
  --upload            公開バケット share の race/<venue>/<date>/<R>.png へ upsert
                      (今ある中身と sha256 が同じなら上げ直さない)

作るのは「払戻が全部そろった」レースだけ= nar_race_payouts に 単勝・複勝・三連単(または三連複)があり、
nar_runs に 1 着がある。発走前・途中・取消は作らない。売っていない券種の帯は「発売なし」。
字= BIZ UDゴシック Bold(OFL・fonts/OFL-BIZUDGothic.txt)。本体 4.6MB は repo に入れず、
fonts/ に無ければ google/fonts から取って sha256 を照合する(fonts/*.ttf は .gitignore)。
読むのは REST だけ。環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(無ければ SUPABASE_ANON_KEY で読むだけ)。
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(os.path.dirname(HERE), "fonts")
FONT_FILE = os.path.join(FONT_DIR, "BIZUDGothic-Bold.ttf")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/bizudgothic/BIZUDGothic-Bold.ttf"
FONT_SHA256 = "98a528b6b638463041968783cc0f63adaf4cdc26f5398afed68bab712d1113f3"
BUCKET = "share"
UA = "nar-jobs share_image (+https://nar.yukochi.com/)"
JST = dt.timezone(dt.timedelta(hours=9))

# サイトの URL 表記(viewer functions/_venues.js の TRACK_PREFIX と同じ)
TRACK_PREFIX = {
    "帯広": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa", "浦和": "urawa",
    "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa", "笠松": "kasamatsu",
    "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
}
TRACK_ALIAS = {"帯広ば": "obihiro"}
PREFIX_TRACK = {v: k for k, v in TRACK_PREFIX.items()}
PREFIX_TRACK["obihiro"] = "帯広ば"          # nar_races の表記
SHOW_NAME = {"帯広ば": "帯広"}

# 券種(DB の t)→ 表示名・帯の色(地・字)。放送の払戻板の並び
KIND = [("win", "単勝"), ("place", "複勝"), ("wakuren", "枠複"), ("wakutan", "枠単"), ("quinella", "馬複"),
        ("exacta", "馬単"), ("wide", "ワイド"), ("trio", "三連複"), ("trifecta", "三連単")]
COL = {"単勝": ("#1020e0", "#ffffff"), "複勝": ("#efefea", "#111111"), "枠複": ("#169a2a", "#ffffff"),
       "枠単": ("#f0a2e8", "#111111"), "馬複": ("#0b0b8c", "#ffffff"), "馬単": ("#ecdc00", "#111111"),
       "ワイド": ("#10bcd6", "#111111"), "三連複": ("#a3390b", "#ffffff"), "三連単": ("#f26a00", "#111111")}
# 枠の色(1 白・2 黒・3 赤・4 青・5 黄・6 緑・7 橙・8 桃)
GATE = {1: ("#ffffff", "#111111"), 2: ("#000000", "#ffffff"), 3: ("#d7263d", "#ffffff"), 4: ("#1f5fd6", "#ffffff"),
        5: ("#f5d000", "#111111"), 6: ("#169a2a", "#ffffff"), 7: ("#f28a00", "#111111"), 8: ("#f28cb1", "#111111")}
NBSP = " "

# 配置(モック A を 1200x630 に)。左列 x0..597・右列 603..1200・帯の内側の余白 22・券種名の幅 150・組番の前 20
W, H = 1200, 630
HEAD_H, HEAD_GAP = 74, 4
COLS = ((0, 597), (603, 1200))
PAD, LABEL_W, COMBO_GAP, FS, BAND_GAP = 22, 150, 20, 44, 3
LEFT = [("単勝", 76), ("複勝", 156), ("枠複", 76), ("枠単", 76), ("馬複", 76), ("馬単", 76)]
RIGHT = [("ワイド", 156), ("三連複", 78), ("三連単", 110)]
SLOTS = {"複勝": 3, "ワイド": 3}         # 高さに入れる行の数(これより多い同着は字を縮める)
PANEL_H = 203


def log(msg):
    print(msg, flush=True)


# ---------- 字 ----------
def ensure_font():
    if not os.path.exists(FONT_FILE):
        os.makedirs(FONT_DIR, exist_ok=True)
        r = urllib.request.Request(FONT_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(r, timeout=120) as x:
            data = x.read()
        if hashlib.sha256(data).hexdigest() != FONT_SHA256:
            raise RuntimeError("フォントの sha256 が違う")
        with open(FONT_FILE, "wb") as f:
            f.write(data)
    return FONT_FILE


_FONTS = {}


def font(size):
    k = round(size * 4) / 4
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype(ensure_font(), k)
    return _FONTS[k]


def baseline(f, cy):
    """CSS の行箱(ascent+descent)を cy に中央寄せしたときのベースライン。"""
    a, d = f.getmetrics()
    return cy - (a + d) / 2 + a


def mix(fg, bg, a):
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return tuple(round(f[i] * a + b[i] * (1 - a)) for i in range(3))


# ---------- データ ----------
class Rest:
    def __init__(self):
        self.base = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]

    def req(self, path, method="GET", body=None, headers=None, ok404=False):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA}
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, method=method, data=body, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=120) as x:
                return x.status, x.read()
        except urllib.error.HTTPError as e:
            if ok404 and e.code in (400, 404):
                return e.code, b""
            raise

    def rows(self, table, **q):
        qs = "&".join("%s=%s" % (k, urllib.parse.quote(str(v), safe=".,()*:")) for k, v in q.items())
        return json.loads(self.req("/rest/v1/%s?%s" % (table, qs))[1] or b"[]")


def load_day(rest, date, venue=None, race=None):
    f = {"race_date": "eq." + date}
    if venue:
        f["track"] = "eq." + PREFIX_TRACK[venue]
    if race:
        f["race_no"] = "eq.%d" % race
    races = rest.rows("nar_races", select="track,race_date,race_no,race_name,surface,distance_m,going,cancelled",
                      order="track.asc,race_no.asc", **f)
    pays = rest.rows("nar_race_payouts", select="track,race_no,payouts", order="track.asc,race_no.asc", **f)
    runs = rest.rows("nar_runs", select="track,race_no,runner_number,gate,horse_name,finish,popularity",
                     finish="lte.3", order="track.asc,race_no.asc,finish.asc,runner_number.asc", **f)
    pay = {(p["track"], p["race_no"]): p["payouts"] or [] for p in pays}
    top = {}
    for r in runs:
        if r.get("finish"):
            top.setdefault((r["track"], r["race_no"]), []).append(r)
    out = []
    for rc in races:
        k = (rc["track"], rc["race_no"])
        if rc["track"] not in PREFIX_TRACK.values() and rc["track"] not in TRACK_PREFIX:
            continue
        rc["payouts"], rc["top"] = pay.get(k, []), top.get(k, [])
        out.append(rc)
    return out


def complete(rc):
    ts = {p.get("t") for p in rc["payouts"]}
    return (not rc.get("cancelled") and "win" in ts and "place" in ts and ("trifecta" in ts or "trio" in ts)
            and any(r.get("finish") == 1 for r in rc["top"]))


def fmt_combo(t, c):
    c = str(c)
    if t in ("win", "place"):
        return c + "番"
    parts = c.split("-")
    return "-".join([parts[0]] + [p.rjust(2, NBSP) for p in parts[1:]])


def pay_rows(rc):
    rank = {}
    for r in rc["top"]:
        rank.setdefault(str(r["runner_number"]), r["finish"])
    by = {}
    for p in rc["payouts"]:
        by.setdefault(p.get("t"), []).append(p)
    out = {}
    for t, name in KIND:
        rs = by.get(t, [])
        if t in ("place", "wide"):
            rs.sort(key=lambda p: sorted(rank.get(x, 9) for x in str(p["c"]).split("-")))
        else:
            rs.sort(key=lambda p: [int(x) if x.isdigit() else 99 for x in str(p["c"]).split("-")])
        out[name] = [(fmt_combo(t, p["c"]), int(p["y"])) for p in rs if p.get("y") is not None]
    return out


# ---------- 描画 ----------
def fit_text(d, text, size, maxw, minsize):
    s = size
    while s > minsize and d.textlength(text, font=font(s)) > maxw:
        s -= 1
    f = font(s)
    if d.textlength(text, font=f) > maxw:
        while text and d.textlength(text + "…", font=f) > maxw:
            text = text[:-1]
        text += "…"
    return text, f


def draw_band(d, name, x0, x1, y0, h, rows, layout):
    bg, fg = COL[name]
    d.rectangle([x0, y0, x1 - 1, y0 + h - BAND_GAP - 1], fill=bg)
    ch = h - BAND_GAP                                     # 色の部分の高さ
    lf = font(FS)
    d.text((x0 + PAD, baseline(lf, y0 + ch / 2)), name, font=lf, fill=fg, anchor="ls")
    cx = x0 + PAD + LABEL_W + COMBO_GAP
    rx = x1 - PAD
    band = {"name": name, "x0": x0, "x1": x1, "combo_x": cx, "right_x": rx, "bg": bg, "rows": []}
    if not rows:
        f = font(FS * 0.8)
        mid = (x0 + PAD + LABEL_W + rx) / 2
        d.text((mid, baseline(f, y0 + ch / 2)), "発売なし", font=f, fill=fg, anchor="ms")
        band["none"] = True
        layout.append(band)
        return
    slots = SLOTS.get(name, 1)
    rh = ch / max(len(rows), slots)
    fs = FS if len(rows) <= slots else max(22, min(FS, rh * 0.84))   # 同着で行が増えたときだけ縮める
    f, fy = font(fs), font(fs * 0.85)
    top = y0 + (ch - rh * len(rows)) / 2
    for i, (combo, yen) in enumerate(rows):
        cy = top + rh * (i + 0.5)
        by = baseline(f, cy)
        d.text((cx, by), combo, font=f, fill=fg, anchor="ls")
        d.text((rx, by), "円", font=fy, fill=fg, anchor="rs")
        d.text((rx - d.textlength("円", font=fy), by), "{:,}".format(yen), font=f, fill=fg, anchor="rs")
        band["rows"].append({"combo": combo, "yen": yen, "y0": round(top + rh * i), "y1": round(top + rh * (i + 1)),
                             "fs": fs, "first": combo[0]})
    layout.append(band)


def chip(d, x, y, s, gate, num):
    bg, fg = GATE.get(gate or 0, ("#777777", "#ffffff"))
    d.rounded_rectangle([x, y, x + s - 1, y + s - 1], radius=6, fill=bg,
                        outline="#888888" if gate in (1, 2) else None, width=2 if gate in (1, 2) else 0)
    f = font(s * 0.6)
    d.text((x + s / 2, baseline(f, y + s / 2)), str(num), font=f, fill=fg, anchor="ms")


def render(rc):
    """1 レースの PNG(bytes)と、検品用の配置を返す。"""
    img = Image.new("RGB", (W, H), "#000000")
    d = ImageDraw.Draw(img)
    track = SHOW_NAME.get(rc["track"], rc["track"])
    # 頭
    d.rectangle([0, 0, W - 1, HEAD_H - 1], fill="#0b1f6e")
    f44, f34, f22 = font(44), font(34), font(22)
    x = PAD
    t1 = "%s %dR" % (track, rc["race_no"])
    d.text((x, baseline(f44, HEAD_H / 2)), t1, font=f44, fill="#ffffff", anchor="ls")
    x += d.textlength(t1, font=f44) + 24
    red_txt = "払戻金"
    sp = 34 * 0.3
    red_w = 26 * 2 + sum(d.textlength(c, font=f34) + sp for c in red_txt)
    red_x = W - PAD - red_w
    rd = dt.date.fromisoformat(rc["race_date"])
    surf = {"ダート": "ダ", "芝": "芝"}.get(rc.get("surface") or "", rc.get("surface") or "")
    cond = "・".join(s for s in ("%d月%d日" % (rd.month, rd.day),
                                  ("%s%sm" % (surf, rc["distance_m"])) if rc.get("distance_m") else "",
                                  rc.get("going") or "") if s)
    cw = d.textlength(cond, font=f22)
    name = unicodedata.normalize("NFKC", rc.get("race_name") or "").strip()
    name, fn = fit_text(d, name, 34, red_x - 24 - cw - 24 - x, 22)
    d.text((x, baseline(fn, HEAD_H / 2)), name, font=fn, fill="#ffffff", anchor="ls")
    x += d.textlength(name, font=fn) + 24
    d.text((x, baseline(f22, HEAD_H / 2)), cond, font=f22, fill=mix("#ffffff", "#0b1f6e", 0.85), anchor="ls")
    d.rectangle([red_x, 11, W - PAD - 1, HEAD_H - 12], fill="#d40000")
    rx = red_x + 26
    for c in red_txt:
        d.text((rx, baseline(f34, HEAD_H / 2)), c, font=f34, fill="#ffffff", anchor="ls")
        rx += d.textlength(c, font=f34) + sp
    # 帯
    rows = pay_rows(rc)
    layout = []
    y = HEAD_H + HEAD_GAP
    for name_, h in LEFT:
        draw_band(d, name_, COLS[0][0], COLS[0][1], y, h, rows[name_], layout)
        y += h
    y = HEAD_H + HEAD_GAP
    for name_, h in RIGHT:
        draw_band(d, name_, COLS[1][0], COLS[1][1], y, h, rows[name_], layout)
        y += h
    # 1〜3 着
    px0, px1 = COLS[1]
    d.rectangle([px0, y, px1 - 1, min(H, y + PANEL_H) - 1], fill="#111111")
    f26, f30, f20, f17 = font(26), font(30), font(20), font(17)
    ry = y + 6
    for r in rc["top"][:3]:
        cy = ry + 29
        xx = px0 + 20
        d.text((xx, baseline(f26, cy)), "%d着" % r["finish"], font=f26, fill="#ffffff", anchor="ls")
        xx += 52 + 12
        chip(d, xx, cy - 22, 44, r.get("gate"), r["runner_number"])
        xx += 44 + 12
        pop = ("%d番人気" % r["popularity"]) if r.get("popularity") else ""
        pw = d.textlength(pop, font=f20)
        hn, fh = fit_text(d, r.get("horse_name") or "", 30, px1 - 20 - pw - 12 - xx, 20)
        d.text((xx, baseline(fh, cy)), hn, font=fh, fill="#ffffff", anchor="ls")
        if pop:
            d.text((px1 - 20, baseline(f20, cy)), pop, font=f20, fill=mix("#ffffff", "#111111", 0.8), anchor="rs")
        ry += 58
    d.text((px1 - 20, y + 6 + 174 + 12), "地方競馬ウォッチ nar.yukochi.com", font=f17,
           fill=mix("#ffffff", "#111111", 0.6), anchor="rs")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue(), layout


def venue_of(track):
    return TRACK_ALIAS.get(track) or TRACK_PREFIX[track]


def rel_path(rc):
    return "race/%s/%s/%d.png" % (venue_of(rc["track"]), rc["race_date"], rc["race_no"])


def upload(rest, path, data):
    st, old = rest.req("/storage/v1/object/public/%s/%s" % (BUCKET, path), ok404=True)
    if st == 200 and hashlib.sha256(old).hexdigest() == hashlib.sha256(data).hexdigest():
        return False
    rest.req("/storage/v1/object/%s/%s" % (BUCKET, path), "POST", data,
             {"Content-Type": "image/png", "x-upsert": "true", "Cache-Control": "max-age=300"})
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(JST).date().isoformat())
    ap.add_argument("--race", type=int)
    ap.add_argument("--venue", choices=sorted(PREFIX_TRACK))
    ap.add_argument("--out")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    if not a.out and not a.upload:
        ap.error("--out か --upload のどちらかが要る")
    rest = Rest()
    made = skip = up = same = fail = 0
    for rc in load_day(rest, a.date, a.venue, a.race):
        if not complete(rc):
            skip += 1
            continue
        try:
            png, _ = render(rc)
            path = rel_path(rc)
            made += 1
            if a.out:
                p = os.path.join(a.out, *path.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(png)
            if a.upload:
                if upload(rest, path, png):
                    up += 1
                else:
                    same += 1
        except Exception as e:  # 1 レースの失敗で残りを止めない(件数に出す)
            fail += 1
            log("⚠ %s %sR: %s" % (rc.get("track", "?"), rc.get("race_no", "?"), e))
    log("share_image %s: 作成 %d・上げた %d・同じで省略 %d・未確定で省略 %d・失敗 %d"
        % (a.date, made, up, same, skip, fail))
    return 1 if fail else 0

if __name__ == "__main__":
    sys.exit(main())
