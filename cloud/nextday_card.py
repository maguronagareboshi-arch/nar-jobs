# -*- coding: utf-8 -*-
"""翌日の出馬表を公式の出馬表ページ(TodayRaceInfo/DebaTable)から作る(月末の穴埋め・2026-10-01)。

なぜ要るか(2026-09-30 の事故):
  翌日の出馬表は公式の月次ZIP(翌日を含む月)から取っている(日次ZIPは日付を指定しても今日の分しか返さない)。
  月末の日は翌月の月次ZIPがまだ公開されておらず(9/30 05:33 の取り込みで「翌月: まだ公式に無い」)、
  翌月 1 日の出馬表が当日になるまで DB に入らない → 前夜の予想の便(nar-ai-v3)が 0 頭で止まった。
  公式の出馬表ページには前日の時点で全レースが載っている(9/30 20:21 に 10/1 船橋 12R を確認)。

作るもの: nar_official_csv.normalize_archive と同じ形の文書(races・horses・payouts=[])。
  - 値の書き方は月次ZIPの行と同じにそろえる(check で ZIP と全列を照合して確かめる)。
  - 出馬表ページから正しく作れない列は入れない(race_kind)。load_nar_official は「無い列は送らない」ので、
    当日の日次ZIPが来た時点で公式の値に置き換わる。
  - 取る数: 開催一覧 1 + 場ごとのレース一覧 + 1 レース 1 ページ(0.5 秒おき)。

  python cloud/nextday_card.py check 2026-10-02     # 月次ZIPに同じ日がある日で、全列を照合(書かない)
  python cloud/nextday_card.py show 2026-10-02      # 作った文書の件数だけ表示(書かない)
"""
import datetime as dt
import html as _html
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))
from nar_official_csv import FORMAT, digest, digest_bytes  # noqa: E402
from odds import BABA, http_get  # noqa: E402

BASE = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo"
CODE2TRACK = {v: k for k, v in BABA.items()}
SLEEP = 0.5
_ZEN = str.maketrans("0123456789", "０１２３４５６７８９")
_HAN = str.maketrans("０１２３４５６７８９", "0123456789")   # 馬名の数字は月次ZIPでは半角(ミリオンセラー2)


def _get(url):
    raw = http_get(url)
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw


def _q(date):
    return date.strftime("%Y%%2F%m%%2F%d")


def _clean(fragment):
    s = re.sub(r"<[^>]+>", " ", fragment)
    s = _html.unescape(s).replace("\xa0", " ")
    return re.sub(r"[ \t\r\n]+", " ", s).strip()


def day_tracks(date):
    """その日に開催がある場のコード(公式の開催一覧)。"""
    h = _get(f"{BASE}/TodayRaceInfoTop?k_raceDate={_q(date)}")
    return sorted(set(re.findall(r"RaceList\?k_raceDate=" + _q(date) + r"&amp;k_babaCode=(\d+)", h)))


def race_nos(date, baba):
    h = _get(f"{BASE}/RaceList?k_raceDate={_q(date)}&k_babaCode={baba}")
    pat = r"DebaTable\?k_raceDate=" + _q(date) + r"&amp;k_raceNo=(\d+)&amp;k_babaCode=" + baba + r"\b"
    return sorted({int(x) for x in re.findall(pat, h)})


