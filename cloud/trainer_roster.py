# -*- coding: utf-8 -*-
"""§移籍まとめ D2(2026-09-30): 公式 keiba.go.jp の「現役管理馬一覧」を調教師ごとに毎日取る。

  一覧 DataRoom/TrainerList?k_pageNum=N&k_nameCondition=include&k_genneki_flag=1&k_shozoku=*&k_sei=
       50 人/頁・行に k_trainerLicenseNo・氏名・登録・所属(persons.py と同じ頁。⛔k_flag は付けない)
  個票 DataRoom/TrainerMark?k_trainerLicenseNo=N(1 頁 50 頭・「次の50頭→」の href を辿る)
       頭に 氏名(字間の空白つき)・所属。表「現役管理馬一覧」= 馬名(RaceHorseInfo?k_lineageLoginCode=…)・性齢・生年・父名・母名
  ⛔JRA 所属の人は取らない(地方だけ・約 459 人)。⛔頁に charset が無いが中身は UTF-8。

書き先(--apply のときだけ。表の形は sql/trainer_roster.sql・適用は本体が手動モードで):
  nar_trainers(license_no, trainer_name, area, short_guess, short_name, updated_at)
  nar_trainer_roster(lineage_code 主キー, license_no, trainer_name, area, horse_name, sex_age, birth_year, sire, dam, fetched_on)
  → 行は 2 夜続けて一覧に居なかったときだけ消す(1 夜目は missing_since に日付を入れて残す)
  → rpc nar_trainers_match_short()= nar_runs の略称と突き合わせ(決まらない人は null のまま)
  D3(9/30): 書き換える前に前夜の nar_trainer_roster を読み、差分を nar_roster_moves に追記
    (別の免許番号に載った/新しく載った= from が null/消えた= to が null)。
    前夜の表が空(初回)は差分を出さない(基準づくりだけ)。主キー (lineage_code, seen_on)+重複は無視= 冪等。
    ① 取れなかった人(失敗・0 頭・頁送りが途中で止まった)は前夜の行をそのまま持ち越し、その人がからむ差分は出さない
       (その人の頁から来た馬・その人へ行った馬とも)。人数は heartbeat の note「取れず n」。
    ② 新しく載った馬は、nar_roster_moves の直近 14 日に別の免許番号の記録があれば from をそれで埋める。
    ③ 消えたは 2 夜続けて載らなかったときだけ(1 夜目は missing_since を入れて行を残す・載り直せば null に戻る)。
  → heartbeat 'trainer_roster'

  py -3.12 -X utf8 cloud/trainer_roster.py --licenses 11088,11309 --out roster.csv   # 試し(書かない)
  py -3.12 -X utf8 cloud/trainer_roster.py --probe                                   # 走者から取れるか(1 人だけ)
  python cloud/trainer_roster.py --apply --out "$RUNNER_TEMP/roster.csv"             # 便(trainer-roster.yml)
環境変数(--apply): SUPABASE_URL / SUPABASE_SERVICE_KEY
終了コード: 0 正常 / 1 失敗 / 2 取れない(probe)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html as htmlmod
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
BASE = "https://www.keiba.go.jp"
LIST_URL = (BASE + "/KeibaWeb/DataRoom/TrainerList?k_pageNum={page}&k_nameCondition=include"
            "&k_genneki_flag=1&k_shozoku=*&k_sei=")
MARK_URL = BASE + "/KeibaWeb/DataRoom/TrainerMark?k_trainerLicenseNo={no}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
WAIT = 2.0                 # 頁の間隔(秒)。約 460 人+次頁で 20 分ほど
MAX_PAGES = 20             # 1 人の頁送りの安全弁(50 頭×20= 1,000 頭)
BEAT_JOB = "trainer_roster"
COLS = ["lineage_code", "license_no", "trainer_name", "area", "horse_name", "sex_age",
        "birth_year", "sire", "dam", "fetched_on"]


def log(msg):
    print(f"[{dt.datetime.now(JST):%m-%d %H:%M:%S}] {msg}", flush=True)


def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
            with urllib.request.urlopen(r, timeout=40) as x:
                return x.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001  通信の切れは間を伸ばして打ち直す
            if i == tries - 1:
                raise
            log(f"  ! {type(e).__name__} → {5 * 2 ** i} 秒後に打ち直す")
            time.sleep(5 * 2 ** i)


def _txt(s):
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def official_name(raw):
    """字間の空白(全角・半角)を全部落とす。「阿 井 正 雄」→「阿井正雄」。"""
    return re.sub(r"[\s　]", "", htmlmod.unescape(raw))


def short_guess(raw):
    """nar_runs の 3 文字の略称の候補(persons.py と同じ規則= 姓[:2]+名[:3-len(姓[:2])])。
    ⛔2 つ以上の空白が姓と名の切れ目。候補にすぎない= 確定は nar_runs との突き合わせ(SQL 側)。"""
    parts = [re.sub(r"[\s　]", "", p) for p in re.split(r"[\s　]{2,}", htmlmod.unescape(raw).strip())]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return None
    sei, mei = parts[0], "".join(parts[1:])
    a = sei[:2]
    return (a + mei[:max(0, 3 - len(a))])[:3]


# ---- 一覧(調教師) ----
ROW_RE = re.compile(r"k_trainerLicenseNo=(\d+)[^>]*>([^<]+)</a>\s*</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>")


def parse_list(h):
    """[(license_no, 生の氏名, 登録, 所属)]"""
    return [(no, raw.strip(), _txt(st), _txt(area)) for no, raw, st, area in ROW_RE.findall(h)]


def list_total(h):
    m = re.search(r"検索結果:\s*<span>\s*([0-9,]+)", h)
    return int(m.group(1).replace(",", "")) if m else None


def fetch_trainers(wait=WAIT):
    """現役の全調教師(JRA を含む)。{license_no: (生の氏名, 所属)}・総件数"""
    out, total, page = {}, None, 1
    while page <= 60:
        h = get(LIST_URL.format(page=page))
        rows = parse_list(h)
        if total is None:
            total = list_total(h)
        before = len(out)
        for no, raw, _st, area in rows:
            out[no] = (raw, area)
        if not rows or len(out) == before:
            break
        page += 1
        time.sleep(wait)
    return out, total


# ---- 個票(現役管理馬一覧) ----
HORSE_RE = re.compile(
    r"k_lineageLoginCode=(\d+)[^>]*>([^<]+)</a>.*?<td>\s*<span[^>]*>([^<]*)</span>\s*</td>\s*"
    r"<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>", re.S)


def parse_mark(h):
    """個票 1 頁 → (氏名(生), 所属, [馬], 次頁の URL or None)"""
    m = re.search(r'<h4 class="odd_title">([^<]*)</h4>', h)
    raw = m.group(1).strip() if m else ""
    m = re.search(r'intablelabel">\s*所属\s*</td>\s*<td>([^<]*)</td>', h)
    area = _txt(m.group(1)) if m else ""
    k = h.find("現役管理馬一覧")
    horses, nxt = [], None
    if k >= 0:
        body = h[k:]
        end = body.find("</table>")
        tbl = body[:end if end > 0 else len(body)]
        for code, name, sa, by, sire, dam in HORSE_RE.findall(tbl):
            horses.append({"lineage_code": code, "horse_name": _txt(name), "sex_age": _txt(sa),
                           "birth_year": int(by) if _txt(by).isdigit() else None,
                           "sire": _txt(sire), "dam": _txt(dam)})
        m = re.search(r'<a href="([^"]*TrainerMark\?[^"]*k_pageNum=\d+[^"]*)"[^>]*>\s*次の50頭', body[:4000])
        if m:
            nxt = BASE + htmlmod.unescape(m.group(1))
    return raw, area, horses, nxt


def fetch_roster(no, wait=WAIT):
    """1 人ぶん全頁 → (生の氏名, 所属, [馬], 全部読めたか)。
    次頁が残っているのに新しい馬が無い/頁数の安全弁に達した= 途中で止まった(False)。"""
    url, raw, area, horses, seen = MARK_URL.format(no=no), "", "", [], set()
    for _ in range(MAX_PAGES):
        r, a, hs, nxt = parse_mark(get(url))
        raw, area = raw or r, area or a
        new = [x for x in hs if x["lineage_code"] not in seen]
        seen.update(x["lineage_code"] for x in new)
        horses += new
        if not nxt:
            return raw, area, horses, True
        if not new:
            return raw, area, horses, False
        url = nxt
        time.sleep(wait)
    return raw, area, horses, False


# ---- 書き込み(--apply) ----
def _rest(method, path, body=None, prefer="return=minimal"):
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method=method, headers={
        "apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json", "Prefer": prefer})
    with urllib.request.urlopen(r, timeout=90) as x:
        raw = x.read()
    return json.loads(raw) if raw else None


def upsert(table, rows, on_conflict, resolution="merge-duplicates"):
    for i in range(0, len(rows), 500):
        _rest("POST", f"{table}?on_conflict={on_conflict}", rows[i:i + 500],
              prefer=f"resolution={resolution},return=minimal")


def _get_all(path, order):
    """GET を 1000 行ずつ全部。⛔offset は一意の order で。"""
    out, off = [], 0
    while True:
        rows = _rest("GET", f"{path}&order={order}&limit=1000&offset={off}") or []
        out += rows
        if len(rows) < 1000:
            return out
        off += 1000


def fetch_prev():
    """前夜の名簿 {lineage_code: {license_no, area, horse_name, missing_since}}"""
    rows = _get_all("nar_trainer_roster?select=lineage_code,license_no,area,horse_name,missing_since", "lineage_code")
    return {r["lineage_code"]: r for r in rows}


def fetch_recent(since):
    """nar_roster_moves の since 以降(主キー順)"""
    return _get_all(f"nar_roster_moves?select=lineage_code,from_license,to_license,from_area,to_area,seen_on"
                    f"&seen_on=gte.{since}", "seen_on,lineage_code")


def last_known(recent):
    """直近の記録から馬ごとの最後の居場所 {lineage_code: (license, area)}(消えたの行は from 側)"""
    out = {}
    for r in sorted(recent, key=lambda r: (str(r["seen_on"]), r["lineage_code"])):
        lic = r["to_license"] or r["from_license"]
        area = r["to_area"] if r["to_license"] else r["from_area"]
        if lic:
            out[r["lineage_code"]] = (lic, area)
    return out


def diff_moves(prev, cur, seen_on, fetched, gone_licenses=(), recent=None):
    """前夜 prev と今夜 cur({lineage_code: {license_no, area, horse_name(, missing_since)}})の差分。
    fetched= 今夜 全部読めた免許番号・gone_licenses= 一覧から居なくなった人(一覧を全部読めた日だけ)。
    recent= last_known() の {lineage_code: (license, area)}(直近 14 日)。
    → (nar_roster_moves の行, 1 夜目の欠け= missing_since を入れる lineage_code, 消えた= 行を消す lineage_code)。
    prev が空(初回)は全部空(基準づくりだけ)。"""
    if not prev:
        return [], [], []
    known = set(fetched) | set(gone_licenses)
    recent = recent or {}
    out, first_miss, gone = [], [], []
    for code, c in cur.items():
        if c["license_no"] not in known:
            continue                                  # 取れなかった人の行(本来は来ない)
        p = prev.get(code)
        if p is not None and p["license_no"] == c["license_no"]:
            continue
        if p is not None and p["license_no"] not in known:
            continue                                  # ① 取れなかった人から来た馬= 出さない
        fl, fa = (p["license_no"], p["area"]) if p is not None else (None, None)
        if p is None and code in recent and recent[code][0] != c["license_no"]:
            fl, fa = recent[code]                     # ② 直近 14 日に別の免許番号にいた
        out.append({"lineage_code": code, "horse_name": c["horse_name"], "from_license": fl,
                    "to_license": c["license_no"], "from_area": fa, "to_area": c["area"], "seen_on": seen_on})
    for code, p in prev.items():
        if code in cur or p["license_no"] not in known:
            continue                                  # ① 取れなかった人の馬は持ち越し
        ms = p.get("missing_since")
        if not ms:
            first_miss.append(code)                   # ③ 1 夜目は残す(差分なし)
        elif str(ms) < str(seen_on):
            gone.append(code)                         # ③ 2 夜続けて居ない= 消えた
            out.append({"lineage_code": code, "horse_name": p["horse_name"], "from_license": p["license_no"],
                        "to_license": None, "from_area": p["area"], "to_area": None, "seen_on": seen_on})
    return sorted(out, key=lambda r: r["lineage_code"]), sorted(first_miss), sorted(gone)


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--licenses", help="免許番号をカンマ区切り(試し)。無ければ一覧から地方の全員")
    ap.add_argument("--apply", action="store_true", help="本番 DB へ書く(無ければ CSV だけ)")
    ap.add_argument("--probe", action="store_true", help="1 人だけ取って取れるか見る(書かない)")
    ap.add_argument("--out", help="CSV の書き先")
    ap.add_argument("--wait", type=float, default=WAIT)
    a = ap.parse_args(argv)
    today = str(dt.datetime.now(JST).date())

    if a.probe:
        try:
            raw, area, hs, _whole = fetch_roster("11088", wait=a.wait)
        except Exception as e:  # noqa: BLE001
            log(f"取れない: {type(e).__name__} {e}")
            return 2
        log(f"probe {official_name(raw)}({area}) {len(hs)} 頭")
        return 0 if hs else 2

    full_list, tr = None, {}
    if a.licenses:
        targets = [x.strip() for x in a.licenses.split(",") if x.strip()]
    else:
        tr, total = fetch_trainers(wait=a.wait)
        full_list = total is not None and len(tr) == total
        targets = [no for no, (_raw, area) in tr.items() if area != "JRA"]
        log(f"一覧 {len(tr)} 人(検索結果 {total})・地方 {len(targets)} 人")

    rows, trainers, failed = [], [], []
    for i, no in enumerate(targets):
        try:
            raw, area, hs, whole = fetch_roster(no, wait=a.wait)
        except Exception as e:  # noqa: BLE001  1 人の失敗で全体を止めない(その人の古い行は残る)
            failed.append(no)
            log(f"  ! {no} {type(e).__name__}")
            continue
        if not hs or not whole:                         # 0 頭・途中で止まった= 取れなかった扱い(前夜の行を持ち越す)
            failed.append(no)
            log(f"  ! {no} {'0 頭' if not hs else '頁送りが途中で止まった'}")
            continue
        name = official_name(raw)
        trainers.append({"license_no": no, "trainer_name": name, "area": area,
                         "short_guess": short_guess(raw), "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()})
        for x in hs:
            rows.append(dict(x, license_no=no, trainer_name=name, area=area, fetched_on=today))
        if i < len(targets) - 1:
            time.sleep(a.wait)
    log(f"取得 {len(trainers)} 人 / {len(rows)} 頭 / 取れず {len(failed)} 人")
    if a.out:
        write_csv(a.out, rows)
        log(f"CSV {a.out}")
    if not a.apply:
        log("ドライラン(--apply で書く)")
        return 0 if trainers else 1

    import beat as B
    try:
        # D3: 書き換える前に前夜の名簿と比べて差分を追記(初回は出さない・同じ日の打ち直しは重複を無視)
        prev = fetch_prev()
        cur = {r["lineage_code"]: r for r in rows}
        done = {t["license_no"] for t in trainers}
        gone_lic = ({p["license_no"] for p in prev.values()} - set(tr) - set(failed)) if full_list else set()
        since = str(dt.date.fromisoformat(today) - dt.timedelta(days=14))
        recent = last_known(fetch_recent(since)) if prev else {}
        moves, first_miss, gone = diff_moves(prev, cur, today, done, gone_lic, recent)
        upsert("nar_roster_moves", moves, "lineage_code,seen_on", resolution="ignore-duplicates")
        log(f"差分 {len(moves)} 行・1 夜目の欠け {len(first_miss)}・消えた {len(gone)}"
            f"(前夜 {len(prev)} 頭{'・初回= 基準づくり' if not prev else ''})")
        upsert("nar_trainers", trainers, "license_no")
        upsert("nar_trainer_roster", [dict(r, missing_since=None) for r in rows], "lineage_code")
        # ③ 1 夜目の欠けは印だけ・2 夜続けて居ない馬の行だけ消す(取れなかった人の行は持ち越し)
        for k in range(0, len(first_miss), 200):
            _rest("PATCH", f"nar_trainer_roster?lineage_code=in.({','.join(first_miss[k:k + 200])})",
                  {"missing_since": today})
        for k in range(0, len(gone), 200):
            _rest("DELETE", f"nar_trainer_roster?lineage_code=in.({','.join(gone[k:k + 200])})")
        matched = _rest("POST", "rpc/nar_trainers_match_short", {}, prefer="return=representation")
        note = f"{len(trainers)}人 {len(rows)}頭 取れず{len(failed)} 略称{matched} 差分{len(moves)}"
        ok = len(failed) <= max(5, len(targets) // 20)   # 5% を超えて落ちた日は失敗と記す
        B.beat(BEAT_JOB, ok, note)
        log(f"書いた: {note}")
        return 0 if ok else 1
    except Exception as e:  # noqa: BLE001
        B.beat(BEAT_JOB, False, f"書けない {type(e).__name__}")
        raise


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
