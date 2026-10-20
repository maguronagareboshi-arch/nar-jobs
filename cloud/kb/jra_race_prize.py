# -*- coding: utf-8 -*-
"""中央のレースの本賞金(1〜5着・付加賞抜き)を競馬ブック スマホ版の成績頁から取り、表 nar_jra_race_prize へ(2026-10-17)。

対象= 佐賀・高知を走った馬(nar_runs・--days 日以内)の中央の走(nar_jra_runs)で 5着以内・まだ表に無いレース。
頁はログイン不要(s.keibabook.co.jp/cyuou/seiseki/<kb_race_id> の table.syokin)。1 本ごとに書くので途中で止まっても次は続きから。
  python cloud/kb/jra_race_prize.py --days 400 --max 60          # 既定= dry-run(取って数えるだけ)
  python cloud/kb/jra_race_prize.py --days 400 --max 60 --apply  # 表へ upsert
"""
import argparse, datetime as dt, html as H, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from class_calc import sb_all, upsert, http_get  # noqa: E402

T = "nar_jra_race_prize"
CIRC = "①②③④⑤"
URL = "https://s.keibabook.co.jp/cyuou/seiseki/"
JST = dt.timezone(dt.timedelta(hours=9))


def parse(html):
    """成績頁 → [1着..5着](円)。賞金の表が無ければ None。"""
    m = re.search(r'<table class="syokin">(.*?)</table>', html, re.S)
    if not m:
        return None
    t = H.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
    vals = []
    for c in CIRC:
        x = re.search(re.escape(c) + r"\s*([\d,]+(?:\.\d+)?)万", t)
        if not x:
            break
        vals.append(round(float(x.group(1).replace(",", "")) * 10000))
    return vals or None


JRA_PLACE = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
_KB_VENUE = {}   # JRA の場コード → 競馬ブックの場コード(0〜9)。1 度当たったら覚える(2026-10-20 京都=00・東京=04・中山=05 を確認)


def kd_candidates(k):
    """kd+yyyymmdd+場+回+日目+R → 競馬ブック頁の番号の候補(yyyy+回+場(0〜9)+日目+R)。"""
    m = re.fullmatch(r"kd(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", k)
    if not m:
        return []
    y, mo, d, pl, kai, nichi, rr = m.groups()
    known = _KB_VENUE.get(pl)
    vs = [known] if known is not None else range(10)
    return [(f"{y}{kai}{v:02d}{nichi}{rr}", v) for v in vs]


def kd_to_page(k, wait):
    """kd の番号 → (頁の番号, html)。頁の題(日付+場+R)が合うものだけ採る(合わなければ None)。"""
    m = re.fullmatch(r"kd(\d{4})(\d{2})(\d{2})(\d{2})\d{2}\d{2}(\d{2})", k)
    y, mo, d, pl, rr = m.groups()
    want = f"{int(y)}年{int(mo)}月{int(d)}日{JRA_PLACE.get(pl, '?')}{int(rr)}R"
    for pid, v in kd_candidates(k):
        try:
            req = urllib.request.Request(URL + pid, headers={"User-Agent": "Mozilla/5.0"})
            h = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(wait)
            continue
        time.sleep(wait)
        t = re.search(r"<title>(.*?)</title>", h, re.S)
        if t and want in t.group(1):
            _KB_VENUE[pl] = v
            return pid, h
    return None, None


def targets(url, key, days):
    q = urllib.parse.quote
    since = (dt.datetime.now(JST).date() - dt.timedelta(days=days)).isoformat()
    runs = []
    for trk in ("佐賀", "高知"):   # 2026-10-20 高知も本賞金に差し替えるので同じ表を使う
        runs += sb_all(url, key, f"nar_runs?select=horse_name,birth_date&track=eq.{q(trk)}&race_date=gte.{since}")
    want = {}
    for r in runs:
        want.setdefault(r["horse_name"], set()).add((r.get("birth_date") or "")[:10])
    names = sorted(want)
    hs = []
    for i in range(0, len(names), 80):
        inq = ",".join('"' + n + '"' for n in names[i:i + 80])
        hs += sb_all(url, key, f"nar_jra_horses?select=kb_horse_id,horse_name,birth_date&horse_name=in.({q(inq)})")
    ids = sorted({h["kb_horse_id"] for h in hs
                  if not h.get("birth_date") or "" in want[h["horse_name"]] or str(h["birth_date"])[:10] in want[h["horse_name"]]})
    races = set()
    for i in range(0, len(ids), 100):
        rs = sb_all(url, key, f"nar_jra_runs?select=kb_race_id&finish=lte.5&kb_horse_id=in.({','.join(ids[i:i + 100])})")
        # 数字 12 桁= 成績頁の番号。「kd+日付8+場2+回2+日目2+R2」(KDSCOPE の番号)は頁の番号に直して取る(kd_to_page)
        races |= {r["kb_race_id"] for r in rs if re.fullmatch(r"\d{12}|kd\d{16}", r.get("kb_race_id") or "")}
    have = set()
    rl = sorted(races)
    for i in range(0, len(rl), 150):
        have |= {r["kb_race_id"] for r in sb_all(url, key, f"{T}?select=kb_race_id&kb_race_id=in.({','.join(rl[i:i + 150])})")}
    return len(ids), sorted(races - have), len(have)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--wait", type=float, default=2.5)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
    nh, todo, nhave = targets(url, key, a.days)
    print(f"馬 {nh}・表に有る {nhave}・未取得 {len(todo)}・今回 {min(len(todo), a.max)}", flush=True)
    got = none = err = 0
    for k in todo[:a.max]:
        try:
            if k.startswith("kd"):
                pid, html = kd_to_page(k, a.wait)
                v = parse(html) if html else None   # 頁が見つからないときも honsho=null で残す(毎日やり直さない・差し替えは台帳の値のまま)
                if not html:
                    print("kd の頁が見つからない", k, flush=True)
            else:
                req = urllib.request.Request(URL + k, headers={"User-Agent": "Mozilla/5.0"})
                v = parse(urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore"))
        except Exception as e:
            err += 1
            print("取れない", k, str(e)[:80], flush=True)
            time.sleep(a.wait)
            continue
        got += 1
        none += v is None
        if a.apply:
            st, msg = upsert(url, key, T, "kb_race_id", [{"kb_race_id": k, "honsho": v, "fetched_at": dt.datetime.now(JST).isoformat()}])
            if st not in (200, 201):
                print("upsert 失敗", st, msg, flush=True)
                return 1
        time.sleep(a.wait)
    print(f"取った {got}(賞金の表なし {none})・取れない {err}・残り {max(0, len(todo) - a.max)}", flush=True)
    return 1 if err and not got else 0


if __name__ == "__main__":
    sys.exit(main())