def _num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_race(h, date, track, race_no):
    """出馬表ページ 1 枚 → (race, horses)。月次ZIPの normalize_races / normalize_horses と同じ鍵・書き方。"""
    head = re.search(r"<h4>(.*?)</h4>", h, re.S)
    post = re.search(r"(\d{1,2}):(\d{2})発走", _clean(head.group(1)) if head else "")
    title = re.search(r'<section class="raceTitle">(.*?)</section>', h, re.S)
    t = title.group(1) if title else ""
    name = _clean((re.search(r"<h3>(.*?)</h3>", t, re.S) or [None, ""])[1])
    lis = [_clean(x) for x in re.findall(r"<li>(.*?)</li>", t, re.S)]
    info = lis[0] if lis else ""
    m = re.search(r"(ダート|芝)\s*(\d+)ｍ（(?:[^）]*・)?(右|左|直)）\s*(.*?)\s*(?:＊|$)", info)   # 大井は「（外コース・右）」
    surface, dist, dirc, cond = (m.group(1), int(m.group(2)), m.group(3), m.group(4).strip()) if m else ("", 0, "", "")
    tok = [x for x in cond.translate(_ZEN).split() if not x.startswith(("天候：", "馬場："))]   # 当日以降のページは天候・馬場が入る
    cond = (tok[0] + "　" + " ".join(tok[1:])).strip() if tok else ""   # 月次ZIPの書き方: 1 つ目の区切りだけ全角空白
    prize = [0] * 5
    for x in lis[1:]:
        for i, yen in re.findall(r"(\d)着([\d,]+)円", x):
            if 1 <= int(i) <= 5:
                prize[int(i) - 1] = int(yen.replace(",", ""))
    horses = []
    card = h.split('<section class="cardTable">', 1)[-1].split("</section>", 1)[0] if '<section class="cardTable">' in h else ""
    last_gate = None
    for b in card.split('<tr class="tBorder">')[1:]:
        b = re.sub(r'<table class="arrival.*?</table>', "", b, flags=re.S)   # 着別成績の入れ子の表は使わない
        gate = re.search(r'class="courseNum[^"]*">\s*(\d+)\s*</td>', b)
        if gate:
            last_gate = int(gate.group(1))                                   # 同じ枠の 2 頭目には枠の欄が無い
        num = re.search(r'class="horseNum">\s*(\d+)\s*</td>', b)
        hn = re.search(r'class="horseName"[^>]*>(.*?)</a>', b, re.S)
        jk = re.search(r'class="jockeyName"[^>]*>(.*?)<span class="jockeyarea">', b, re.S)
        sa = re.search(r"<span[^>]*>\s*(牡|牝|セン|セ|騸)\s*(\d+)\s*</span>", b)
        bd = re.search(r"<td>\s*(\d{2})\.(\d{2})生\s*</td>", b)
        wt = re.search(r"<td>\s*([^\d<]*?)\s*(\d+\.\d)\s*　", b)
        rows3 = re.findall(r'<td colspan="3">(.*?)</td>', b, re.S)
        tr = re.search(r'TrainerMark\?[^"]*">\s*(.*?)（(.*?)）\s*</a>', b, re.S)
        rows1 = [_clean(x) for x in re.findall(r'<td colspan="1">(.*?)</td>', b, re.S)]
        if not (num and hn):
            continue
        age = int(sa.group(2)) if sa else None
        birth = None
        if bd and age is not None:
            try:
                birth = dt.date(date.year - age, int(bd.group(1)), int(bd.group(2))).isoformat()
            except ValueError:
                birth = None
        mark = (wt.group(1) or "").strip() if wt else ""
        sire = _clean(rows3[1]).translate(_HAN) if len(rows3) > 1 else ""
        dam = _clean(rows3[2]).translate(_HAN) if len(rows3) > 2 else ""
        bms = _clean(rows3[3]).strip("（）()").translate(_HAN) if len(rows3) > 3 else ""
        # colspan=1 の並び: [騎手, 調教師, 馬主, 生産牧場](騎手・調教師はリンク付きで別に取る)
        owner = rows1[2] if len(rows1) > 2 else ""
        breeder = rows1[3] if len(rows1) > 3 else ""
        horses.append({
            "track": track, "race_date": date.isoformat(), "race_no": race_no,
            "gate": last_gate,
            "runner_number": int(num.group(1)),
            "horse_name": _clean(hn.group(1)).translate(_HAN),
            "sex": {"セ": "セン", "騸": "セン"}.get(sa.group(1), sa.group(1)) if sa else "",   # 月次ZIPの書き方は「セン」
            "age": age,
            "birth_date": birth,
            "sire": sire, "dam": dam, "broodmare_sire": bms,
            "jockey": _clean(jk.group(1)) if jk else "",
            "trainer": _clean(tr.group(1)) if tr else "",
            "trainer_area": _clean(tr.group(2)) if tr else "",
            "owner": owner, "breeder": breeder,
            "carried_weight": _num(wt.group(2)) if wt else None,
            "weight_mark": mark or None,
            "body_weight": None, "body_weight_change": None, "finish": None,
            "time_raw": "", "margin": "", "last3f": None, "popularity": None,
        })
    race = {
        "track": track, "race_date": date.isoformat(), "race_no": race_no,
        "post_time": f"{int(post.group(1)):02d}{post.group(2)}" if post else "",
        "race_name": name, "surface": surface, "direction": dirc, "distance_m": dist,
        "weather": "", "going": "", "field_size": len(horses), "condition": cond, "prize_yen": prize,
        "race_last4f": None, "race_last3f": None, "furlongs": [], "corners": [],
    }
    return race, horses


