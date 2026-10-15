# -*- coding: utf-8 -*-
"""yukochi.com の当日の全レース画面を読むだけで見回る(手本= nar-site/research/race-sweep-20261013/sweep.mjs)。

  python cloud/race_sweep.py [--date YYYY-MM-DD] [--out DIR] [--wait 8]

当日の場と R はトップ・/calendar・各場の当日ページのリンクから拾う(DB の鍵は使わない)。
/race/<場>/<日付>/<R> と /venue/<場>/<日付> を 1280 と 375(端末幅= is_mobile)で開き、描画 8 秒後に測る:
  HTTP 状態・console エラー/例外・「取得中」「読み込み中」の残り・行 0 の表・横送り(scrollWidth>innerWidth)
  ・本文の NaN/undefined/null/[object・別 URL への転送。
⛔全面撮影はしない(375 の下の固定帯が途中に写る誤検知を避ける)。崩れた URL だけ 1 画面を撮る。
⛔発走前のオッズ「—」・結果が無いのは正常(測らない)。
出力: DIR/sweep.jsonl・DIR/summary.txt・DIR/shots/*.png
exit: 0= 崩れ 0(開催 0 も 0)・1= 崩れあり・2= 台本が回らなかった
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ORIGIN = "https://yukochi.com"
JST = dt.timezone(dt.timedelta(hours=9))

LINKS = """() => [...new Set([...document.querySelectorAll('a[href]')].map(a => {
  try { return new URL(a.getAttribute('href'), location.href).pathname; } catch { return ''; } }))]"""

MEASURE = r"""() => {
  const iw = innerWidth;
  const clipped = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) { const ox = getComputedStyle(p).overflowX; if (ox==='auto'||ox==='scroll'||ox==='hidden'||ox==='clip') return true; } return false; };
  const over = [...document.querySelectorAll('body *')].filter(e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.right > iw + 1 && getComputedStyle(e).position !== 'fixed' && !clipped(e); });
  const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const vis = e => e.checkVisibility ? e.checkVisibility() : true;
  const body = document.body ? document.body.innerText : '';
  const tables = [...document.querySelectorAll('table')].filter(vis);
  const emptyTables = tables.filter(t => ![...t.querySelectorAll('tr')].some(r => r.querySelector('td')));
  const loadingM = body.match(/.{0,15}(取得中|読み込み中|読込中|ロード中).{0,15}/g) || [];
  const badM = body.match(/.{0,20}(\bNaN\b|\bundefined\b|\bnull\b|\[object).{0,20}/g) || [];
  return { finalUrl: location.href, innerWidth: iw, scrollWidth: document.documentElement.scrollWidth,
    overflowSample: over.slice(0, 6).map(name),
    tables: tables.length, emptyTables: emptyTables.length, emptyTableSample: emptyTables.slice(0, 4).map(name),
    loading: loadingM.slice(0, 5), bad: badM.slice(0, 5), textLen: body.length };
}"""

UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
UA_SP = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"


def url_of(path):
    return ORIGIN + path + ("&" if "?" in path else "?") + "nocount=1"


def norm(p):
    return p.rstrip("/") or "/"


def symptoms(path, status, errs, v):
    s = []
    if status != 200:
        s.append(f"HTTP {status}")
    if errs:
        s.append("console エラー " + str(len(errs)) + " 件: " + " / ".join(errs[:3]))
    if v["loading"]:
        s.append("取得中のまま: " + " / ".join(v["loading"][:2]))
    if v["emptyTables"]:
        s.append(f"行 0 の表 {v['emptyTables']} 個: " + ",".join(v["emptyTableSample"]))
    if v["scrollWidth"] > v["innerWidth"]:
        s.append(f"横送り scrollWidth {v['scrollWidth']} > {v['innerWidth']}: " + ",".join(v["overflowSample"]))
    if v["bad"]:
        s.append("本文に NaN/undefined/null: " + " / ".join(v["bad"][:2]))
    fp = urlparse(v["finalUrl"]).path
    if norm(fp) != norm(path):
        s.append("転送 → " + v["finalUrl"])
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(JST).date().isoformat())
    ap.add_argument("--out", default="race-sweep-out")
    ap.add_argument("--wait", type=float, default=8.0)
    a = ap.parse_args()
    DATE = a.date
    os.makedirs(os.path.join(a.out, "shots"), exist_ok=True)
    jsonl = open(os.path.join(a.out, "sweep.jsonl"), "w", encoding="utf-8")
    t_start = time.time()
    venue_re = re.compile(rf"^/venue/([^/]+)/{DATE}/?$")
    race_re = re.compile(rf"^/race/([^/]+)/{DATE}/(\d+)/?$")
    targets = {}

    def add(paths):
        for p in paths:
            m = race_re.match(p)
            if m:
                targets[f"race_{m.group(1)}_{int(m.group(2)):02d}"] = f"/race/{m.group(1)}/{DATE}/{int(m.group(2))}"
                continue
            m = venue_re.match(p)
            if m:
                targets[f"venue_{m.group(1)}"] = f"/venue/{m.group(1)}/{DATE}"

    broken = []  # (url, width, [症状])
    n_measured = n_fail = n_retry_ok = 0
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        try:
            ctxs = {
                1280: br.new_context(viewport={"width": 1280, "height": 1080}, user_agent=UA_PC, color_scheme="light"),
                375: br.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True,
                                    device_scale_factor=2, user_agent=UA_SP, color_scheme="light"),
            }
            # 1) 当日の場と R を拾う(同時 1 タブ・間隔 1 秒以上)
            pg = ctxs[1280].new_page()
            for p in ["/", "/calendar"]:
                r = pg.goto(url_of(p), wait_until="load", timeout=60000)
                if r is None or r.status != 200:
                    raise RuntimeError(f"{p} が開けない(HTTP {r.status if r else None})")
                pg.wait_for_timeout(3000)
                add(pg.evaluate(LINKS))
                time.sleep(1.2)
            for vid, p in sorted(t for t in targets.items() if t[0].startswith("venue_")):
                pg.goto(url_of(p), wait_until="load", timeout=60000)
                pg.wait_for_timeout(3000)
                add(pg.evaluate(LINKS))
                time.sleep(1.2)
            pg.close()
            for k in list(targets):
                m = re.match(r"^race_(.+)_\d+$", k)
                if m and f"venue_{m.group(1)}" not in targets:
                    targets[f"venue_{m.group(1)}"] = f"/venue/{m.group(1)}/{DATE}"
            lst = sorted(targets.items())
            n_race = sum(1 for k, _ in lst if k.startswith("race_"))
            n_venue = len(lst) - n_race
            print(f"{DATE}: 場 {n_venue}・レース {n_race}・URL {len(lst)}", flush=True)
            if n_race == 0:
                with open(os.path.join(a.out, "summary.txt"), "w", encoding="utf-8") as f:
                    f.write(f"{DATE}: 開催 0(レース画面が無い)= 見回らない\n")
                print("開催 0 = 見回らない")
                return 0

            # 2) 測る(崩れた画面は 60 秒あけて 1 回だけ測り直し、まだ崩れていれば数える。
            #    10/15: 本番を出している途中に当たり、古い HTML と新しい CSS の食い違いで 41 件の空振りが出た)
            def measure(w, tid, path, tag=""):
                nonlocal n_measured, n_fail
                url = url_of(path)
                errs = []
                page = ctxs[w].new_page()
                page.on("console", lambda m, e=errs: e.append("console: " + m.text[:200]) if m.type in ("error", "assert") else None)
                page.on("pageerror", lambda x, e=errs: e.append("exception: " + str(x)[:200]))
                t0 = time.time()
                sy = None
                try:
                    r = page.goto(url, wait_until="load", timeout=60000)
                    status = r.status if r else None
                    page.wait_for_timeout(a.wait * 1000)
                    v = page.evaluate(MEASURE)
                    errs_u = list(dict.fromkeys(errs))[:8]
                    sy = symptoms(path, status, errs_u, v)
                    rec = {"id": tid, "url": url, "width": w, "status": status, "errors": errs_u,
                           "symptoms": sy, "ms": int((time.time() - t0) * 1000), "retry": bool(tag), **v}
                    n_measured += 1
                    if sy and tag:
                        png = f"{tid}_{w}.png"
                        try:
                            page.screenshot(path=os.path.join(a.out, "shots", png), full_page=False)
                            rec["png"] = png
                        except Exception as e:
                            rec["png_error"] = str(e)[:200]
                    print(w, tid, tag, status, "NG " + " | ".join(sy) if sy else "ok", flush=True)
                except Exception as e:
                    n_fail += 1
                    rec = {"id": tid, "url": url, "width": w, "error": str(e)[:300], "retry": bool(tag)}
                    sy = ["測定できない: " + str(e)[:200]]
                    print(w, tid, tag, "FAIL", str(e)[:200], flush=True)
                finally:
                    page.close()
                jsonl.write(json.dumps(rec, ensure_ascii=False) + "\n")
                jsonl.flush()
                time.sleep(1.0)
                return url, sy

            suspects = []
            for w in (1280, 375):
                for tid, path in lst:
                    _, sy = measure(w, tid, path)
                    if sy:
                        suspects.append((w, tid, path))
            if suspects:
                print(f"崩れの候補 {len(suspects)} 件= 60 秒あけて測り直す", flush=True)
                time.sleep(60)
                for w, tid, path in suspects:
                    url, sy = measure(w, tid, path, tag="再")
                    if sy:
                        broken.append((url, w, sy))
                n_retry_ok = len(suspects) - len(broken)
        finally:
            br.close()

    mins = (time.time() - t_start) / 60
    lines = [f"{DATE}: 場 {n_venue}・レース {n_race}・URL {len(lst)}・測定 {n_measured}・失敗 {n_fail}・崩れ {len(broken)}(測り直しで直った {n_retry_ok})・{mins:.1f} 分"]
    for url, w, sy in broken:
        lines.append(f"  [{w}] {url} — " + " ; ".join(sy))
    txt = "\n".join(lines) + "\n"
    with open(os.path.join(a.out, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    return 1 if broken else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("race_sweep が回らなかった:", e)
        try:
            os.makedirs("race-sweep-out", exist_ok=True)
        except Exception:
            pass
        sys.exit(2)