def fill_doc(date, have=(), log=print):
    """date の公式の開催一覧と照らし、have(月次ZIPに入っていた (場, R))に無いレースだけ出馬表ページから作る。
    足りないレースが無ければ None。開催が無い日も None。"""
    t0 = time.time()
    want = []
    for c in day_tracks(date):
        track = CODE2TRACK.get(c)
        if not track:
            continue
        time.sleep(SLEEP)
        want += [(track, c, no) for no in race_nos(date, c)]
    miss = [(t, c, no) for t, c, no in want if (t, no) not in set(have)]
    log(f"翌日 {date} 出馬表ページ: 公式の開催一覧 {len(want)} R・月次ZIPにある {len(want) - len(miss)} R・足りない {len(miss)} R")
    if not miss:
        return None
    races, horses, pages = [], [], []
    for track, c, no in miss:
        time.sleep(SLEEP)
        h = _get(f"{BASE}/DebaTable?k_raceDate={_q(date)}&k_raceNo={no}&k_babaCode={c}")
        r, hs = parse_race(h, date, track, no)
        if not hs:
            log(f"  {track}{no}R: 出馬表ページに馬が無い(飛ばす)"); continue
        races.append(r); horses.extend(hs); pages.append(h)
    doc = {
        "format": FORMAT, "kind": "race", "scope": "nextday-html",
        "source_url": f"{BASE}/TodayRaceInfoTop?k_raceDate={_q(date)}",
        "source_observed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_snapshot_hash": digest_bytes("\n".join(pages).encode("utf-8")),
        "files": [], "races": races, "horses": horses, "payouts": [],
    }
    doc["document_hash"] = digest(doc)
    log(f"  出馬表ページから races={len(races)} 頭={len(horses)} ({time.time() - t0:.0f}s)")
    return doc


def build_doc(date, log=print, tracks=None):
    """date の全場・全レースの出馬表 → 正規化文書(書かない)。開催が無ければ races = []。"""
    t0 = time.time()
    codes = day_tracks(date)
    if tracks:
        codes = [c for c in codes if CODE2TRACK.get(c) in tracks]
    races, horses, pages = [], [], []
    for c in codes:
        track = CODE2TRACK.get(c)
        if not track:
            continue
        time.sleep(SLEEP)
        for no in race_nos(date, c):
            time.sleep(SLEEP)
            h = _get(f"{BASE}/DebaTable?k_raceDate={_q(date)}&k_raceNo={no}&k_babaCode={c}")
            r, hs = parse_race(h, date, track, no)
            if not hs:
                continue
            races.append(r); horses.extend(hs); pages.append(h)
    doc = {
        "format": FORMAT, "kind": "race", "scope": "nextday-html",
        "source_url": f"{BASE}/TodayRaceInfoTop?k_raceDate={_q(date)}",
        "source_observed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_snapshot_hash": digest_bytes("\n".join(pages).encode("utf-8")),
        "files": [], "races": races, "horses": horses, "payouts": [],
    }
    doc["document_hash"] = digest(doc)
    log(f"出馬表ページ {date}: 場 {len(codes)} races={len(races)} 頭={len(horses)} ({time.time() - t0:.0f}s)")
    return doc


def check(date):
    """月次ZIPの同じ日の行と全列を照合する(race_kind・cancelled は出馬表ページから作らないので外す)。"""
    from nar_official_csv import download_archive, download_url, normalize_archive
    p, f = download_archive(download_url("race", scope="monthly", year=date.year, month=date.month))
    z = normalize_archive(p, kind="race", scope="monthly", source_url=f, observed_at="x")
    w = date.isoformat()
    zr = {(r["track"], r["race_no"]): r for r in z["races"] if r["race_date"] == w}
    zh = {(r["track"], r["race_no"], r["runner_number"]): r for r in z["horses"] if r["race_date"] == w}
    d = build_doc(date)
    bad, n = {}, {"races": 0, "horses": 0}
    for kind, mine, ref, key in (("races", d["races"], zr, lambda r: (r["track"], r["race_no"])),
                                 ("horses", d["horses"], zh, lambda r: (r["track"], r["race_no"], r["runner_number"]))):
        keys_m = {key(r) for r in mine}
        print(kind, '出馬表ページ', len(keys_m), 'ZIP', len(ref), 'ページだけ', sorted(keys_m - set(ref))[:5],
              'ZIPだけ', sorted(set(ref) - keys_m)[:5])
        for r in mine:
            o = ref.get(key(r))
            if o is None:
                continue
            n[kind] += 1
            for c in set(o) | set(r):
                if c in ("race_kind", "cancelled"):
                    continue
                if r.get(c) != o.get(c):
                    bad.setdefault((kind, c), []).append((key(r), r.get(c), o.get(c)))
    print('照合した行', n)
    for (kind, c), v in sorted(bad.items()):
        print(f'  合わない {kind}.{c}: {len(v)} 件 例 {v[:3]}')
    if not n["races"] or not n["horses"]:
        print('  ⛔ 重なる行が無い(照合になっていない)')
        return False
    if not bad:
        print('  重なる行は全列一致')
    return not bad


if __name__ == "__main__":
    cmd, day = sys.argv[1], dt.date.fromisoformat(sys.argv[2])
    if cmd == "check":
        sys.exit(0 if check(day) else 1)
    elif cmd == "show":
        build_doc(day)
