# -*- coding: utf-8 -*-
"""本体 cloud: 公式サイトの能力検査を集めて nar_meta へ入れる(DESIGN §32a)。

第1陣 = 岩手(盛岡・水沢)・兵庫(園田・西脇)。第2陣 = 佐賀・ばんえい帯広。
第3陣(§32c) = 笠松・名古屋・高知。この3場は HTML ではなく成績表 PDF しか無い。
第4陣(§117b) = 門別・大井・船橋・川崎・浦和。手元の PC のジョブ(旧 chihou_meta)から移した5場。
  ⛔主催者公式だけで組むので、公式に無い列は入れない(南関= 着順・馬番・上がり3F・馬場・天候・短評 /
  門別= 上がり3F・短評)。下調べ= docs/s117_survey_result.md。
どれもログイン不要の公式ページなのでクラウドから取れる。
出力の形は既存の {prefix}_noken(chihou_meta)と同じ: {"days":[{"date","races":[{"no","dist","rows":[…]}]}]}。
行のキーも既存に合わせる(ok/fin/name/time/jockey/sexage/umaban/weight/trainer…)。無い項目は入れない。
映像は主催者によって単位が違う: 兵庫/佐賀/ばんえい/笠松/高知/南関4場/名古屋/金沢は1日1本なので day.video、
岩手はレースごとなので races[].video(全レースには付かない・2021年より前は1本も無い)、門別は races[].mp4。
大井・浦和は動画の説明欄に章(0:00 第1組…)があるので `{prefix}_noken_offsets` も作る(§33.7-3 と同じ形)。

  python cloud/noken_public.py --venue iwate            # 差分更新(索引にある日を全部・保存済みはスキップ)
  python cloud/noken_public.py --venue hyogo --backfill # 全量(兵庫は detail/1 から順に)
  python cloud/noken_public.py --venue saga  --backfill # 全量(2020年度〜。年度ページを 前年 リンクで遡る)
  python cloud/noken_public.py --venue banei --backfill # 全量(お知らせ検索「能力検査」で記事を列挙)
  python cloud/noken_public.py --venue kasamatsu        # PDF(索引に出ている回だけ=だいたい1年ぶん)
  python cloud/noken_public.py --venue nagoya --backfill # PDF(nr{和暦}-{回}.pdf を令和6年度から総当たり)
  python cloud/noken_public.py --venue kochi --backfill  # PDF(?cat=42 の記事を遡る。2020-03-30 以降が読める)
  python cloud/noken_public.py --venue kanazawa --backfill # PDF(お知らせ「レース」を 2019-06 まで遡る)
  python cloud/noken_public.py --venue monbetsu         # 索引の新しい3日(--backfill= 索引の全部=今年度)
  python cloud/noken_public.py --venue ooi              # 日付の総当たり(直近21日+索引の日。404=その日は無い)
  python cloud/noken_public.py --venue kawasaki --backfill # 今年の1/1から今日まで総当たり
  python cloud/noken_public.py --venue ooi --dry-run --out out/  # ooi_noken.json と ooi_noken_offsets.json
  python cloud/noken_public.py --env pipeline/.env.nar --dry-run --out out/
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY
⚠PDF の3場は pdfplumber が要る(cloud/requirements.txt)。入っていない環境でも既存5源は動くように
  PDF 経路の中でだけ import する。
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗
"""
import argparse
import datetime as dt
import email.utils
import html as H
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
from load_nar_official import load_env, upsert  # noqa: E402

UA = "nar-jobs/1.0"
SLEEP = 0.7
JST = dt.timezone(dt.timedelta(hours=9))


def log(msg):
    print(f"[{dt.datetime.now(JST):%H:%M:%S}] {msg}", flush=True)


_last = [0.0]


def get(url, tries=1, enc="utf-8"):
    """tries>1 で 5xx だけ間を置いて取り直す(ばんえいのサーバは2%ほど 500 を返すが
    同じ URL をもう一度叩けば通る。2026-08-26 実測 347件中7件)。404 等は取り直さない。
    enc= 文字コード(南関 nankankeiba.com は Shift_JIS なので cp932 を渡す)。"""
    for n in range(tries):
        wait = SLEEP - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=25).read().decode(enc, "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or n == tries - 1:
                raise
            _last[0] = time.monotonic()
            time.sleep(2.0 * (n + 1))
        finally:
            _last[0] = time.monotonic()


def get_bin(url, tries=1):
    """PDF 用。中身と Last-Modified を返す(名古屋は PDF に年が書いていないので掲載日で年を決める)。
    get() と同じ間合い(SLEEP)を守る。"""
    for n in range(tries):
        wait = SLEEP - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            res = urllib.request.urlopen(req, timeout=40)
            return res.read(), res.headers.get("Last-Modified")
        except urllib.error.HTTPError as e:
            if e.code < 500 or n == tries - 1:
                raise
            _last[0] = time.monotonic()
            time.sleep(2.0 * (n + 1))
        finally:
            _last[0] = time.monotonic()


def strip(fragment, br=" "):
    """タグを外して1行にする。br に "\n" を渡したときだけ <br> を改行として残す
    (佐賀の「父馬名<br>母馬名」のように1セルに2項目入る表で使う)。"""
    if br != " ":
        fragment = re.sub(r"<br\s*/?>", br, fragment, flags=re.I)
    s = H.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace(" ", " ")
    if br == " ":
        return re.sub(r"\s+", " ", s).strip()
    return br.join(re.sub(r"[^\S\r\n]+", " ", x).strip() for x in s.split(br)).strip()


def norm(text):
    """全角を半角へ寄せる。公式ページの見出しは「水沢1R（能力検査）1300ｍ」のように
    括弧も単位も全角のことがある(2026-08-26 実測)。照合の前に必ず通す。"""
    return unicodedata.normalize("NFKC", text)


ERA = {"令和": 2018, "平成": 1988, "昭和": 1925}
ERA_DATE_RE = re.compile(r"(?:(令和|平成|昭和)\s*(元|\d+)|(\d{4}))\s*年\s*(\d+)\s*月\s*(\d+)\s*日")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
YT_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/|live/)|youtu\.be/)([\w-]+)")


def era_date(text):
    """「令和8年8月21日」「2020年3月27日」→ 2026-08-21 / 2020-03-27。読めなければ None。
    norm() を通した文字列を渡すこと。"""
    m = ERA_DATE_RE.search(text)
    return era_of(m) if m else None


def era_of(m):
    if m.group(3):
        year = int(m.group(3))
    else:
        year = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
    return f"{year}-{int(m.group(4)):02d}-{int(m.group(5)):02d}"


def era_dates(text):
    """1つの見出しに日付が複数あることがある(笠松「令和8年6月12日（金）及び令和8年6月26日（金）」)。
    年の無い2つめ(「及び3月20日」)は拾えないので、これだけを頼りに何かを捨ててはいけない。"""
    return [era_of(m) for m in ERA_DATE_RE.finditer(text)]


TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.S)


def tables_of(page):
    return [m.group(0) for m in TABLE_RE.finditer(page)]


def rows_of(table, br=" "):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        out.append([strip(c, br) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)])
    return out


# ---------------------------------------------------------------- 表の読み方(4場 共通)
# 列の並びは主催者ごとに違う(岩手=馬番/出走馬/年齢/厩舎/騎乗者/馬体重/タイム/合否・
# 兵庫=馬名/齢/距離/タイム/体重/きゅう舎/合否。兵庫の「自主参加」表には合否が無い・
# 佐賀=番号/馬名/性/資格/騎手/斤量/調教師/父馬名母馬名/順位/タイム/馬体重/合否/備考・
# ばんえい=着順/馬番/馬名/[性別]/重量/騎手/調教師/タイム/[合否])。
# 位置決め打ちにせずヘッダ行から列の対応を作る。
COLS = {
    "馬番": "umaban", "番": "umaban", "番号": "umaban",
    "出走馬": "name", "馬名": "name",
    "年齢": "sexage", "性齢": "sexage", "齢": "sexage", "性別年齢": "sexage",
    "性": "sexage", "性別": "sexage",
    "厩舎": "trainer", "きゅう舎": "trainer", "調教師": "trainer",
    "騎乗者": "jockey", "騎手": "jockey",
    "馬体重": "weight", "体重": "weight", "馬体重(kg)": "weight",
    "タイム": "time",
    "合否": "ok", "判定": "ok",
    "距離": "dist",
    "資格": "cls",            # 佐賀=出走資格(C1/2歳…)。馬齢ではないので sexage には入れない
    "斤量": "kin", "重量": "kin",   # ばんえいの「重量」はソリの積載重量(馬体重ではない)
    "順位": "fin", "着順": "fin",
    "備考": "note",
    "父馬名母馬名": "ped",     # 1セルに父<br>母。row_of で sire/dam に割る
}
DASHES = {"", "-", "‐", "‑", "–", "—", "―", "−", "ー", "*"}


def key_of(text, extra=None):
    """extra = その場だけの列名の対応(PDF の3場。COLS に足すと既存の場に効いてしまう。
    例: 笠松には「調教師」と「厩舎」が両方あるので、厩舎を trainer にしてはいけない)。"""
    k = norm(text).replace(" ", "").replace("\n", "")
    if extra and k in extra:
        return extra[k]
    return COLS.get(k, "")


def header_at(rws, extra=None):
    """ヘッダ行(出走馬…/馬名…)の位置と 列→キー の対応を返す。無ければ (-1, [])。"""
    for i, cells in enumerate(rws):
        keys = [key_of(c, extra) for c in cells]
        if "name" in keys and sum(1 for k in keys if k) >= 3:
            # 岩手は馬番の見出しが空欄。先頭列だけは空でも馬番として拾う
            if keys and not keys[0] and "umaban" not in keys:
                keys[0] = "umaban"
            return i, keys
    return -1, []


def cell(text):
    s = norm(text).strip()
    return "" if s in DASHES else s


def fix_time(s):
    """兵庫は「1,20.6」「0,51.2」の書き方。既存データ(1.24.2 / 53.4)に揃える。"""
    t = s.replace(",", ".")
    return re.sub(r"^0\.(?=\d{2}\.\d)", "", t)


# 行には入れない列(レース側で使う・呼び側が col_of で読む)
ROW_SKIP = {"dist", "grp", "meet", "start"}


def row_of(cells, keys, join=None):
    """ヘッダの対応どおりに1行を作る。空の項目はキーごと入れない(既存の形に合わせる)。
    join = {キー: つなぎ文字}。同じキーの列が2つある表で上書きせずにつなぐ
    (名古屋は「性」「齢」が別の列・笠松は不合格理由と受検理由が別の列)。"""
    row = {}
    for text, key in zip(cells, keys):
        if not key or key in ROW_SKIP:
            continue
        if key == "ped":          # 佐賀「父馬名<br>母馬名」。片方しか無い行も落とさない
            parts = [p for p in (cell(x) for x in text.split("\n")) if p]
            if parts:
                row["sire"] = parts[0]
            if len(parts) > 1:
                row["dam"] = parts[1]
            continue
        v = cell(text)
        if not v:
            continue
        if join and key in join and row.get(key):
            row[key] += join[key] + v
            continue
        row[key] = fix_time(v) if key == "time" else v
    return row


def col_of(cells, keys, want):
    """その行の want 列の生の文字(レース番号・距離・発走時刻を読むため)。無ければ ""。"""
    for text, key in zip(cells, keys):
        if key == want:
            return norm(text).replace("\n", " ").strip()
    return ""


def dist_of(cells, keys):
    for text, key in zip(cells, keys):
        if key == "dist":
            m = re.search(r"\d+", norm(text))
            return int(m.group(0)) if m else None
    return None


def body_rows(rws, head_i, keys):
    """ヘッダの下のデータ行だけ(見出しの繰り返し・空行・区分名の行は落とす)"""
    out = []
    for cells in rws[head_i + 1:]:
        if len(cells) < 3 or not any(cell(c) for c in cells):
            continue
        if sum(1 for c in cells if key_of(c)) >= 3:
            continue          # ヘッダの繰り返し(長い表で途中に入ることがある)
        row = row_of(cells, keys)
        if row.get("name"):
            out.append((row, dist_of(cells, keys)))
    return out


def sb_get_meta(base, key, meta_key, table="nar_meta"):
    url = f"{base}/rest/v1/{table}?select=value&key=eq.{meta_key}"
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8"))
        return rows[0]["value"] if rows else None
    except Exception:
        return None


# ---------------------------------------------------------------- 岩手(盛岡・水沢)

IWATE_INDEX = "https://www.iwatekeiba.or.jp/race-data/noken"
# 表の直前の <p> に「水沢1R（能力検査）1300ｍ」の形で場・R番・距離が書いてある(2026-08-26 実測)。
# 括弧も単位も全角なので、照合はタグを外して norm() を通した文字列に対して行う。
IWATE_RACE_RE = re.compile(r"(盛岡|水沢)\s*(\d+)\s*R\s*\(?\s*(?:能力検査|能検)\s*\)?\s*(\d+)\s*m", re.I)
# 本文の終わり。ここから後ろはフッタのナビなので、最後の表の「直後」を見るときの行き止まりにする。
IWATE_END_RE = re.compile(r'<div id="footnav"|<footer', re.I)


def iwate_videos(page, tabs, limit, owner, date):
    """レースごとの映像。結果表の直後(次の表が始まるまでの間)にある YouTube の iframe を
    その表のレースに付ける。岩手の能検ページは「見出しの<p> → 結果表 →(あれば)映像の iframe」の
    並びで、映像が始まった2021年からこの形が崩れていない(2026-08-26 実測: 索引の231ページ・
    iframe 173本が全部 表と表の間にあり、表の中・最初の表より前・フッタより後ろは0本)。
    映像は全レースには付かない(1日4Rで2本など)ので、本数を数えて割り当てるのではなく
    「どの表の後ろに置かれているか」だけで決める。並びが読めない所は付けない方に倒す。
    ⚠映像の題(YouTube側)は主催者の手打ちで当てにならない。173本のうち4本は題と置き場所が食い違うが、
    うち1本は同じ題の動画が同じページに2本、もう1本は題の日付が2週間ずれ、と題の方が壊れている
    (置き場所は231ページ全部で1つも崩れていない)。題は照合に使わない。"""
    for i, tm in enumerate(tabs):
        seg = page[tm.end():(tabs[i + 1].start() if i + 1 < len(tabs) else limit)]
        ids = list(dict.fromkeys(YT_RE.findall(seg)))
        if not ids:
            continue
        if i not in owner:
            log(f"  岩手 {date} レースとして読めない表の後ろに映像 {ids}(付けない)")
        elif len(ids) > 1:
            log(f"  岩手 {date} {owner[i]['venue']}{owner[i]['no']}R の後ろに映像が{len(ids)}本"
                f" {ids}(どれのものか決められないので付けない)")
        else:
            owner[i]["video"] = "https://www.youtube.com/watch?v=" + ids[0]
    pre = YT_RE.findall(page[:tabs[0].start()]) if tabs else []
    if pre:
        log(f"  岩手 {date} 最初の表より前に映像 {pre}(どのレースのものか決められないので付けない)")


def iwate_day(url, date, venue_label):
    """1日ぶん。1ページに水沢と盛岡の両方が載ることがある(実測 260801e)ので場はレース単位で持つ。
    レースごとの映像は表の直後に置かれているので iwate_videos で拾って races[].video に入れる。"""
    page = get(url)
    end = IWATE_END_RE.search(page)
    tabs = list(TABLE_RE.finditer(page))
    races, owner = [], {}
    prev, head = 0, None
    for i, tm in enumerate(tabs):
        found = list(IWATE_RACE_RE.finditer(norm(strip(page[prev:tm.start()]))))
        prev = tm.end()
        if found:
            head = found[-1]
        if head is None:          # 見出しの無い表(ページ内の飾り)は読まない
            continue
        rws = rows_of(tm.group(0))
        hi, keys = header_at(rws)
        if hi < 0:
            continue
        rows = [r for r, _ in body_rows(rws, hi, keys)]
        if rows:
            race = {"no": int(head.group(2)), "dist": int(head.group(3)),
                    "venue": head.group(1), "rows": rows}
            races.append(race)
            owner[i] = race       # 表の位置 → レース。映像を貼るときの手がかり
        head = None               # 見出しは1つの表で使い切る
    if not races:
        return None
    iwate_videos(page, tabs, end.start() if end else len(page), owner, date)
    venues = {r["venue"] for r in races}
    venue = venues.pop() if len(venues) == 1 else (venue_label or "")
    return {"date": date, "venue": venue, "races": races}


def iwate_drop_reused(days):
    """同じ映像が別の日にも貼ってあったら、どちらかが主催者の貼り間違い。ページからは
    どちらが正しいか決められないので両方から外す(誤った映像を出すより無い方がよい)。
    実測1件: HwnW4Y-QhfU が 2021-06-05(盛岡2R)と 2021-06-19(水沢2R)の両方に入っている。
    動画の題は「2021年6月5日…盛岡２R」なので 6/19 側が前回の使い回し。
    ⚠見えるのはこの実行で集めた日どうしだけ。差分更新で1日ずつ取るときは気づけない。"""
    where = {}
    for d in days:
        for r in d["races"]:
            if r.get("video"):
                where.setdefault(r["video"], []).append((d["date"], r))
    for url, hits in where.items():
        if len({date for date, _ in hits}) > 1:
            log(f"  岩手 同じ映像が複数の日に {url} "
                f"{sorted(date for date, _ in hits)}(貼り間違いなのでどれにも付けない)")
            for _, r in hits:
                r.pop("video", None)


def collect_iwate(existing_dates, backfill):
    idx = get(IWATE_INDEX)
    items = re.findall(r'href="(https?://www\.iwatekeiba\.or\.jp/news/(\d{6})e)"[^>]*>(.*?)</a>', idx, re.S)
    seen, days, miss, empty = set(), [], 0, 0
    for url, ymd, label in items:
        if url in seen:
            continue
        seen.add(url)
        date = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}"
        if not backfill and date in existing_dates:
            continue
        label = strip(label)
        venue = "盛岡" if "盛岡" in label else ("水沢" if "水沢" in label else "")
        try:
            day = iwate_day(url, date, venue)
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  岩手 {date} 索引の死にリンク HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  岩手 {date} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        if day:
            days.append(day)
            nv = sum(1 for r in day["races"] if r.get("video"))
            log(f"  岩手 {date} {day['venue']} {sum(len(r['rows']) for r in day['races'])}頭/"
                f"{len(day['races'])}R" + (f"(映像 {nv}R)" if nv else ""))
        else:
            empty += 1
            log(f"  岩手 {date} 表が読めない(見出し無し・古い書式?)")
    iwate_drop_reused(days)
    vids = sum(1 for d in days for r in d["races"] if r.get("video"))
    races = sum(len(d["races"]) for d in days)
    log(f"  岩手: 索引 {len(seen)} 件 / 取得できた {len(days)} / 取れなかった {miss} / 中身なし {empty}"
        f" / 映像つき {vids}R(全 {races}R)")
    return days


# ---------------------------------------------------------------- 兵庫(園田・西脇)

HYOGO_LIST = "https://www.sonoda-himeji.jp/data/ability/"

# §33.7-1 兵庫の映像。⛔**レース単位ではなく1日1本**(2026-08-26 実測: プレイリストの動画100本が
# ぜんぶ「能力検査 2026年8月18日(火) 西脇馬事公苑」の形・長さ5分ほどの その日まるごと1本)。
# だから races[].video には付けない(岩手 §33.2 と同じ規律=対応が決められないものは付けない)。
# 公式の検査ページはどの日も同じプレイリストを貼っているだけなので、そのままだと26日ぜんぶが
# 同じ URL になる。題の「年月日+場」で日と突き合わせて day.video をその日の1本に差し替える。
HYOGO_PLAYLIST = "https://www.youtube.com/playlist?list=PLPPu0DjqqwMPJlRy0dgI7XcpgVVHSnEyr"
HYOGO_DATE_RE = re.compile(r'l-ability_date[^>]*>\s*(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})')
HYOGO_NAME_RE = re.compile(r'l-ability_name[^>]*>(.*?)</div>', re.S)
YT_INITIAL_RE = re.compile(r"var ytInitialData\s*=\s*(\{.*?\});</script>", re.S)
YT_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def yt_title_of(node):
    """YouTube の JSON の1節から題を取る。古い形(title.runs[0].text / title.simpleText)と
    新しい形(metadata.lockupMetadataViewModel.title.content)のどちらでも読めるように。"""
    t = node.get("title")
    if isinstance(t, dict):
        for key in ("content", "simpleText"):
            if isinstance(t.get(key), str):
                return t[key]
        runs = t.get("runs")
        if isinstance(runs, list) and runs and isinstance(runs[0], dict):
            got = runs[0].get("text")
            if isinstance(got, str):
                return got
    meta = node.get("metadata")
    if isinstance(meta, dict):
        for v in meta.values():
            if isinstance(v, dict):
                got = yt_title_of(v)
                if got:
                    return got
    return None


def yt_titles(url):
    """プレイリストのページ → [(動画ID, 題)]。ページ埋め込みの ytInitialData を歩いて
    「11文字の動画IDと題を両方持つ節」だけ拾う(作りが変わっても落ちないように名前で決め打ちしない)。
    ⚠外部サイトなので読めないことがある。そのときは空を返して呼び側は今までどおりにする。
    ⚠yt-dlp は要らない(標準ライブラリだけ・映像は落とさない)。"""
    page = get(url)
    m = YT_INITIAL_RE.search(page)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    out = {}

    def walk(node):
        if isinstance(node, dict):
            vid = node.get("contentId") or node.get("videoId")
            ttl = yt_title_of(node)
            if isinstance(vid, str) and re.fullmatch(r"[\w-]{11}", vid) and ttl and vid not in out:
                out[vid] = ttl
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return list(out.items())


def hyogo_videos():
    """(実施日, 場) → 動画ID。同じ日・同じ場に2本あったら どれのものか決められないので付けない。"""
    try:
        items = yt_titles(HYOGO_PLAYLIST + "&hl=ja")
    except Exception as e:
        log(f"  兵庫: プレイリストが読めない {type(e).__name__}: {str(e)[:80]}"
            f"(日ごとの映像は付けずプレイリストのまま)")
        return {}
    by = {}
    for vid, title in items:
        m = YT_DATE_RE.search(norm(title))
        if not m:
            log(f"  兵庫 プレイリストに日付の無い動画 {vid} 「{title[:40]}」(使わない)")
            continue
        venue = next((v for v in ("西脇", "姫路", "園田") if v in title), "")
        by.setdefault((f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", venue),
                      []).append(vid)
    out = {}
    for key, vids in by.items():
        if len(vids) == 1:
            out[key] = vids[0]
        else:
            log(f"  兵庫 {key[0]} {key[1]} に動画が {len(vids)} 本 {vids}(決められないので付けない)")
    log(f"  兵庫: プレイリストの動画 {len(items)} 本 / 日と場の読めた {len(out)}")
    return out


def hyogo_head(page):
    """ページ上部の「2026/8/18 西脇トレーニングセンター 天候：晴 馬場状態：良」を読む。
    日付は本文の <div class="l-ability_date"> から取る(ページ先頭には別の日付が混ざる)。"""
    m = HYOGO_DATE_RE.search(page)
    if not m:
        main = page[page.find("<main"):] if "<main" in page else page
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", strip(main))
    if not m:
        return None, "", None, None
    date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    nm = HYOGO_NAME_RE.search(page)
    label = strip(nm.group(1).split("<p")[0]) if nm else ""
    venue = next((v for v in ("西脇", "姫路", "園田") if v in label), "")
    # 「天候：晴　馬場状態：良」= コロンも区切りも全角。norm() を通してから読む
    wm = re.search(r"天候:\s*(\S+)\s+馬場状態:\s*(\S+)",
                   norm(strip(nm.group(1)) if nm else strip(page)))
    weather = wm.group(1) if wm else None
    going = wm.group(2) if wm else None
    return date, (venue or label), weather, going


def hyogo_day(detail_id):
    page = get(f"https://www.sonoda-himeji.jp/data/ability/detail/{detail_id}")
    if "404 Not Found" in page[:1000]:     # 未使用の id は 200 で 404 ページが返る
        return None
    date, venue, weather, going = hyogo_head(page)
    if not date:
        return None
    video = None
    vm = re.search(r'href="(https://www\.youtube\.com/playlist[^"]+)"', page)
    if vm:
        video = H.unescape(vm.group(1))
    races, no = [], 0
    for tbl in tables_of(page):
        rws = rows_of(tbl)
        hi, keys = header_at(rws)
        if hi < 0:
            continue
        # ヘッダの上の1セル行が区分名(ゲート検査/能力検査/発走検査/自主参加)
        kind = cell(rws[0][0]) if hi > 0 and len(rws[0]) == 1 and rws[0] else ""
        groups = {}
        for row, dist in body_rows(rws, hi, keys):
            groups.setdefault(dist, []).append(row)
        for dist, rows in groups.items():
            no += 1
            race = {"no": no, "rows": rows}
            if kind:
                race["kind"] = kind
            if dist:
                race["dist"] = dist
            races.append(race)
    if not races:
        return None
    day = {"date": date, "venue": venue, "races": races, "src_id": detail_id}
    if video:
        day["video"] = video
    if weather:
        day["weather"], day["going"] = weather, going
    return day


def collect_hyogo(existing_ids, backfill):
    idx = get(HYOGO_LIST)
    ids = sorted({int(n) for n in re.findall(r"ability/detail/(\d+)", idx)})
    if backfill and ids:
        ids = list(range(1, max(ids) + 1))
    days, miss, gone = [], 0, 0
    for i in ids:
        if not backfill and i in existing_ids:
            continue
        try:
            day = hyogo_day(i)
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  兵庫 detail/{i} HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  兵庫 detail/{i} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        if day:
            days.append(day)
            log(f"  兵庫 detail/{i} {day['date']} {day['venue']} "
                f"{sum(len(r['rows']) for r in day['races'])}頭/{len(day['races'])}組"
                + ("(映像あり)" if day.get("video") else ""))
        else:
            gone += 1
    # §33.7-1 day.video を「その日の1本」に差し替える(元のプレイリストは day.playlist に残す)
    vids = hyogo_videos() if days else {}
    hit = 0
    for day in days:
        vid = vids.get((day["date"], day.get("venue", "")))
        if not vid:
            if vids:
                log(f"  兵庫 {day['date']} {day.get('venue')} に合う動画がプレイリストに無い"
                    f"(プレイリストのまま)")
            continue
        if day.get("video"):
            day["playlist"] = day["video"]
        day["video"] = f"https://www.youtube.com/watch?v={vid}"
        hit += 1
    log(f"  兵庫: 試した id {len(ids)} 件 / 取得できた {len(days)} / 中身なし {gone} / 取得失敗 {miss}"
        f" / 日ごとの映像 {hit}日")
    return days


# ---------------------------------------------------------------- 佐賀

SAGA_BASE = "https://www.sagakeiba.net"
SAGA_INDEX = SAGA_BASE + "/raceinfo/exam/"
# 1ページ = 1回の能力検査(examYYYYNN = 年度 + その年度の回次)。ページ上部のタブに
# 同じ年度の全回、下の「前年」リンクで1つ前の年度へ行ける(遡れるのは2020年度まで。2026-08-26 実測)。
SAGA_TAB_RE = re.compile(r'href="(?:' + re.escape(SAGA_BASE) + r')?(/raceinfo/exam/(exam\d{6})/)"')
SAGA_PREV_RE = re.compile(r'p-cBlock__hLink[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>\s*前年')
SAGA_TITLE_RE = re.compile(r'p-cBlock__title[^>]*>(.*?)</h2>', re.S)
SAGA_TXT_RE = re.compile(r'p-cBlock__txt[^>]*>(.*?)</p>', re.S)
# 「天候馬場（晴・良）」。括弧も中黒も全角なので norm() の後に当てる。
SAGA_WX_RE = re.compile(r"天候馬場\s*\(\s*([^・)]+?)\s*・\s*([^)]+?)\s*\)")
SAGA_RNO_RE = re.compile(r"第\s*(\d+)\s*競走")
# 「サラ系　１，３００m　（引付時刻　９：２０　）」/「サラ系2歳　９００m」
# 歳の数字を距離と取り違えないよう、齢は別の組にして先に食わせる。
SAGA_COND_RE = re.compile(r"サラ系\s*(\d+歳)?\s*([\d,]+)\s*m")
SAGA_REST = SAGA_BASE + "/wp-json/wp/v2/exam?per_page=100&_fields=date,slug&page={}"


def saga_pages(backfill):
    """年度ページ(examYYYYNN → URL)。差分は今年度+前年度だけ、--backfill は「前年」を辿って全部。"""
    out, url, seen = {}, SAGA_INDEX, set()
    while url and url not in seen:
        seen.add(url)
        page = get(url)
        for path, slug in SAGA_TAB_RE.findall(page):
            out.setdefault(slug, SAGA_BASE + path)
        if not backfill and len(seen) >= 2:
            break
        m = SAGA_PREV_RE.search(page)
        if not m:
            break
        url = SAGA_BASE + m.group(1) if m.group(1).startswith("/") else m.group(1)
    return dict(sorted(out.items()))


def saga_post_dates():
    """見出しに日付が無い/重複しているページの逃げ道。WordPress の公開日は だいたい 実施日と同じ
    (2026-08-26 実測 146ページ: 一致122・ずれ22・見出しに日付が無い2。ずれ22のうち17は
    2020年度ぶんの一括移行、残り5は1〜8日のずれ)。当てにした日は date_src="post" を付けて残す。"""
    out = {}
    for pg in (1, 2, 3):
        try:
            rows = json.loads(get(SAGA_REST.format(pg)))
        except Exception:
            break
        if not rows:
            break
        for r in rows:
            out[r["slug"]] = r["date"][:10]
        if len(rows) < 100:
            break
    return out


def saga_day(slug, page, drop):
    """1ページ = 1日。date が読めないことがあるので日付は None のまま返し、呼び側で埋める。"""
    page = COMMENT_RE.sub("", page)          # 古い映像リンクがコメントアウトで残っている
    i, j = page.find("<article"), page.find("</article>")
    art = page[i:j] if 0 <= i < j else page
    tm = SAGA_TITLE_RE.search(art)
    date = era_date(norm(strip(tm.group(1)))) if tm else None
    races = []
    for chunk in art.split('class="p-cBlock__box"')[1:]:
        hm = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.S)
        label = norm(strip(hm.group(1))) if hm else ""
        tb = TABLE_RE.search(chunk)
        if not tb:
            drop.append(f"佐賀 {slug} 表の無い区分「{label}」")     # 「実施なし」の回
            continue
        rws = rows_of(tb.group(0), br="\n")   # 父馬名<br>母馬名 を割るため改行を残す
        hi, keys = header_at(rws)
        if hi < 0:
            drop.append(f"佐賀 {slug}「{label}」見出し行が読めない")
            continue
        rows = []
        for row, _ in body_rows(rws, hi, keys):
            if row["name"].startswith("※"):   # ※ = 新規馬。馬名から外して旗にする
                row["name"] = row["name"].lstrip("※").strip()
                row["new"] = 1
            rows.append(row)
        if not rows:
            drop.append(f"佐賀 {slug}「{label}」中身が空")
            continue
        rno = SAGA_RNO_RE.search(label)
        race = {"no": int(rno.group(1)) if rno else len(races) + 1, "rows": rows}
        for pm in SAGA_TXT_RE.finditer(chunk):
            cm = SAGA_COND_RE.search(norm(strip(pm.group(1))))
            if not cm:
                continue                       # 「※印は新規馬」等は条件行ではない
            race["dist"] = int(cm.group(2).replace(",", ""))
            if cm.group(1):
                race["kind"] = cm.group(1)     # 「サラ系2歳」の2歳ぶん
            break
        races.append(race)
    if not races:
        return None
    day = {"date": date, "venue": "佐賀", "races": races, "src_id": slug}
    wm = SAGA_WX_RE.search(norm(strip(art)))
    if wm:
        day["weather"], day["going"] = wm.group(1), wm.group(2)
    ym = YT_RE.search(art)
    if ym:
        day["video"] = "https://www.youtube.com/watch?v=" + ym.group(1)
    return day


def collect_saga(existing, backfill):
    pages = saga_pages(backfill)
    days, drop, miss, empty = [], [], 0, 0
    for slug, url in pages.items():
        if not backfill and slug in existing:
            continue
        try:
            day = saga_day(slug, get(url), drop)
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  佐賀 {slug} HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  佐賀 {slug} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        if not day:
            empty += 1
            continue
        days.append(day)
        log(f"  佐賀 {slug} {day['date']} {sum(len(r['rows']) for r in day['races'])}頭/"
            f"{len(day['races'])}R" + ("(映像あり)" if day.get("video") else ""))
    # 日付の穴と重複を公開日で埋める(見出しの日付は主催者の書き間違いがある)
    fix, used = [], set()
    for d in days:
        if not d["date"]:
            fix.append((d, "見出しに日付が無い"))
        elif d["date"] in used:
            fix.append((d, f"見出しの日付 {d['date']} が重複"))
        else:
            used.add(d["date"])
    if fix:
        posts = saga_post_dates()
        for d, why in fix:
            p = posts.get(d["src_id"])
            if p and p not in used:
                log(f"  佐賀 {d['src_id']} {why} → 公開日 {p} を使う")
                d["date"], d["date_src"] = p, "post"
                used.add(p)
            else:
                drop.append(f"佐賀 {d['src_id']} {why}・公開日でも決められない(捨てる)")
        days = [d for d in days if d["date"]]
    for line in drop:
        log("  " + line)
    log(f"  佐賀: 年度ページ {len(pages)} 件 / 取得できた {len(days)} / 表なし {empty} / 取得失敗 {miss}")
    return days


# ---------------------------------------------------------------- ばんえい十勝(帯広)

BANEI = "https://banei-keiba.or.jp/"
# 記事 id を総当たりしないための入口 = お知らせのキーワード検索(1ページ24件・no は0始まり)。
# 成績の表が入っているのは「【速報】令和N年度第M回能力検査」の記事だけで、
# 「…能力検査 結果」の記事は要約と PDF リンクしか無い(2026-08-26 実測)。
BANEI_SEARCH = BANEI + "tp_list.php?wt=keyword&wv=%E8%83%BD%E5%8A%9B%E6%A4%9C%E6%9F%BB&ispost=1"
BANEI_ART_RE = re.compile(r'<article>\s*<a href="([^"]+)".*?<time>([^<]*)</time>.*?<h1>(.*?)</h1>', re.S)
BANEI_ID_RE = re.compile(r"tp_detail\.php\?id=(\d+)")
# 実施日は公式の「能力検査実施概要(YYYY年度)」表が正本。記事本文の日付は前回の使い回しがある
# (2026-08-26 実測: id=10546 の本文は「6/5」だが令和8年度第6回の実施日は 6/19)。
BANEI_AT = BANEI + "race_program.php?c=at&aty={}"
BANEI_KAI_RE = re.compile(r"(令和|平成)\s*(元|\d+)\s*年度\s*第\s*(\d+)\s*回")
BANEI_RNO_RE = re.compile(r"第\s*(\d+)\s*競走")
BANEI_MOIST_RE = re.compile(r"馬場水分\s*([\d.]+)")
BANEI_WX_RE = re.compile(r"天候\s*([^\s馬予0-9]+)")
BANEI_BASE_RE = re.compile(r"予定合格基準タイム\s*([\d:.]+)")
BANEI_STATUS = {"中止", "取消", "除外", "失格"}


def banei_index():
    """検索の全ページから 能力検査 の記事(id・投稿日・題)を拾う。
    no がページ数を超えると先頭に巻き戻るので、新しい id が出なくなったら止める。"""
    out, seen = [], set()
    for no in range(0, 60):
        page = get(BANEI_SEARCH + (f"&no={no}" if no else ""), tries=3)
        fresh = 0
        for href, when, title in BANEI_ART_RE.findall(page):
            m = BANEI_ID_RE.search(H.unescape(href))
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            fresh += 1
            out.append((int(m.group(1)), when.strip(), norm(strip(title))))
        if not fresh:
            break
    return out


_BANEI_AT = {}


def banei_at(year):
    """公式「能力検査実施概要(YYYY年度)」→ ({回次: (実施日, 競馬場, 成績PDF)}, 1つ前の年度)。
    ⚠実施日に年が書いていないので年度の数字をそのまま使うが、回次は4月〜10月にしか無いので
    年をまたがない(2012〜2026年度の全表で実測)。同じ年度を2回取りに行かないよう覚えておく。"""
    if year in _BANEI_AT:
        return _BANEI_AT[year]
    page = get(BANEI_AT.format(year), tries=3)
    i = page.rfind("能力検査実施概要")       # 先頭のはタブの見出しなので後ろのを使う
    tb = TABLE_RE.search(page[i:]) if i > 0 else None
    years = [int(x) for x in re.findall(r"aty=(\d{4})", page)]
    prev = max([y for y in years if y < year], default=None)
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(0), re.S) if tb else []:
        cells = [strip(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        m = re.match(r"第\s*(\d+)\s*回", norm(cells[0])) if cells else None
        if not m:
            continue
        d = re.search(r"(\d+)\s*月\s*(\d+)\s*日", norm(" ".join(cells[1:3])))
        if not d:
            continue
        # 「成績」の欄の result.pdf。中止になった回はリンクが無い(2026-08-26 実測: 令7-2/3)
        pm = re.search(r'href="([^"]*result\.pdf)"', tr)
        url = None
        if pm:
            url = pm.group(1) if pm.group(1).startswith("http") else BANEI + pm.group(1).lstrip("/")
        out[int(m.group(1))] = (f"{year}-{int(d.group(1)):02d}-{int(d.group(2)):02d}",
                                cells[2].strip() if len(cells) > 2 else "", url)
    _BANEI_AT[year] = (out, prev)
    return _BANEI_AT[year]


def banei_dates(year):
    """公式「能力検査実施概要(YYYY年度)」から 回次 → (実施日, 競馬場)。"""
    rows, _prev = banei_at(year)
    return {k: (v[0], v[1]) for k, v in rows.items()}


def banei_day(page, date, venue, src_id, num, drop):
    i = page.find('class="atl_txt')
    j = page.find("</article>", i)
    art = page[i:j] if 0 <= i < j else page
    races, pos = [], 0
    for tm in TABLE_RE.finditer(art):
        head = norm(strip(art[pos:tm.start()]))   # 「第1競走成績 馬場水分0.8% 天候 曇 予定合格基準タイム04:02.0」
        pos = tm.end()
        rws = rows_of(tm.group(0))
        hi, keys = header_at(rws)
        if hi < 0 or "time" not in keys:
            continue                              # 「第1R|第2R…」の目次表など
        rows = []
        for row, _ in body_rows(rws, hi, keys):
            for k in ("jockey", "trainer"):
                if k in row:
                    row[k] = row[k].replace(" ", "")   # 「菊 池」= 2文字名の字送り
            for k in ("time", "fin"):
                if row.get(k) in BANEI_STATUS:         # 中止/取消/除外/失格 はタイムではない
                    row["status"] = row.pop(k)
            rows.append(row)
        if not rows:
            drop.append(f"ばんえい id={num} 中身の無い表")
            continue
        found = list(BANEI_RNO_RE.finditer(head))
        race = {"no": int(found[-1].group(1)) if found else len(races) + 1, "rows": rows}
        for key, rx in (("weather", BANEI_WX_RE), ("moisture", BANEI_MOIST_RE),
                        ("base", BANEI_BASE_RE)):
            m = rx.search(head)
            if m:
                race[key] = m.group(1)
        races.append(race)
    if not races:
        return None
    day = {"date": date, "venue": venue, "races": races, "src_id": src_id, "src": num}
    vids = []
    for v in YT_RE.findall(art):
        u = "https://www.youtube.com/watch?v=" + v
        if u not in vids:
            vids.append(u)
    if vids:
        day["video"] = vids[0]
        if len(vids) > 1:
            day["videos"] = vids                  # ライブとアーカイブの2本立てのことがある
    return day


# §32e 速報の無い回は 公式「能力検査実施概要」の『成績』リンク(result.pdf)から取る。
# ⛔設計は「【速報】の無い『…結果』記事に result.pdf のリンクがある」としていたが、実測では
# 2018〜2019年度の一部の記事にしかリンクが無く、新しい記事は実施概要ページを指すだけだった。
# 実施概要の表そのものが全回ぶんの成績PDFを持っている(2012〜2026年度=158回・うち156回にPDF)ので
# お知らせ検索を通さずここから取る。表は1ページに何レースも横に並び、pdfplumber が返す順番は
# 左上から右下ではない(3ページの回で 1R→4R→2R の順に出た)ので、番号は必ず表の上の見出しから取る。
BANEI_PDF_RNO_RE = re.compile(r"第\s*(\d+)\s*競走")
BANEI_PDF_MOIST_RE = re.compile(r"水分\s*([\d.]+)")
BANEI_PDF_HEAD_RE = re.compile(r"頭数\s*(\d+)")
BANEI_PDF_KIND_RE = re.compile(r"競走\s*(.*?)\s*頭数")
BANEI_ENTRY_RE = re.compile(r"申込頭数(.*?)[)）]", re.S)


def banei_pdf(data, date, venue, src_id, url, drop):
    """成績PDF → 1日ぶん。表の見出し(第N競走 2歳 頭数9 水分1.7%)は表のすぐ上・同じ横幅にある
    ので、表の枠の真上だけを切り出して読む(横に並ぶ別のレースの見出しを拾わないため)。"""
    pdfplumber = pdf_lib()
    races, want, text = [], 0, ""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text += norm(page.extract_text() or "") + "\n"
            for tbl in page.find_tables():
                x0, top, x1, _bot = tbl.bbox
                # ⚠見出しの行が表の枠の「中」に入ってしまう回がある(実測 2012年度第1回の18競走は
                # 枠の上端 560 に対して見出しが 572)。上下に少し広げて切り、いちばん下の
                # 「第N競走」を採る(横は表の幅で切るので隣の列の見出しは入らない)。
                area = (max(0, x0 - 6), max(0, top - 42),
                        min(page.width, x1 + 6), min(page.height, top + 18))
                try:
                    crop = norm(page.crop(area).extract_text() or "")
                except Exception:
                    crop = ""
                found = list(BANEI_PDF_RNO_RE.finditer(crop))
                head = crop[found[-1].start():] if found else ""
                rows = tbl.extract()
                hi, keys = pdf_head(rows)
                if hi < 0 or "time" not in keys:
                    continue
                got = [r for r, _ in pdf_body(rows, hi, keys)]
                for row in got:
                    for k in ("time", "fin"):      # 中止/取消/除外/失格 はタイムでも着順でもない
                        if row.get(k) in BANEI_STATUS:
                            row["status"] = row.pop(k)
                if not got:
                    continue
                if not head:
                    drop.append(f"ばんえい {src_id} レース番号の読めない表(捨てる {len(got)}頭)")
                    continue
                race = {"no": int(BANEI_PDF_RNO_RE.match(head).group(1)), "rows": got}
                mk = BANEI_PDF_KIND_RE.search(head)
                if mk and mk.group(1).strip():
                    race["kind"] = mk.group(1).replace(" ", "")
                mm = BANEI_PDF_MOIST_RE.search(head)
                if mm:
                    race["moisture"] = mm.group(1)
                mh = BANEI_PDF_HEAD_RE.search(head)
                if mh:
                    want += int(mh.group(1))
                races.append(race)
    if not races:
        return None
    nos = [r["no"] for r in races]
    if len(set(nos)) != len(nos):
        drop.append(f"ばんえい {src_id} 同じレース番号の表が2つ {sorted(nos)}(そのまま入れる)")
    races.sort(key=lambda r: r["no"])
    got = sum(len(r["rows"]) for r in races)
    # 独立検証 = 表の中身ではなく 見出しの頭数・PDF題の申込頭数・PDF題の実施日 と突き合わせる。
    # ⚠レースの見出しの「頭数」は出走した数なので、発走前に取り消した馬は入っていない
    # (中止=走り出してから止めた馬は入っている。2026-05-08 で1レースずつ確かめた)
    off = sum(1 for r in races for row in r["rows"] if row.get("status") in ("取消", "除外"))
    if want and want != got - off:
        drop.append(f"ばんえい {src_id} 見出しの出走頭数 計{want} と 表の行 {got}-取消 {off} "
                    f"が合わない")
    em = BANEI_ENTRY_RE.search(text)
    if em:
        tot = sum(int(x) for x in re.findall(r"(\d+)\s*頭", em.group(1)))
        if tot and tot != got:
            drop.append(f"ばんえい {src_id} 申込頭数 {tot} と 表の行 {got} が合わない")
    dm = re.search(r"(\d+)\s*月\s*(\d+)\s*日", text)
    if dm and f"{int(dm.group(1)):02d}-{int(dm.group(2)):02d}" != date[5:]:
        drop.append(f"ばんえい {src_id} 実施概要は {date} だが PDF の題は "
                    f"{dm.group(1)}/{dm.group(2)}(実施概要を採る)")
    return {"date": date, "venue": venue or "帯広", "races": races,
            "src_id": src_id, "src_pdf": url}


def banei_years(backfill):
    """成績PDFを見に行く年度。差分は今年度と前年度だけ・--backfill は「前年」のリンクを
    たどれるだけ遡る(2026-08-26 実測: 2012年度まで)。"""
    now = dt.datetime.now(JST).date()
    year, out = now.year - (0 if now.month >= 4 else 1), []
    while year is not None and year not in out:
        out.append(year)
        if not backfill and len(out) >= 2:
            return out
        try:
            _rows, year = banei_at(year)
        except Exception as e:
            log(f"  ばんえい {year}年度 実施概要が読めない {type(e).__name__}: {str(e)[:80]}")
            break
    return out


def banei_from_pdf(existing, backfill, done, drop):
    """速報で取れなかった回を成績PDFで埋める。⚠速報が先(done に入っている回は開かない)。"""
    if not pdf_lib():
        log("  ばんえい: pdfplumber が入っていないので成績PDFは飛ばす(cloud/requirements.txt)")
        return []
    days, miss, none = [], 0, 0
    for year in banei_years(backfill):
        try:
            rows, _prev = banei_at(year)
        except Exception as e:
            log(f"  ばんえい {year}年度 実施概要が読めない {type(e).__name__}: {str(e)[:80]}")
            continue
        for kai in sorted(rows):
            date, venue, url = rows[kai]
            src_id = f"{year}-{kai}"
            if src_id in done or (not backfill and src_id in existing):
                continue
            if not url:
                none += 1
                drop.append(f"ばんえい {src_id} {date} 実施概要に成績PDFのリンクが無い(中止?)")
                continue
            try:
                data, _lm = get_bin(url, tries=3)
                day = banei_pdf(data, date, venue, src_id, url, drop)
            except urllib.error.HTTPError as e:
                miss += 1
                log(f"  ばんえい {src_id} 成績PDF HTTP {e.code}(無視)")
                continue
            except Exception as e:
                miss += 1
                log(f"  ばんえい {src_id} 成績PDF が読めない {type(e).__name__}: {str(e)[:100]}")
                continue
            if not day:
                none += 1
                drop.append(f"ばんえい {src_id} {date} 成績PDF に表が無い(字の無い PDF?)")
                continue
            done.add(src_id)
            days.append(day)
            log(f"  ばんえい {src_id} {date} {sum(len(r['rows']) for r in day['races'])}頭/"
                f"{len(day['races'])}R(成績PDF)")
    log(f"  ばんえい: 成績PDF から {len(days)} 回 / 中身なし {none} / 取得失敗 {miss}")
    return days


def collect_banei(existing, backfill):
    items = banei_index()
    cand = []
    for num, _when, title in items:
        m = BANEI_KAI_RE.search(title) if "能力検査" in title else None
        if not m:
            continue                              # 写真・お知らせ・追加実施の案内など
        fy = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
        cand.append((fy, int(m.group(3)), 0 if "速報" in title else 1, num, title))
    cand.sort()
    log(f"  ばんえい: 検索に出た記事 {len(items)} 件 / 回次の読めた能検記事 {len(cand)} 件")
    dates, days, drop, done, miss, empty = {}, [], [], set(), 0, 0
    for fy, kai, _pref, num, title in cand:
        src_id = f"{fy}-{kai}"
        if src_id in done or (not backfill and src_id in existing):
            continue
        if fy not in dates:
            try:
                dates[fy] = banei_dates(fy)
            except Exception as e:
                dates[fy] = {}
                log(f"  ばんえい {fy}年度 実施概要が読めない {type(e).__name__}: {str(e)[:80]}")
        when, venue = dates[fy].get(kai, (None, ""))
        if not when:
            drop.append(f"ばんえい {src_id} 実施日が公式表に無い({title})")
            continue
        try:
            day = banei_day(get(f"{BANEI}tp_detail.php?id={num}", tries=3), when, venue or "帯広",
                            src_id, num, drop)
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  ばんえい id={num} HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  ばんえい id={num} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        if not day:
            empty += 1                            # 「…結果」記事は表が無い(PDF だけ)
            continue
        done.add(src_id)
        days.append(day)
        log(f"  ばんえい {src_id} {when} {sum(len(r['rows']) for r in day['races'])}頭/"
            f"{len(day['races'])}R" + ("(映像あり)" if day.get("video") else ""))
    log(f"  ばんえい: 速報から {len(days)} 回 / 表なし記事 {empty} / 取得失敗 {miss}")
    days += banei_from_pdf(existing, backfill, done, drop)
    for line in drop:
        log("  " + line)
    log(f"  ばんえい: 取得できた {len(days)} 回")
    return days


# ---------------------------------------------------------------- PDF の共通部品(笠松・名古屋・高知)
# この3場は成績が PDF でしか出ない(DESIGN §32c)。どれも機械生成のテキスト PDF なので
# pdfplumber の罫線ベースの表取りがそのまま効く。⚠pdfplumber はここでだけ import する
# (クラウドに入っていなくても既存5源が動くように)。

_PDFLIB = []


def pdf_lib():
    """pdfplumber を1回だけ読み込む。無ければ None を返し、PDF の3場だけあきらめる
    (既存5源はこの関数を通らないので、入っていないクラウドでもそのまま動く)。"""
    if not _PDFLIB:
        try:
            import pdfplumber
            _PDFLIB.append(pdfplumber)
        except ImportError:
            _PDFLIB.append(None)
    return _PDFLIB[0]


def pdf_pages(data):
    """PDF のバイト列 → [(本文, [表])]。本文は norm() 済み。"""
    pdfplumber = pdf_lib()
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            out.append((norm(page.extract_text() or ""), page.extract_tables()))
    return out


def pdf_head(table, extra=None):
    """PDF の表 → (ヘッダ行の位置, 列→キー)。空セルは None で来るので "" に均す。"""
    return header_at([["" if c is None else str(c) for c in row] for row in table], extra)


def pdf_body(table, hi, keys, extra=None, join=None, expand=None):
    """ヘッダの下のデータ行 → [(row, cells)]。cells は行の生の並び(レース番号や距離を
    呼び側が col_of で読むため)。
    ⚠結合セル(「1R」が3頭ぶん縦につながっている等)は pdfplumber が None で返すので、
    レース番号・距離・時刻の列だけ上の行から埋める。馬名や着順は埋めない(前の馬が複製されるため)。
    ⚠PDF は長い名前をセルの中で折り返す(「クツワホームランの2024\\n（べラジオホームラン）」)。
    表示は1つの値なので改行は詰める。父母名のように改行が区切りの列は expand で先に割る。"""
    out, frags, carry = [], [], {}
    for row in table[hi + 1:]:
        cells = ["" if c is None else str(c) for c in row]
        for i, key in enumerate(keys):
            if key not in ROW_SKIP or i >= len(cells):
                continue
            if cells[i].strip():
                carry[i] = cells[i]
            else:
                cells[i] = carry.get(i, "")
        flat = [c.replace("\n", "") for c in cells]
        if len(flat) < 3 or not any(cell(c) for c in flat):
            continue
        if sum(1 for c in flat if key_of(c, extra)) >= 3:
            continue                       # 途中に挟まる見出しの繰り返し
        cs, ks = expand(cells, keys) if expand else (flat, keys)
        row_d = row_of(cs, ks, join)
        if row_d.get("name"):
            out.append((row_d, flat))
        elif row_d.get("umaban"):
            # 馬番のある行は「その馬の枠」なので上下の馬の断片ではない。名古屋は出走頭数より
            # 枠の数が多く空の枠が並ぶ(黙って捨てる)。名前の無い枠に備考だけ入っていることも
            # あるので(「除外※枠入不良」)、そこは何を捨てたか言う。
            if set(row_d) - {"umaban"}:
                log(f"  馬名の無い行を捨てた {row_d}")
        elif row_d:
            frags.append((len(out), row_d))     # 馬名も馬番も無い行 = 上か下の馬の断片
    put_frags(out, frags)
    for row_d, _ in out:
        take_status(row_d)
    return out


TIME_RE = re.compile(r"^\d+[.:]\d+(?:[.:]\d+)?$")


def take_status(row):
    """タイムの欄に「取消」「2レースに変更」と書いてあることがある(名古屋の実測)。
    タイムでない字は status へ移す(ばんえいの 中止・取消 と同じ扱い)。"""
    t = row.get("time")
    if t and not TIME_RE.match(t):
        row["status"] = row.pop("time")


SEX_RE = re.compile(r"^[牡牝セ騸ン]+$")


def frag_fits(row, key, val):
    """その馬の key にこの断片が入る余地があるか。性齢だけは「性」と「齢」の2つでできているので、
    片方しか入っていなければもう片方は入る。"""
    cur = row.get(key, "")
    if not cur:
        return True
    if key != "sexage":
        return False
    if SEX_RE.match(val):
        return not re.search(r"[牡牝セ騸]", cur)
    return not re.search(r"\d", cur)


def put_frags(out, frags):
    """背の高い行を pdfplumber が2行に割ることがある(笠松の出走取消馬)。断片は上の馬のことも
    下の馬のこともあるので(実測どちらもある)、⛔「どちらか片方にしか入らない」ときだけ足す。
    両方に入る/どちらにも入らないときは決められないので足さずに残す(誤った性齢を出さないため)。"""
    for at, frag in frags:
        prev = out[at - 1][0] if at > 0 else None
        nxt = out[at][0] if at < len(out) else None
        for key, val in frag.items():
            to_prev = prev is not None and frag_fits(prev, key, val)
            to_next = nxt is not None and frag_fits(nxt, key, val)
            if to_prev == to_next:
                log(f"  PDF の折り返し行 {key}={val} がどの馬のものか決められない(捨てる)")
            elif to_prev:
                prev[key] = prev.get(key, "") + val
            else:
                nxt[key] = val + nxt.get(key, "")


def base_times(table):
    """「階級別合格タイム一覧」→ ({階級: タイム}, {階級: 距離})。
    笠松は見出しつき3列・名古屋は見出しの無い3列。どちらも「以内」が入っている列がタイム。"""
    times, dists = {}, {}
    for row in table:
        cells = [cell("" if c is None else str(c)) for c in row]
        if len(cells) < 2 or not cells[0]:
            continue
        tm = next((c for c in cells[1:] if "以内" in c), "")
        if not tm:
            continue                       # 見出し行(階級/距離(m)/合格タイム)
        times[cells[0]] = tm.replace("以内", "").strip()
        dm = next((c for c in cells[1:] if re.fullmatch(r"[\d,]+\s*m?", c)), "")
        if dm:
            dists[cells[0]] = int(re.sub(r"[^\d]", "", dm))
    return times, dists


def put_base(day, times, dists):
    """階級別の合格タイム表を日に付ける(回ごとに変わるのでレースではなく日に持つ)。"""
    if times:
        day["base_times"] = times
    if dists:
        day["base_dists"] = dists


def race_no(text, fallback):
    m = re.search(r"(\d+)\s*R", text) or re.match(r"\s*(\d+)", text)
    return int(m.group(1)) if m else fallback


def hhmm(text):
    m = re.search(r"(\d{1,2}:\d{2})", text)
    return m.group(1) if m else ""


def dist_num(text):
    m = re.search(r"[\d,]+", text)
    return int(m.group(0).replace(",", "")) if m else None


def group_races(body, keys):
    """(row, cells) の並び → レースの配列。レース番号の列(grp)が変わったら次のレース。
    番号の列が無い表は全部で1レース。

    §117f ⚠**番号が同じでも距離が変わったら別のレース**にする(`no` は同じまま・`dist` だけ違う)。
      2026-08-28 笠松の公式 PDF は「1R 800m 2頭(取消)」と「1R 1,400m 1頭(除外)」を同じ 1R と書いており、
      番号だけで束ねると 1 レース 3 頭・距離は先に出た 800m だけが残って、1,400m を走った馬が
      800m のレースの中に見える(= 情報が潰れる)。⛔番号の付け直しはしない(1R が 2 つ並ぶ)。"""
    races, grps = [], 0
    for row, cells in body:
        grp = col_of(cells, keys, "grp")
        dist = dist_num(col_of(cells, keys, "dist"))
        last = races[-1] if races else None
        new_grp = last is None or last["_grp"] != grp
        # ⚠先頭の行に距離が無い表(_dist が None)では割らない= 今までどおり
        new_dist = (not new_grp) and dist is not None and last["_dist"] is not None and dist != last["_dist"]
        if new_grp or new_dist:
            if new_grp:
                grps += 1
            race = {"_grp": grp, "_dist": dist, "rows": [],
                    "no": race_no(grp, grps) if new_grp else last["no"]}
            if dist:
                race["dist"] = dist
            start = hhmm(col_of(cells, keys, "start")) or hhmm(grp)
            if start:
                race["start"] = start
            races.append(race)
        races[-1]["rows"].append(row)
    for race in races:
        race.pop("_grp", None)
        race.pop("_dist", None)
    return races


# ---------------------------------------------------------------- 笠松
# https://www.kasamatsu-keiba.com/ability に回ごとの「能力審査番組表及び成績表」PDF。
# ⛔索引は1年ぶんしか出ない(2026-08-26 実測: 令和7年度第9回=2025-09-12 が最古)。PDF の名前は
# アップロード時刻+乱数なので推測できず、/resources/pdfs/ability/ のディレクトリ一覧は 403。
# = 遡れるのは索引に出ている回まで。取りこぼすと戻れないので毎月動かすこと。
KASA = "https://www.kasamatsu-keiba.com"
KASA_INDEX = KASA + "/ability"
# 最新の回だけ class が「 l_race_sec_top」(頭に空白・末尾に _top)なので前後を緩く見る
KASA_ITEM_RE = re.compile(r'class="[^"]*l_race_sec[^"]*"[^>]*>(.*?)'
                          r'(?=class="[^"]*l_race_sec|<footer|</main)', re.S)
KASA_TITLE_RE = re.compile(r'class="race_title"[^>]*>(.*?)</div>', re.S)
# 「実施日 令和8年8月14日 天 候 くもり 審査頭数 4 頭」「馬場状態 稍重」。字の間に空白が入る。
KASA_DATE_RE = re.compile(r"実\s*施\s*日\s*(.{0,24}?日)")
KASA_WX_RE = re.compile(r"天\s*候\s+(.+?)\s+(?:審査頭数|合格頭数|不合格頭数|馬場状態)")
KASA_GOING_RE = re.compile(r"馬\s*場\s*状\s*態\s+(\S+)")
# 笠松だけの列。「厩舎」は円城寺きゅう舎などの略号で調教師ではない(調教師の列は別にある)。
KASA_COLS = {"番号(発走時刻)": "grp", "距離(m)": "dist", "階級": "cls", "厩舎": "stable",
             "合否(不合格理由)": "ok", "受検理由": "note"}
KASA_JOIN = {"note": "・"}


def kasa_expand(cells, keys):
    """合否のセルは「不合格\\n（タイムオーバー）」の2段。理由は備考へ回す。"""
    cs, ks = [], []
    for text, key in zip(cells, keys):
        if key == "ok":
            parts = [p.strip(" ()") for p in norm(text).split("\n")]
            parts = [p for p in parts if p]
            cs.append(parts[0] if parts else "")
            ks.append("ok")
            if len(parts) > 1:
                cs.append("・".join(parts[1:]))
                ks.append("note")
            continue
        cs.append(text.replace("\n", ""))
        ks.append(key)
    return cs, ks


def kasa_pdf(data, src, video, drop):
    """1つの PDF → 日の配列。1ページ=1日で、1つの PDF に前半/後半の2日が入ることがある
    (2026-08-26 実測: 第5回=6/12 と 6/26 が2ページ)。日はページの「実施日」で決める。"""
    days = {}
    for text, tables in pdf_pages(data):
        dm = KASA_DATE_RE.search(text)
        date = era_date(dm.group(1)) if dm else None
        if not date:
            drop.append(f"笠松 {src} 実施日が読めないページ(捨てる)")
            continue
        times, dists, body, keys = {}, {}, [], []
        for table in tables:
            hi, ks = pdf_head(table, KASA_COLS)
            if hi < 0:
                t, d = base_times(table)
                times.update(t)
                dists.update(d)
                continue
            keys = ks
            body += pdf_body(table, hi, ks, KASA_COLS, KASA_JOIN, kasa_expand)
        if not body:
            drop.append(f"笠松 {src} {date} 成績の表が読めない(捨てる)")
            continue
        day = days.get(date)
        if not day:
            day = {"date": date, "venue": "笠松", "races": [], "src_id": src}
            wm = KASA_WX_RE.search(text)
            gm = KASA_GOING_RE.search(text)
            if wm:
                day["weather"] = wm.group(1).strip()
            if gm:
                day["going"] = gm.group(1)
            if video:
                day["video"] = video
            put_base(day, times, dists)
            days[date] = day
        races = group_races(body, keys)
        for race in races:                 # 同じ日が2ページに割れていたら続きの番号にする
            if any(r["no"] == race["no"] for r in day["races"]):
                race["no"] = max(r["no"] for r in day["races"]) + 1
        day["races"] += races
    return list(days.values())


def collect_kasamatsu(existing_dates, backfill):
    if not pdf_lib():
        log("  笠松: pdfplumber が入っていないので飛ばす(cloud/requirements.txt)")
        return []
    idx = get(KASA_INDEX)
    days, drop, miss = [], [], 0
    for chunk in KASA_ITEM_RE.findall(idx):
        pm = re.search(r'href="(/resources/pdfs/[^"]+\.pdf)"', chunk)
        if not pm:
            continue
        tm = KASA_TITLE_RE.search(chunk)
        label = norm(strip(tm.group(1))) if tm else ""
        listed = era_dates(label)
        if not backfill and listed and all(d in existing_dates for d in listed):
            continue                       # 見出しに出ている日が全部そろっている回は開かない
        vm = re.search(r'href="(https://www\.youtube\.com/playlist[^"]+)"', chunk)
        src = pm.group(1).rsplit("/", 1)[-1].split("_")[0]
        try:
            data, _ = get_bin(KASA + pm.group(1))
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  笠松 {label} HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  笠松 {label} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        try:
            got = kasa_pdf(data, src, H.unescape(vm.group(1)) if vm else None, drop)
        except Exception as e:
            miss += 1
            log(f"  笠松 {label} PDF が読めない {type(e).__name__}: {str(e)[:100]}")
            continue
        for day in got:
            days.append(day)
            log(f"  笠松 {day['date']} {sum(len(r['rows']) for r in day['races'])}頭/"
                f"{len(day['races'])}R" + ("(映像あり)" if day.get("video") else ""))
        if not got:
            drop.append(f"笠松 {label} 中身の無い PDF")
    for line in drop:
        log("  " + line)
    log(f"  笠松: 索引の回 {len(KASA_ITEM_RE.findall(idx))} 件 / 取得できた {len(days)} 日 / 取得失敗 {miss}")
    return days


# §117g 笠松の映像。公式の各回に YouTube の**プレイリスト**が貼ってある(2026-09-07 実測: 24日のうち16日)。
# プレイリストはレース単位ではないので画面は R ボタンを作れず、ID の短い回(list=PLd510fzLbHC0 など)は
# 埋め込みの形にもならないので**映像の行がまるごと消えていた**(⛔主催者が出しているものを落としていた)。
# 動画の題に「実施日」と「第N R」が入っているので、それを読んでその日のレースに1本ずつ当てる。
# ⚠題の形は回で違う(実測 30本):「令和8年7月31日 笠松競馬能力審査(第2R)」「2026 03 20 能力審査1R」
#   「令和7年10月24日 笠松競馬 能力審査(1R・未出走馬出走)」「令和8年4月3日 笠松競馬能力審査」(R 無し)。
# ⚠並びは R 順とはかぎらない(実測: 題で R の読めた 26 本のうち 18 本が 2R→1R の降順)。
#   だから**順では当てない**= 題で R が読めた動画だけ付ける。1レースの日で題に R が無いときだけ、
#   その1本をその1レースに当てる(当てる先が1つしかない= 推定にならない)。
# ⚠1つのプレイリストに2日ぶん入っている回がある(第5回= 6/12 と 6/26 の4本)。題の実施日で分ける。
KASA_YT_YMD_RE = re.compile(r"(20\d{2})\s*[-/. ]\s*(\d{1,2})\s*[-/. ]\s*(\d{1,2})")
KASA_YT_R_RE = re.compile(r"(?:第\s*)?(\d+)\s*R|第\s*(\d+)\s*競走")


def kasa_video_key(title):
    """動画の題 → (実施日 or None, レース番号 or None)。⛔読めないものは None のまま(埋めない)。"""
    t = norm(title or "")
    m = ERA_DATE_RE.search(t)
    date = era_of(m) if m else None
    if not date:
        m = KASA_YT_YMD_RE.search(t)       # 「2026 03 20 能力審査1R」= 年月日の字が無い題
        if m:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    rest = (t[:m.start()] + " " + t[m.end():]) if m else t   # 日付の数字を R と読み違えない
    rm = KASA_YT_R_RE.search(rest)
    return date, int(rm.group(1) or rm.group(2)) if rm else None


def kasa_assign(day, items):
    """[(動画ID, 題)] → その日の races[].video。返り値= (付けた本数, 当て方, 断り or None)。"""
    races = [r for r in (day.get("races") or []) if r.get("no") is not None]
    got = [(vid, kasa_video_key(title)) for vid, title in items]
    # 2日ぶん入っているプレイリストは、題の実施日でこの日のぶんだけにする
    if any(k[0] and k[0] != day["date"] for _, k in got):
        got = [x for x in got if x[1][0] == day["date"]]
    if not got or not races:
        return 0, "", f"笠松 {day['date']} プレイリストにこの日の動画が無い(付けない)"
    nos = [no for _, (_, no) in got]
    if all(n is not None for n in nos) and len(set(nos)) == len(nos):
        by = {}
        for r in races:
            by.setdefault(r["no"], []).append(r)
        if any(len(by.get(n) or []) != 1 for n in nos):
            return 0, "", (f"笠松 {day['date']} 題の R {nos} が この日のレース "
                           f"{[r['no'] for r in races]} に1つずつ決まらない(付けない)")
        for vid, (_, no) in got:
            by[no][0]["video"] = "https://www.youtube.com/watch?v=" + vid
        short = (f"・動画 {len(got)}本 / {len(races)}R= 読めたぶんだけ" if len(got) != len(races) else "")
        return len(got), "題", (f"笠松 {day['date']} 題で当てた {sorted(nos)}{short}" if short else None)
    if len(got) == 1 and len(races) == 1:
        races[0]["video"] = "https://www.youtube.com/watch?v=" + got[0][0]
        return 1, "順", None
    return 0, "", (f"笠松 {day['date']} 動画 {len(got)}本 / {len(races)}R で題に R が読めない"
                   f"(並びは R 順とはかぎらないので付けない)")


def kasa_videos(days):
    """day.video がプレイリストの日 → races[].video を付ける。返り値= (付けた日, ログの行)。
    ⛔もう付いている日はプレイリストを開かない(差分)。⛔当てられない日は day.video のまま残す
    (画面は「検査回の映像(外部)」の外リンクにする)。GET はプレイリスト1つにつき1回(間合いは get())。"""
    todo, lines = {}, []
    for day in days:
        url = str(day.get("video") or "")
        if "playlist?list=" not in url:
            continue
        if any(r.get("video") for r in (day.get("races") or [])):
            continue
        todo.setdefault(url, []).append(day)
    n_day, n_race, how = 0, 0, {"題": 0, "順": 0}
    for url, ds in todo.items():
        try:
            items = yt_titles(url + "&hl=ja")
        except Exception as e:
            lines.append(f"笠松 プレイリストが読めない {url[-18:]} {type(e).__name__}: {str(e)[:60]}"
                         f"(その日は今までどおり)")
            continue
        if not items:
            lines.append(f"笠松 プレイリストに動画が無い {url[-18:]}(その日は今までどおり)")
            continue
        for day in sorted(ds, key=lambda d: d["date"]):
            n, mode, note = kasa_assign(day, items)
            if note:
                lines.append(note)
            if n:
                n_day += 1
                n_race += n
                how[mode] = how.get(mode, 0) + 1
    if todo:
        lines.append(f"笠松: 映像 プレイリスト {len(todo)} 件 → {n_day} 日 {n_race} レースに付けた"
                     f"(題で {how['題']} 日 / 1レースの日の1本 {how['順']} 日)")
    return n_day, lines


# ---------------------------------------------------------------- 名古屋(愛知県馬主会)
# http://aichi-owners.jp/pdf/nr{和暦}-{回}.pdf。索引(トップページ)は1年半ぶんしか出ないが、
# 名前が規則的なので古い回も URL で生きている(2026-08-26 実測: nr6-1〜26 は全部 200・nr5-* は 404)。
NAGOYA = "http://aichi-owners.jp/"
NAGOYA_PDF = NAGOYA + "pdf/nr{}-{}{}.pdf"
NAGOYA_LINK_RE = re.compile(r"pdf/nr(\d+)-(\d+)([a-z]?)\.pdf")
NAGOYA_FIRST_ERA = 6                       # これより前は 404(実測)
# 「実 施 日 ： 8 月 24 日 （月）」= 年が無い。字の間に空白が入るので \s* を挟む。
NAGOYA_DATE_RE = re.compile(r"実\s*施\s*日\s*[:：]?\s*(\d+)\s*月\s*(\d+)\s*日")
NAGOYA_WX_RE = re.compile(r"天\s*候\s*[:：]\s*(\S+)")
NAGOYA_GOING_RE = re.compile(r"馬\s*場\s*状\s*態\s*[:：]\s*(\S+)")
NAGOYA_PLACE_RE = re.compile(r"実\s*施\s*場\s*所\s*[:：]\s*(\S+)")
NAGOYA_COLS = {"レース番号": "grp", "集合時刻": "meet", "発走時刻": "start",
               "クラス": "cls", "騎手名": "jockey", "調教師名": "trainer"}
NAGOYA_JOIN = {"sexage": ""}               # 「性」と「齢」が別の列 → 牝+2 = 牝2


def nagoya_expand(cells, keys):
    """人名は字送りの空白が入る(「丹 羽」「加 藤」)ので詰める(ばんえいと同じ)。
    ⚠乗り替わりの日は1つのセルに2人ぶん入る(実測 2024-07-26「丹 羽\\n加藤利」・備考は騎手変更)。
    詰めると居ない人の名前になるので、行が分かれているところは中黒でつなぐ。"""
    cs, ks = [], []
    for text, key in zip(cells, keys):
        if key in ("jockey", "trainer"):
            parts = [p.replace(" ", "").strip() for p in norm(text).split("\n")]
            cs.append("・".join(p for p in parts if p))
        else:
            cs.append(text.replace("\n", ""))
        ks.append(key)
    return cs, ks


def nagoya_year(fy, month, day, lastmod):
    """PDF に年が無い。年度(fy)から候補を出し、掲載日(Last-Modified)に一番近い年を採る。
    ⚠「年度の初め=4月」ではない: 令和6年度第1回は 2024-03-29 と年度が始まる前に行われている
    (実測。月だけで年度をまたぐ判定をすると1年ずれる)。掲載日が無ければ月で決める。"""
    ref = None
    if lastmod:
        try:
            ref = email.utils.parsedate_to_datetime(lastmod).date()
        except Exception:
            ref = None
    cand = []
    for year in (fy - 1, fy, fy + 1):
        try:
            cand.append(dt.date(year, month, day))
        except ValueError:
            continue
    if not cand:
        return None
    if ref is None:
        want = fy if month >= 4 else fy + 1
        return next((f"{d:%Y-%m-%d}" for d in cand if d.year == want), f"{cand[0]:%Y-%m-%d}")
    return f"{min(cand, key=lambda d: abs((d - ref).days)):%Y-%m-%d}"


def nagoya_pdf(data, lastmod, fy, src, drop, videos=None):
    """1つの PDF = 1日(実測: 全部1ページ)。ページに成績表と合格タイム表が並ぶ。"""
    pages = pdf_pages(data)
    if not pages:
        drop.append(f"名古屋 {src} ページの無い PDF")
        return None
    text = pages[0][0]
    dm = NAGOYA_DATE_RE.search(text)
    if not dm:
        drop.append(f"名古屋 {src} 実施日が読めない(画像だけの PDF?)")
        return None
    date = nagoya_year(fy, int(dm.group(1)), int(dm.group(2)), lastmod)
    if not date:
        drop.append(f"名古屋 {src} 実施日 {dm.group(1)}/{dm.group(2)} が暦に無い")
        return None
    times, dists, body, keys = {}, {}, [], []
    for _text, tables in pages:
        for table in tables:
            hi, ks = pdf_head(table, NAGOYA_COLS)
            if hi < 0:
                t, d = base_times(table)
                times.update(t)
                dists.update(d)
                continue
            keys = ks
            body += pdf_body(table, hi, ks, NAGOYA_COLS, NAGOYA_JOIN, nagoya_expand)
    if not body:
        drop.append(f"名古屋 {src} {date} 成績の表が読めない")
        return None
    pm = NAGOYA_PLACE_RE.search(text)
    day = {"date": date, "venue": (pm.group(1).replace("競馬場", "") if pm else "名古屋"),
           "races": group_races(body, keys), "src_id": src}
    if videos and videos.get(date):        # §117b 公式サイトに埋まっている YouTube(日で合わせる)
        day["video"] = videos[date]
    wm = NAGOYA_WX_RE.search(text)
    gm = NAGOYA_GOING_RE.search(text)
    if wm:
        day["weather"] = wm.group(1)
    if gm:
        day["going"] = gm.group(1)
    put_base(day, times, dists)
    return day


def nagoya_todo(backfill):
    """取りに行く (年度, 回, 枝番) の並び。差分はトップページのリンクだけ、
    --backfill は令和6年度から番号で総当たり(索引に出ていない古い回も生きている)。"""
    try:
        idx = get(NAGOYA)
    except Exception as e:
        log(f"  名古屋: トップページが読めない {type(e).__name__}: {str(e)[:80]}")
        idx = ""
    linked = sorted({(int(a), int(b), c) for a, b, c in NAGOYA_LINK_RE.findall(idx)})
    if not backfill:
        return linked, len(linked)
    now = dt.datetime.now(JST).date()
    last = (now.year - (0 if now.month >= 4 else 1)) - 2018      # 令和の年度
    return None, last                      # 総当たりは collect 側で(404 を見ながら進める)


def collect_nagoya(existing, backfill):
    if not pdf_lib():
        log("  名古屋: pdfplumber が入っていないので飛ばす(cloud/requirements.txt)")
        return []
    todo, last = nagoya_todo(backfill)
    videos = nagoya_videos()               # §117b 能力審査結果ページの埋め込み(日→URL)
    days, drop, miss, gone = [], [], 0, 0

    def take(fy, kai, suf):
        nonlocal miss, gone
        src = f"nr{fy}-{kai}{suf}"
        if not backfill and src in existing:
            return True
        try:
            data, lastmod = get_bin(NAGOYA_PDF.format(fy, kai, suf))
        except urllib.error.HTTPError as e:
            if e.code != 404 or todo is not None:
                # 総当たりの 404 は「その回は無い」だけ。索引が貼っているのに 404 のときは言う
                miss += 1
                log(f"  名古屋 {src} HTTP {e.code}(無視)")
            return False
        except Exception as e:
            miss += 1
            log(f"  名古屋 {src} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            return False
        try:
            day = nagoya_pdf(data, lastmod, 2018 + fy, src, drop, videos)
        except Exception as e:
            miss += 1
            log(f"  名古屋 {src} PDF が読めない {type(e).__name__}: {str(e)[:100]}")
            return True
        if not day:
            gone += 1
            return True
        days.append(day)
        log(f"  名古屋 {src} {day['date']} {sum(len(r['rows']) for r in day['races'])}頭/"
            f"{len(day['races'])}R")
        return True

    if todo is not None:
        for fy, kai, suf in todo:
            take(fy, kai, suf)
    else:
        for fy in range(NAGOYA_FIRST_ERA, last + 1):
            blank = 0
            for kai in range(1, 41):
                hit = take(fy, kai, "")
                if not hit:                # 枝番(nr8-10a / nr8-10b)で出ることがある
                    for suf in ("a", "b", "c"):
                        hit = take(fy, kai, suf) or hit
                blank = 0 if hit else blank + 1
                if blank >= 3:             # 3回続けて無ければその年度は終わり
                    break
    for line in drop:
        log("  " + line)
    log(f"  名古屋: 取得できた {len(days)} 日 / 中身なし {gone} / 取得失敗 {miss}")
    return days


# ---------------------------------------------------------------- 高知
# https://www.keiba.or.jp/?cat=42 の記事ごとに「能力調教試験出馬表」PDF。
# ⚠題は出馬表だが、検査が終わると着順・タイム・合否・基準タイムの入った PDF に差し替わる。
# 検査前に取ると中身が空なので、その日は入れずに次の実行で取り直す。
KOCHI = "https://www.keiba.or.jp/"
KOCHI_CAT = KOCHI + "?cat=42"
KOCHI_POST_RE = re.compile(r'\?p=(\d+)"[^>]*class="entry-title[^>]*>(.*?)</a>', re.S)
# ⛔2020-03-30 より前の PDF は字が埋め込まれていない(図形だけ。2026-08-26 実測:
# upfile/278-1=2020-03-02 まで和字0・280-1=2020-03-30 から読める)。記事自体は2008年まである。
KOCHI_FROM = "2020-03-30"
# 「第 1 競走 能力検査（曇・良） 1300 ｍ 発走時刻 12:50」。天候馬場は2024年ごろから書かれない。
# ⚠検査の呼び名は日によって違い(能力検査・能力試験・無し)、括弧の閉じ忘れもある
# (実測 2022-01-25「能力検査（曇り・不良 1300 ｍ」)。だから「競走」と距離の間は中身を見ずに飛ばす。
KOCHI_RACE_RE = re.compile(
    r"第\s*(\d+)\s*競走\s*(.{0,20}?)(\d{3,4})\s*m\s*(?:発走時刻\s*(\d{1,2}:\d{2}))?", re.I)
KOCHI_WX_RE = re.compile(r"[(（]\s*([^()・]+?)\s*・\s*([^()・]+?)\s*[)）]?\s*$")
KOCHI_COLS = {"毛色馬齢血種性別格": "bio", "騎手負担重量": "ride",
              "前走馬体重": "prev_weight", "基準タイム": "base"}
# ⛔性別の「セン(騙馬)」に外字を使っている(2026-08-26 実測: 925行中66行・全部 U+E598 の1文字で、
# 出るのは性別の所だけ)。そのまま入れると画面が □ になるので収集の時点で「セン」に直す(§10 #89)。
KOCHI_PUA_RE = re.compile(r"[\uE000-\uF8FF]+")
# ⛔「騎手/負担重量」欄の重量は 923/925 行が 0.0(発表が無い)。残る2行(2023-10-28 の 482.0・430.0)は
# 馬体重が紛れ込んだもので負担重量ではない(同じ行の馬体重と一致することを実測)。§10 #89。
KOCHI_KIN_MAX = 100.0


def kochi_expand(cells, keys):
    """高知の表は1セルに3項目まとめてある(縦書きの見出しをそのまま表にしたもの)。
      「鹿毛 2 / サラ 牝 / ２歳」= 毛色 馬齢 / 血種 性別 / 格 → sexage(牝2)と cls(2歳)
      「木村直 / 0.0」= 騎手 / 負担重量 → jockey と kin
    毛色・特徴・マイクロチップは使わないので取らない(DESIGN §32c)。"""
    cs, ks = [], []
    for text, key in zip(cells, keys):
        if key == "bio":
            lines = [norm(x).split() for x in text.split("\n")]
            age = lines[0][1] if len(lines) > 0 and len(lines[0]) > 1 else ""
            sex = lines[1][1] if len(lines) > 1 and len(lines[1]) > 1 else ""
            cls = " ".join(lines[2]) if len(lines) > 2 else ""
            sex = KOCHI_PUA_RE.sub("セン", sex)      # 外字の「セン」(§10 #89)
            cs.append(sex + age)
            ks.append("sexage")
            cs.append(cls)
            ks.append("cls")
            continue
        if key == "ride":
            parts = [p.replace(" ", "").strip() for p in norm(text).split("\n") if p.strip()]
            cs.append(parts[0] if parts else "")
            ks.append("jockey")
            cs.append(parts[1] if len(parts) > 1 else "")
            ks.append("kin")
            continue
        if key == "ped":                   # 「父馬名\n母馬名」。row_of が改行で割る
            cs.append(text)
            ks.append(key)
            continue
        flat = text.replace("\n", "")
        cs.append(flat.replace(" ", "") if key == "trainer" else flat)
        ks.append(key)
    return cs, ks


def kochi_kin(row, date, drop):
    """⛔「騎手/負担重量」の重量は 923/925 行が 0.0 = 発表が無い。残る2行(2023-10-28 の
    482.0・430.0)は馬体重が紛れ込んだもので負担重量ではない(同じ行の馬体重と一致)。
    負担重量になり得ない値(0 か 100kg 以上)は kin として出さない。馬体重が空ならそちらへ回す
    (実測の2行は馬体重が入っているので捨てるだけ)。§10 #89 の根治。"""
    raw = row.get("kin")
    if raw is None:
        return
    try:
        val = float(norm(raw))
    except ValueError:
        return                             # 数字でない書き方はそのまま置いておく
    if 0 < val < KOCHI_KIN_MAX:
        return                             # まっとうな負担重量(高知では今のところ1行も無い)
    row.pop("kin")
    if val <= 0:
        return                             # 0.0 = 発表なし。黙って落とす(923行)
    if row.get("weight"):
        drop.append(f"高知 {date} {row.get('name')} 負担重量 {raw} は馬体重"
                    f"({row['weight']})の写し(捨てる)")
    else:
        row["weight"] = str(int(val)) if val == int(val) else str(val)
        drop.append(f"高知 {date} {row.get('name')} 負担重量 {raw} を馬体重に回した")


def kochi_pdf(data, date, video, src, drop, race_videos=None):
    """1ページ=1レース。ページの見出しから レース番号・距離・天候馬場・発走時刻を取る。
    race_videos({レース番号: URL})があれば races[].video に付ける(§32g。索引は
    race.video を day.video より先に読むので、2R以上の日も▶が正しい競走を開くようになる)。"""
    races = []
    for text, tables in pdf_pages(data):
        rm = KOCHI_RACE_RE.search(text)
        dm = ERA_DATE_RE.search(text)
        if dm and era_of(dm) != date:
            drop.append(f"高知 {src} 記事は {date} だが PDF は {era_of(dm)}(PDF を採る)")
            date = era_of(dm)
        for table in tables:
            hi, keys = pdf_head(table, KOCHI_COLS)
            if hi < 0:
                continue
            rows = [r for r, _ in pdf_body(table, hi, keys, KOCHI_COLS, None, kochi_expand)]
            if not rows:
                continue
            for row in rows:
                kochi_kin(row, date, drop)
            race = {"no": int(rm.group(1)) if rm else len(races) + 1, "rows": rows}
            if rm:
                race["dist"] = int(rm.group(3))
                wm = KOCHI_WX_RE.search(rm.group(2))
                if wm:
                    race["weather"], race["going"] = wm.group(1), wm.group(2)
                if rm.group(4):
                    race["start"] = rm.group(4)
            bases = {r["base"] for r in rows if r.get("base")}
            if len(bases) == 1:            # 基準タイムはレースで1つ(ばんえいと同じ形で持つ)
                race["base"] = bases.pop()
            rv = (race_videos or {}).get(race["no"])
            if rv:
                race["video"] = rv
            races.append(race)
    if not races:
        return None
    # 検査前に取ると着順もタイムも合否も空(題は「出馬表」で、検査が終わると結果入りに差し替わる)。
    # ⚠着順とタイムだけでは足りない: 発走しなかった馬は合否(不合格)だけが入る日がある
    # (実測 2024-02-06 は1頭立てで着順もタイムも無いが不合格)。
    if not any(r.get("fin") or r.get("time") or r.get("ok") for race in races for r in race["rows"]):
        drop.append(f"高知 {date} 着順もタイムも合否も無い=検査前の PDF(次の実行で取り直す)")
        return None
    day = {"date": date, "venue": "高知", "races": races, "src_id": src}
    if video:
        day["video"] = video
    return day


def kochi_posts(backfill):
    """?cat=42 の記事(id, 実施日)。題が実施日そのもの(古い記事は「2020年5月30日」だけ)。
    差分は最初の2ページ(1ページ29件=だいたい9か月ぶん)、--backfill は読める年まで遡る。"""
    out, seen = [], set()
    for pg in range(1, 40):
        url = KOCHI_CAT + (f"&paged={pg}" if pg > 1 else "")
        page = get(url)
        found = 0
        for pid, label in KOCHI_POST_RE.findall(page):
            if pid in seen:
                continue
            seen.add(pid)
            found += 1
            date = era_date(norm(strip(label)))
            if date:
                out.append((pid, date))
        if not found:
            break
        if not backfill and pg >= 2:
            break
        if out and out[-1][1] < KOCHI_FROM:
            break                          # ここから先は字の無い PDF しかない
    return [(pid, date) for pid, date in out if date >= KOCHI_FROM]


def kochi_race_videos(art, date):
    """記事の埋め込み(iframe)の題からレース番号→動画URLを作る(§32g)。
    題は「高知けいば　能力検査　2026/08/02　第2競走」(全角スペース・エディタ次第で表記ゆれ)。
    記事にはショートムービーや啓発動画の埋め込みも並ぶが、題に「能力検査」と「第N競走」の
    両方が無いものは採らないので自然に外れる。題に日付があり記事の日付と違うものも採らない。
    ⛔iframe は data-iframe 属性の中に **HTMLエスケープされて**入っている(&lt;iframe …&gt;)ので、
    生の <iframe> とエスケープ形の両方を1本の切り出しで拾う。"""
    out = {}
    for chunk in re.findall(r"(?:<|&lt;)iframe(.*?)(?:>|&gt;)", art, re.S):
        tm = re.search(r'title=(?:"|&quot;)(.*?)(?:"|&quot;)', chunk, re.S)
        vm = YT_RE.search(chunk)
        if not tm or not vm:
            continue
        title = norm(H.unescape(tm.group(1)))
        if "能力検査" not in title:
            continue
        rm = re.search(r"第\s*(\d{1,2})\s*競走", title)
        if not rm:
            continue
        dm = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", title)
        if dm and date and "%04d-%02d-%02d" % tuple(int(x) for x in dm.groups()) != date:
            continue
        out.setdefault(int(rm.group(1)), "https://www.youtube.com/watch?v=" + vm.group(1))
    return out


def kochi_pdf_link(page, date=None):
    """記事の中の PDF とレース別動画。ページの下の方には毎回同じ案内(入場制限申告書など)が
    並ぶので、本文(<div id="the-content">〜</article>)の中だけ見る。"""
    i = page.find('id="the-content"')
    if i < 0:
        return None, None, {}
    j = page.find("</article>", i)
    art = page[i:j if j > i else len(page)]
    href = None
    for u, label in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', art, re.S):
        text = strip(label)
        if "/hensei/nouken/" in u or "能力" in text or "出馬表" in text or href is None:
            href = H.unescape(u)
            if "/hensei/nouken/" in u or "能力" in text or "出馬表" in text:
                break
    vm = YT_RE.search(art)
    return (href, "https://www.youtube.com/watch?v=" + vm.group(1) if vm else None,
            kochi_race_videos(art, date))


def collect_kochi(existing, backfill):
    if not pdf_lib():
        log("  高知: pdfplumber が入っていないので飛ばす(cloud/requirements.txt)")
        return []
    posts = kochi_posts(backfill)
    days, drop, miss, empty = [], [], 0, 0
    for pid, date in posts:
        if not backfill and pid in existing:
            continue
        try:
            href, video, rvids = kochi_pdf_link(get(f"{KOCHI}?p={pid}"), date)
        except Exception as e:
            miss += 1
            log(f"  高知 p={pid} 記事が読めない {type(e).__name__}: {str(e)[:100]}")
            continue
        if not href:
            empty += 1
            drop.append(f"高知 {date} 記事に PDF が無い(p={pid})")
            continue
        try:
            data, _ = get_bin(href)
            day = kochi_pdf(data, date, video, pid, drop, rvids)
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  高知 {date} PDF HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  高知 {date} PDF が読めない {type(e).__name__}: {str(e)[:100]}")
            continue
        if not day:
            empty += 1
            continue
        days.append(day)
        nrv = sum(1 for r in day["races"] if r.get("video"))
        log(f"  高知 {day['date']} {sum(len(r['rows']) for r in day['races'])}頭/"
            f"{len(day['races'])}R"
            + (f"(レース映像 {nrv}本)" if nrv else "(映像あり)" if day.get("video") else ""))
    for line in drop:
        log("  " + line)
    log(f"  高知: 記事 {len(posts)} 件 / 取得できた {len(days)} / 中身なし {empty} / 取得失敗 {miss}")
    return days


# ---------------------------------------------------------------- 金沢(石川県競馬事業局)
# https://www.kanazawakeiba.com/info/race/ のお知らせに「能力検査結果」PDF が回ごとに出る。
# 全15場でいちばん濃い(馬主・産地・血統・指示タイム・実走タイム・騎手・着順・合否)。
# 索引は1ページ20件で **2019-06 まで遡れる**(2026-08-26 実測: 67ページ・記事1,337件・能検156件。
# 68ページ目からは先頭の1件に巻き戻るので「新しい記事が出なくなったら止める」)。
# 字は156件とも埋まっている(高知のような画像だけの回は無い)。
KANA = "https://www.kanazawakeiba.com"
KANA_INDEX = KANA + "/info/race/"
KANA_ITEM_RE = re.compile(r'<li class="race"><a href="([^"]+)"[^>]*>(.*?)'
                          r'<span class="date">([\d.]+)</span>', re.S)
# 見出しの書き方は7通りあった(2026-08-26 実測)が、違うのは「その列があるか」だけなので
# 名前で対応を作れば全部通る。⚠2021〜2022年度は性齢の列そのものが無い。
KANA_COLS = {"枠番": "umaban", "馬名(馬主)": "name", "血統": "ped",
             "産地": "origin", "産地馬体重(鞍有)": "origin", "指示タイム": "base"}
# 「1R\n2歳\n1400m\n集合\n時刻\n11:00\n発走\n時刻\n11:15」= レースの枠。集合時刻を発走時刻と
# 取り違えないよう、時刻は必ず「発走」「集合」の字と一緒に読む。
KANA_START_RE = re.compile(r"発\s*走\s*時\s*刻\s*(\d{1,2}:\d{2})")
KANA_MEET_RE = re.compile(r"集\s*合\s*時\s*刻\s*(\d{1,2}:\d{2})")
KANA_DIST_RE = re.compile(r"([\d,]{3,6})\s*m")
KANA_KG_RE = re.compile(r"^\d{2,4}\s*(?:kg)?$", re.I)
KANA_HEAD_RE = re.compile(r"計\s*[:：]?\s*(\d+)\s*頭")
# 備考の欄の末尾に来る「タイムの代わりの字」。除外・取消は実走タイムが無いという意味
KANA_STATUS = {"除外", "取消", "中止", "失格", "不出走", "疾病", "競走除外"}
# 使われていない枠には「( )」だけが刷ってある。表計算のエラーがそのまま出ている回もある
KANA_JUNK = {"#N/A", "#REF!", "#VALUE!", "#DIV/0!", "#NAME?"}


def kana_txt(text):
    """「( )」だけの欄と表計算のエラー値は中身が無いものとして扱う。"""
    s = norm(text).replace("\n", "").strip()
    return "" if s in KANA_JUNK or not re.search(r"[^\s()]", s) else s


def kana_name(text):
    """「カガノクローム\n(矢内卓人)」→ ("カガノクローム", "矢内卓人")。
    空いている枠は「( )」だけが入っているので馬名は空にする(馬でない行を作らないため)。"""
    name, owner = "", ""
    for line in norm(text).split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("("):
            owner = re.sub(r"^\(|\)$", "", s).strip()
        elif not name:
            name = s
    if not re.search(r"[^\s()]", name):
        name = ""
    return name, owner


def kana_note(text):
    """備考の欄には「不合格の理由」と「騎手 実走タイム」が縦に並んで入っている
    (実測: 合格馬は「加藤翔馬 1.41.4」だけ・不合格馬は「能力不足\n柴田勇真 1.48.6」・
    検査を休んだ馬は「検査休み -」)。→ (騎手, タイム, 備考, 状態)。"""
    jockey, tm, status, notes = "", "", "", []
    for line in norm(text).split("\n"):
        # 「0」は古い書き方でタイムが無いことを表す置き字(検査休みの馬に付く)。捨てる
        parts = [p for p in line.split()
                 if p and p != "0" and p not in DASHES and p not in KANA_JUNK]
        if not parts:
            continue
        if TIME_RE.match(parts[-1]) or parts[-1] in KANA_STATUS:
            last = parts.pop()
            if TIME_RE.match(last):
                tm = last
            else:
                status = last
            if parts:
                jockey = "".join(parts)
            continue
        notes += parts
    return jockey, tm, "・".join(notes), status


def kana_expand(cells, keys):
    """1つのセルに2項目まとめてある列を割る。
      馬名(馬主) → name + owner / 血統「父 X\n母 Y」→ sire + dam /
      産地(と下の行に馬体重)→ orig + weight / 備考 → jockey + time + note + status"""
    cs, ks = [], []
    for text, key in zip(cells, keys):
        if key == "name":
            name, owner = kana_name(text)
            cs += [name, owner]
            ks += ["name", "owner"]
            continue
        if key == "ped":
            sire, dam = "", ""
            for line in norm(text).split("\n"):
                m = re.match(r"^([父母])\s*(.*)$", line.strip())
                if m and m.group(1) == "父":
                    sire = m.group(2).strip()
                elif m:
                    dam = m.group(2).strip()
                elif line.strip() and not sire:
                    sire = line.strip()
            cs += [sire, dam]
            ks += ["sire", "dam"]
            continue
        if key == "origin":
            # 回によって「産地」だけの列と「産地/馬体重」の2段の列がある。中身で見分ける
            place, kg = "", ""
            for line in norm(text).split("\n"):
                s = line.strip()
                if not s or s in DASHES:
                    continue
                if KANA_KG_RE.match(s):
                    kg = re.sub(r"[^\d]", "", s)
                elif not place:
                    place = s
            cs += [place, kg]
            ks += ["origin", "weight"]
            continue
        if key == "note":
            cs += list(kana_note(text))
            ks += ["jockey", "time", "note", "status"]
            continue
        if key == "sexage":
            # 「牝\n3」。使われていない枠から「( )」が紛れ込むので行ごとに落とす
            parts = [kana_txt(x) for x in norm(text).split("\n")]
            cs.append("".join(p.replace(" ", "") for p in parts if p))
            ks.append(key)
            continue
        flat = kana_txt(text)
        cs.append(flat.replace(" ", "") if key == "trainer" else flat)
        ks.append(key)
    return cs, ks


KANA_REASON_RE = re.compile(r"不良|不足|休み|跛行|移動|除外|取消|中止|変更|検査|[()]")
KANA_NAME_RE = re.compile(r"[一-龥ぁ-んァ-ヶー]{2,6}")


def kana_fix(row):
    """タイムが別の列に出る回では、備考の欄に騎手の名前だけが残る(2025年度〜)。
    タイムがあるのに騎手が空なら、備考の最後の項目を騎手として取り出す。
    ⚠不合格の理由(「能力不足」など)を人名と間違えないよう、理由の言い回しは外す。"""
    if row.get("jockey") or not row.get("time") or not row.get("note"):
        return
    parts = row["note"].split("・")
    last = parts[-1]
    if KANA_REASON_RE.search(last) or not KANA_NAME_RE.fullmatch(last):
        return
    row["jockey"] = last
    rest = "・".join(parts[:-1])
    if rest:
        row["note"] = rest
    else:
        row.pop("note")


def kana_keys(table):
    """ヘッダ行 → 列の対応。⚠見出しが空の列が2つある(先頭=レースの枠・馬名の右=性齢)。
    名前が無いので位置で補うしかないが、「その列の見出しが本当に空のときだけ」に限る。"""
    hi, keys = pdf_head(table, KANA_COLS)
    if hi < 0:
        return hi, keys
    head = [key_of("" if c is None else str(c)) for c in table[hi]]
    raw = ["" if c is None else norm(str(c)).strip() for c in table[hi]]
    if keys and not keys[0] and not raw[0]:
        keys[0] = "grp"
    if "name" in keys:
        i = keys.index("name") + 1
        if i < len(keys) and not keys[i] and not raw[i] and not head[i]:
            keys[i] = "sexage"
    # ⚠2025年度からは実走タイムが備考の右の「見出しの無い列」に出る回がある
    # (備考の欄には騎手の名前だけが残る。実測 2025-09-01 以降)
    if "note" in keys:
        i = keys.index("note") + 1
        if i < len(keys) and not keys[i] and not raw[i] and not head[i]:
            keys[i] = "time"
    return hi, keys


def kana_blocks(rows, keys):
    """表 → [(1レースぶんの行, 着順の文字列, レースの見出し)]。
    「着順 ６－２－３…」の行がレースの区切りなので、そこで割れば着順とレースが必ず対になる
    (⚠使われていないレースの枠が並ぶ回があり「着順 － － －」だけの塊も出る=馬が0頭)。
    1頭が2行に分かれている回もある(下の行に馬体重だけ)。枠番も馬名も空の行は上の馬の続きなので
    改行でつないで1行にする。
    ⛔レースの見出し(1R/2歳/1400m/集合時刻/発走時刻)は縦につながった1つのセルだが、
    pdfplumber が途中で切って何行かに分けて返す回がある(実測 2020-05-23 の 4R は「4 R」だけ)。
    行ごとに見るとレースが割れてしまうので、塊の中の見出し列を全部つないでから読む。"""
    ci = {k: i for i, k in enumerate(keys) if k}
    ui, ni, gi = ci.get("umaban", -1), ci.get("name", -1), ci.get("grp", -1)
    blocks, cur, label = [], [], []
    for row in rows:
        cells = ["" if c is None else str(c) for c in row]
        flat = [norm(c).replace("\n", " ").strip() for c in cells]
        if 0 <= gi < len(flat) and flat[gi]:
            label.append(flat[gi])
        if 0 <= ui < len(flat) and flat[ui] == "着順":
            blocks.append((cur, " ".join(flat[ui + 1:]), " ".join(label)))
            cur, label = [], []
            continue
        head = (flat[ui] if 0 <= ui < len(flat) else "") or \
               (kana_name(cells[ni])[0] if 0 <= ni < len(cells) else "")
        if not head and cur and any(flat):
            prev = cur[-1]
            for i, c in enumerate(cells):
                if i < len(prev) and c.strip():
                    prev[i] = (prev[i] + "\n" + c) if prev[i].strip() else c
            continue
        cur.append(cells)
    if cur:
        blocks.append((cur, "", " ".join(label)))   # 着順の行で終わっていない表
    return blocks


def kana_race(label, rows, src, drop):
    """レースの見出し → レース。番号は後で(番号の無い枠があるので日ぜんぶを見てから決める)。"""
    if len(re.findall(r"\d+\s*R", label)) > 1:
        drop.append(f"金沢 {src} 1つの着順の枠に見出しが2つ「{label[:60]}」(1レースとして入れる)")
    race = {"no": race_no(label, 0), "rows": rows}
    m = KANA_DIST_RE.search(label)
    if m:
        race["dist"] = int(m.group(1).replace(",", ""))
    m = KANA_START_RE.search(label)
    if m:
        race["start"] = m.group(1)
    kind = kana_kind(label)
    if kind:
        race["kind"] = kind
    return race


def kana_kind(grp):
    """レースの枠から 番号・距離・時刻 を消した残り = 区分(一般 / 混合 / 2歳 / 3歳)。"""
    s = KANA_MEET_RE.sub(" ", grp)
    s = KANA_START_RE.sub(" ", s)
    s = re.sub(r"\d+\s*R", " ", s)         # 「3R 2R」と2つ刷ってある回がある
    s = KANA_DIST_RE.sub(" ", s)
    s = re.sub(r"\d{1,2}:\d{2}|集\s*合|発\s*走|時\s*刻", " ", s)
    s = "".join(c for c in s if c not in DASHES and c not in "()")
    return re.sub(r"\s+", "", s)


def kana_finish(race, order, src, drop):
    """「着順 ６－２－３－４－５」= 枠番を着順の順に並べたもの。表に無い枠番が混ざっていたり
    同じ枠番が2回出てきたら読み違えなので、そのレースの着順は入れない。"""
    want = re.findall(r"\d+", order)
    if not want:
        return                             # 走らなかった枠(着順が「－ － －」)
    by = {r.get("umaban"): r for r in race["rows"]}
    if len(set(want)) != len(want) or any(w not in by for w in want):
        drop.append(f"金沢 {src} {race['no']}R の着順「{order.strip()}」が表の枠番と合わない"
                    f"(着順を入れない)")
        return
    for i, w in enumerate(want):
        by[w]["fin"] = str(i + 1)


def kana_pdf(data, src, drop, videos=None):
    """1つの PDF = 1日(実測: 156件とも1ページ)。回によって表が1つの日と、左右2つに割れて
    いる日(奇数レースが左・偶数レースが右)がある。番号は表の中に書いてあるので最後に並べ替える。"""
    races, text = [], ""
    for page_text, tables in pdf_pages(data):
        text += page_text + "\n"
        for table in tables:
            hi, keys = kana_keys(table)
            if hi < 0:
                continue                   # 成績以外の表(見出しの読めない飾り)
            for rows, order, label in kana_blocks(table[hi + 1:], keys):
                body = pdf_body(rows, -1, keys, KANA_COLS, None, kana_expand)
                if not body:
                    continue               # 使われていないレースの枠(馬が0頭)
                rows_d = [r for r, _ in body]
                for row in rows_d:
                    kana_fix(row)
                race = kana_race(label, rows_d, src, drop)
                kana_finish(race, order, src, drop)
                races.append(race)
    if not races:
        return None
    date = era_date(text)
    if not date:
        drop.append(f"金沢 {src} 実施日が読めない(捨てる)")
        return None
    top = max([r["no"] for r in races if r["no"]] + [0])
    for race in races:                     # 番号の書かれていない枠(中止になった回)は末尾に回す
        if not race["no"]:
            top += 1
            race["no"] = top
            drop.append(f"金沢 {src} {date} 番号の無いレースを {top}R として入れる")
    nos = [r["no"] for r in races]
    if len(set(nos)) != len(nos):
        drop.append(f"金沢 {src} {date} 同じレース番号が2つ {sorted(nos)}"
                    f"(主催者の書き方どおりそのまま入れる)")
    races.sort(key=lambda r: r["no"])
    got = sum(len(r["rows"]) for r in races)
    # 独立検証 = 表ではなく PDF の見出し「（計 ２４頭）」と突き合わせる(笠松・名古屋と同じ形)。
    # ⚠見出しは「申込」の数なので、検査に出て来なかった馬がいる回は表の行の方が少なくなる
    # ⛔備考の字が表の枠からはみ出している行があり、そこは pdfplumber が表として拾えない
    # (2026-08-26 実測 1,407行中2行。着順には載っているのにタイムも騎手も空になる)。
    # 黙って消さずに何が欠けたか言う
    for race in races:
        for row in race["rows"]:
            if row.get("fin") and not row.get("time") and not row.get("status"):
                drop.append(f"金沢 {src} {date} {race['no']}R {row.get('name')} は着順があるのに"
                            f"タイムが表に無い(PDF の枠からはみ出している)")
    hm = KANA_HEAD_RE.search(text)
    if hm and int(hm.group(1)) != got:
        drop.append(f"金沢 {src} {date} 見出しの頭数(申込) {hm.group(1)} と 表の行 {got} が違う"
                    f"(表のまま入れる)")
    day = {"date": date, "venue": "金沢", "races": races, "src_id": src}
    if videos and videos.get(date):        # §117b 公式チャンネルの「◯年◯月◯日 …能力検査」
        day["video"] = videos[date]
    return day


def kana_index(backfill):
    """お知らせ(レース)から「能力検査結果」の PDF を新しい順に。差分は3ページ(≒1か月半)まで。"""
    out, seen = [], set()
    for pg in range(1, 100):
        url = KANA_INDEX if pg == 1 else f"{KANA_INDEX}page/{pg}/"
        try:
            page = get(url)
        except Exception as e:
            log(f"  金沢: 索引 {pg} ページ目が読めない {type(e).__name__}: {str(e)[:80]}")
            break
        fresh = 0
        for href, title, when in KANA_ITEM_RE.findall(page):
            href = H.unescape(href)
            if href in seen:
                continue
            seen.add(href)
            fresh += 1
            label = norm(strip(title))
            if "能力検査" in label and href.lower().endswith(".pdf"):
                out.append((href, label, when))
        if not fresh:
            break                          # 最後のページの次は先頭の1件に巻き戻る
        if not backfill and pg >= 3:
            break
    return out


def collect_kanazawa(existing, backfill):
    if not pdf_lib():
        log("  金沢: pdfplumber が入っていないので飛ばす(cloud/requirements.txt)")
        return []
    items = kana_index(backfill)
    videos = kana_videos()                 # §117b 公式チャンネルの RSS(最新15本)
    days, drop, miss, empty, seen_date = [], [], 0, 0, {}
    for href, label, when in items:
        # ⛔ファイル名は元の題の md5 なので**年月まで入れないと重なる**(実測 156件中34件が重複。
        # 例 2e3d67… は 2021/05・2022/04・2023/05・2024/05 の4回ぶん)。src_id は年月込みで作る
        m = re.search(r"/uploads/(.+?)\.pdf$", href, re.I)
        src = m.group(1) if m else href.rsplit("/", 1)[-1][:-4]
        if not backfill and src in existing:
            continue
        try:
            data, _lm = get_bin(href)
        except urllib.error.HTTPError as e:
            miss += 1
            log(f"  金沢 {label} HTTP {e.code}(無視)")
            continue
        except Exception as e:
            miss += 1
            log(f"  金沢 {label} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        try:
            day = kana_pdf(data, src, drop, videos)
        except Exception as e:
            miss += 1
            log(f"  金沢 {label} PDF が読めない {type(e).__name__}: {str(e)[:100]}")
            continue
        if not day:
            empty += 1
            drop.append(f"金沢 {label} 中身の無い PDF({href})")
            continue
        # 独立検証その2 = 掲載日と PDF の実施日(ずれる回があれば言う。実施日は PDF を採る)
        if when.replace(".", "-") != day["date"]:
            drop.append(f"金沢 {day['date']} PDF の実施日と 掲載日 {when} が違う({label})")
        if day["date"] in seen_date:
            drop.append(f"金沢 {day['date']} が2つの PDF に({seen_date[day['date']]} と {src})")
        seen_date[day["date"]] = src
        days.append(day)
        log(f"  金沢 {day['date']} {sum(len(r['rows']) for r in day['races'])}頭/"
            f"{len(day['races'])}R")
    for line in drop:
        log("  " + line)
    log(f"  金沢: 索引の能検 {len(items)} 件 / 取得できた {len(days)} 日 / 中身なし {empty}"
        f" / 取得失敗 {miss}")
    return days


# ---------------------------------------------------------------- 南関4場(nankankeiba.com)
# §117b 下調べ= docs/s117_survey_result.md §2(2026-09-06 実物で確認)。
# 索引 /shiken_menu/shiken.do は**直近10日だけ**なので、日は**日付の総当たり**で拾う(無い日は 404)。
# ⛔公式に無い列(着順・馬番・上がり3F・馬場・天候・短評)は**入れない**(空で埋めない・推定しない)。
# ⚠ページの HTML は**行の開きタグが抜けている**(川崎 8/21 実測: `<tr` 45 / `</tr>` 72)。
#   `rows_of()` は `<tr…>` を要るので 4 頭中 3 頭が消える。ここは `</tr>` で切って読む。
NANKAN = "https://www.nankankeiba.com"
NANKAN_MENU = NANKAN + "/shiken_menu/shiken.do"
NANKAN_DAY = NANKAN + "/shiken_list/{}{}.do"
# 南関の場コード(URL の末尾2桁)
NANKAN_CODE = {"urawa": "18", "funabashi": "19", "ooi": "20", "kawasaki": "21"}
NANKAN_NAME = {"urawa": "浦和", "funabashi": "船橋", "ooi": "大井", "kawasaki": "川崎"}
NANKAN_RECENT = 21                    # 差分で総当たりする日数(今日から何日前まで)
# 見出しの列 → 行の鍵。⛔位置決め打ちにしない(§32a の作法)。「性別\n馬齢」「体重\n(kg)」は1セル
NANKAN_COLS = {"R": "no", "距離(m)": "dist", "馬名": "name", "父馬": "sire", "母馬": "dam",
               "騎手": "jockey", "調教師": "trainer", "性別馬齢": "sexage",
               "体重(kg)": "weight", "試験内容": "kind", "タイム": "time", "合否": "ok",
               "母父馬": "bms"}
# 行に入れる鍵(§117h で母父馬 bms も入れる= 画面の馬名の下の血統行「母 ○(母父 ○)」に出る)
NANKAN_KEEP = ("name", "sire", "dam", "jockey", "trainer", "sexage", "weight",
               "kind", "time", "ok", "bms")
# 説明欄に章がある場だけ offsets を作る(実測: 大井○ 浦和○ 川崎× 船橋×)
NANKAN_OFFSETS = ("ooi", "urawa")
UMA_ID_RE = re.compile(r"/uma_info/(\d{6,12})\.do")
VIDEO_BTN_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*to_video_anchor')
# 「0:00 第1組」「0:00　第1レース　2歳能力試験」(全角空白あり)。時:分[:秒]
CHAPTER_RE = re.compile(r"(?:^|\n)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?[\s　]*第\s*([0-9０-９]+)\s*"
                        r"(?:組|レース|Ｒ|R)")
YT_DESC_RE = re.compile(r'"shortDescription":"(.*?)","isCrawlable"', re.S)


def nankan_table_rows(table):
    """⚠開きタグの無い行があるので `</tr>` で切る。返り値= [[(タグの中の属性, セルの中身), …], …]"""
    out = []
    for chunk in table.split("</tr>"):
        cells = re.findall(r"<(t[dh])([^>]*)>(.*?)</t[dh]>", chunk, re.S)
        if cells:
            out.append([(tag, attrs, html) for tag, attrs, html in cells])
    return out


def nankan_keys(cells):
    """見出し行(12列)→ キーの並び。読めなければ []"""
    keys = [key_of(strip(html), NANKAN_COLS) for _t, _a, html in cells]
    return keys if "name" in keys and "time" in keys else []


def nankan_sexage(text):
    """「牝2」はそのまま・「牝\n2」も「牝 2」も既存の形(牝2)へ"""
    return re.sub(r"\s+", "", norm(text))


def nankan_day(prefix, date, drop):
    """1日1ページ。無い日は None(404)。⛔取得できなかった日と「試験の無い日」を混ぜない"""
    url = NANKAN_DAY.format(date.replace("-", ""), NANKAN_CODE[prefix])
    try:
        page = get(url, enc="cp932")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None                    # その日は試験が無い(索引と同じ意味)
        raise
    # 表は2つ(見出しだけの thead と 本体)。本体= 馬名リンクのある方
    table = next((t for t in tables_of(page) if UMA_ID_RE.search(t)), "")
    if not table:
        drop.append(f"{NANKAN_NAME[prefix]} {date} 馬の表が見つからない({url})")
        return None
    rws = nankan_table_rows(table)
    keys = next((k for k in (nankan_keys(c) for c in rws) if k), [])
    if not keys:
        drop.append(f"{NANKAN_NAME[prefix]} {date} 見出しが読めない({url})")
        return None
    races, cur = [], None
    for cells in rws:
        if nankan_keys(cells):
            continue                       # 見出しの行
        if len(cells) == len(keys):        # R と距離が入っている= レースの1頭目
            use = list(zip(keys, cells))
        elif len(cells) == len(keys) - 2:  # R と距離は上の行から続いている(rowspan)
            use = list(zip(keys[2:], cells))
        elif len(cells) == 1 and cur and cur["rows"] and "bms" not in cur["rows"][-1]:
            # §117h 母父馬は 2 段目の <tr>(td 1 つ)= 直前の馬の行に足す(見出しの「母父馬」も 2 段目)
            v = cell(strip(cells[0][2]))
            if v and "bms" in NANKAN_KEEP:
                cur["rows"][-1]["bms"] = v
            continue
        else:
            continue                       # 崩れた行
        row, no, dist = {}, None, None
        for key, (_tag, _attrs, html) in use:
            text = strip(html)
            if key == "no":
                m = re.search(r"\d+", norm(text))
                no = int(m.group(0)) if m else None
                continue
            if key == "dist":
                m = re.search(r"\d+", norm(text).replace(",", ""))
                dist = int(m.group(0)) if m else None
                continue
            if key not in NANKAN_KEEP:
                continue
            v = nankan_sexage(text) if key == "sexage" else cell(text)
            if not v:
                continue
            row[key] = fix_time(v) if key == "time" else v
            if key == "name":
                m = UMA_ID_RE.search(html)
                if m:
                    row["official_horse_id"] = m.group(1)
        if not row.get("name"):
            continue
        if no is not None or cur is None:
            cur = {"no": no, "rows": []}
            if dist is not None:
                cur["dist"] = dist
            races.append(cur)
        cur["rows"].append(row)
    if not races:
        return None
    day = {"date": date, "venue": NANKAN_NAME[prefix], "races": races}
    vm = VIDEO_BTN_RE.search(page)
    if vm:
        day["video"] = H.unescape(vm.group(1))
    return day


def yt_description(url):
    """動画ページの説明欄。読めなければ ""(⛔ここで例外を上げない= 映像は本文ではない)"""
    m = YT_RE.search(url or "")
    if not m:
        return ""
    try:
        page = get("https://www.youtube.com/watch?v=" + m.group(1))
    except Exception as e:
        log(f"  説明欄が読めない {m.group(1)} {type(e).__name__}: {str(e)[:60]}")
        return ""
    dm = YT_DESC_RE.search(page)
    if not dm:
        return ""
    try:
        return json.loads('"%s"' % dm.group(1))
    except Exception:
        return ""


def nankan_offsets(video_url):
    """説明欄の章「0:00 第1組」→ {"1": 0, "2": 77}。章が無ければ None(⛔何も書かない)"""
    desc = yt_description(video_url)
    if not desc:
        return None
    out = {}
    for h, mi, s, no in CHAPTER_RE.findall("\n" + desc):
        sec = int(h) * 3600 + int(mi) * 60 + int(s or 0) if s else int(h) * 60 + int(mi)
        out[str(int(norm(no)))] = sec
    return out or None


def nankan_dates(prefix, backfill):
    """差分= 索引に出ている日 + 今日から NANKAN_RECENT 日前まで。--backfill= 今年の1/1から今日まで。
    ⛔過去の年は足さない(スコープの床=1年単位)。"""
    today = dt.datetime.now(JST).date()
    if backfill:
        start = dt.date(today.year, 1, 1)
        return [(start + dt.timedelta(days=i)).isoformat()
                for i in range((today - start).days + 1)]
    days = {(today - dt.timedelta(days=i)).isoformat() for i in range(NANKAN_RECENT + 1)}
    try:
        page = get(NANKAN_MENU, enc="cp932")
        code = NANKAN_CODE[prefix]
        for d in re.findall(r"/shiken_list/(\d{8})" + code + r"\.do", page):
            days.add(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    except Exception as e:
        log(f"  {NANKAN_NAME[prefix]}: 索引が読めない {type(e).__name__}: {str(e)[:80]}")
    return sorted(days)


def collect_nankan(prefix, existing, backfill):
    """返り値= (days, offsets)。offsets は説明欄に章のある場だけ(無ければ {})"""
    name = NANKAN_NAME[prefix]
    dates = nankan_dates(prefix, backfill)
    days, offsets, drop = [], {}, []
    miss = hit = 0
    for date in dates:
        if not backfill and date in existing:
            continue
        try:
            day = nankan_day(prefix, date, drop)
        except Exception as e:
            miss += 1
            log(f"  {name} {date} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        if not day:
            continue
        hit += 1
        days.append(day)
        log(f"  {name} {date} {sum(len(r['rows']) for r in day['races'])}頭/"
            f"{len(day['races'])}R 映像 {'有' if day.get('video') else '無'}")
        if prefix in NANKAN_OFFSETS and day.get("video"):
            off = nankan_offsets(day["video"])
            vm = YT_RE.search(day["video"])
            if off and vm:
                offsets[date] = {"video_id": vm.group(1), "offsets": off}
                log(f"    頭出し {len(off)} レース {sorted(off.items(), key=lambda x: int(x[0]))}")
    for line in drop:
        log("  " + line)
    log(f"  {name}: 叩いた日 {len(dates)} / 試験のあった日 {hit} / 取得失敗 {miss}"
        f" / 頭出しの取れた日 {len(offsets)}")
    return days, offsets


def nankan_collector(prefix):
    def collect(existing, backfill):
        return collect_nankan(prefix, existing, backfill)
    return collect


# ---------------------------------------------------------------- 門別(hokkaidokeiba.net)
# §117b 下調べ= docs/s117_survey_result.md §1。索引は**今年度だけ**(19日)。
# 成績は R ごとの PDF ではなく **全R の PDF(-00.pdf)**を1枚読む(罫線の表が4つ/頁で拾える)。
# ⛔上がり3F・短評は公式に無いので入れない。fin は見出し「１R . . . ３ . １ . ２ . ４ . ５ ８００m」から。
MONBETSU = "https://www.hokkaidokeiba.net"
MONBETSU_INDEX = MONBETSU + "/racedata/noken/"
MONBETSU_DAY = MONBETSU + "/racedata/noken/index.php?p_day={}"
MONBETSU_FILE = MONBETSU + "/user-data/noken/{}-{:02d}.{}"
MONBETSU_RECENT = 3                   # 差分で見に行く日数(索引の新しい方から)
MONBETSU_DATE_RE = re.compile(r"<option value='(\d{8})'")
# 索引の1レース分「<dt>1Ｒ</dt><dd>…</dd>」。動画の無いレースは <li class="nodt">動画</li>
MONBETSU_RACE_RE = re.compile(r"<dt>([０-９\d]+)Ｒ</dt>\s*<dd>(.*?)</dd>", re.S)
MONBETSU_MP4_RE = re.compile(r"wfNokenMovie\('[^']*','(\d{8}-\d{2}\.mp4)'")
MONBETSU_PDF_RE = re.compile(r"user-data/noken/(\d{8}-\d{2}\.pdf)")
MONBETSU_WX_RE = re.compile(r"〔([^〕]*)〕")
MONBETSU_PASS_RE = re.compile(r"合格頭数([０-９\d]+)頭")
MONBETSU_TIMEOVER = "タイムオーバー"


def monbetsu_dates(backfill):
    """索引の日付(今年度ぶん)。新しい順。差分は先頭 MONBETSU_RECENT 日だけ見る。"""
    page = get(MONBETSU_INDEX)
    dates = sorted({f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in MONBETSU_DATE_RE.findall(page)},
                   reverse=True)
    return dates if backfill else dates[:MONBETSU_RECENT]


def monbetsu_files(date):
    """その日の R ごとの pdf / mp4。⛔HEAD はしない= 索引が動画を貼っている R だけ mp4 を入れる。"""
    page = get(MONBETSU_DAY.format(date.replace("-", "")))
    out = {}
    for no, body in MONBETSU_RACE_RE.findall(page):
        n = int(norm(no))
        item = {}
        pm = MONBETSU_PDF_RE.search(body)
        if pm:
            item["pdf"] = MONBETSU + "/user-data/noken/" + pm.group(1)
        mm = MONBETSU_MP4_RE.search(body)
        if mm:
            item["mp4"] = MONBETSU + "/user-data/noken/" + mm.group(1)
        out[n] = item
    return out


def monbetsu_heads(page):
    """1頁の「NR . . . 3 . 1 . 2 . 4 . 5 800m」を語の座標から読む。
    ⚠見出しの `NR` と 着順の数字は 2pt ずれた別の行として出てくるので、行の幅を広めに取る。
    ⛔字を詰めた本文から読んではいけない(最後の着順と距離がくっついて「４８００m」になる)。"""
    ws = page.extract_words()
    out = []
    for w in ws:
        m = re.fullmatch(r"([0-9０-９]+)R", w["text"])
        if not m:
            continue
        line = sorted((v for v in ws if v is not w and abs(v["top"] - w["top"]) <= 6
                       and v["x0"] > w["x0"]), key=lambda v: v["x0"])
        order, dist = [], None
        for v in line:
            t = norm(v["text"])
            dm = re.fullmatch(r"([\d,]+)m", t)
            if dm:
                dist = int(dm.group(1).replace(",", ""))
                break
            if re.fullmatch(r"\d+", t):
                order.append(int(t))
        out.append({"no": int(norm(m.group(1))), "x0": w["x0"], "top": w["top"],
                    "order": order, "dist": dist})
    return out


def monbetsu_head_for(heads, bbox):
    """表の枠のすぐ上・同じ列にある見出しを選ぶ(1頁に4つの表が2列2段で並ぶ)"""
    x0, top = bbox[0], bbox[1]
    best = None
    for h in heads:
        if h["top"] >= top or top - h["top"] > 60:
            continue
        if not (x0 - 25 <= h["x0"] <= x0 + 90):
            continue
        if best is None or h["top"] > best["top"]:
            best = h
    return best


def monbetsu_rows(table, order):
    """表の1レース分。馬は2行(2行目は母の血統だけ)。⛔空の枠(使っていない行)は落とす。"""
    rows, cur = [], None
    for cells in table[1:]:
        c = [norm(x or "").strip() for x in cells]
        if len(c) < 11:
            continue
        ped = c[5]
        if re.fullmatch(r"\d+", c[0]):
            parts = [p for p in (x.strip() for x in c[1].split("\n")) if p]
            name = parts[1] if len(parts) >= 3 else (parts[0] if parts else "")
            if not name:
                continue
            row = {"umaban": c[0], "name": name}
            age_sex = [p for p in (x.strip() for x in c[3].split("\n")) if p]
            if len(age_sex) >= 2:
                row["sexage"] = age_sex[1] + age_sex[0]
            elif age_sex:
                row["sexage"] = age_sex[0]
            sire = ped.split(" ")[-1].strip() if ped else ""
            if sire:
                row["sire"] = sire
            for key, i in (("jockey", 7), ("time", 8), ("trainer", 9), ("weight", 10)):
                v = cell(c[i]) if i < len(c) else ""
                if v:
                    row[key] = fix_time(v) if key == "time" else v
            if not row.get("jockey") and not row.get("trainer"):
                continue           # 表の下の「制限タイム ◯◯秒」= 馬ではない(実測 2026-07-27)
            note = cell(c[12]) if len(c) > 12 else ""
            if note:
                row["note"] = note
            try:
                row["fin"] = str(order.index(int(c[0])) + 1)
            except ValueError:
                pass                       # 着順の並びに無い馬(取消など)は fin を付けない
            rows.append(row)
            cur = row
        elif cur is not None and ped:
            dam = ped.split(" ")[-1].strip()
            if dam:
                cur["dam"] = dam
    return rows


def monbetsu_pdf(data, date, files, drop):
    """全R の PDF 1枚 → races。ok は「備考=タイムオーバー」「×の数」「合格頭数」が
    **3つとも合ったときだけ**付ける(合わない日は付けずにログへ)。"""
    pdfplumber = pdf_lib()
    races, marks, npass = [], 0, None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            tight = re.sub(r"\s+", "", text)
            marks += tight.count("×")
            pm = MONBETSU_PASS_RE.search(tight)
            if pm:
                npass = int(norm(pm.group(1)))
            wx = MONBETSU_WX_RE.search(text)
            weather, going = "", ""
            if wx:
                parts = [p.strip() for p in norm(wx.group(1)).replace("・", "/").split("/")]
                weather = parts[0] if parts else ""
                going = parts[1] if len(parts) > 1 else ""
            heads = monbetsu_heads(page)
            for tb in page.find_tables():
                head = monbetsu_head_for(heads, tb.bbox)
                if not head:
                    continue
                rows = monbetsu_rows(tb.extract(), head["order"])
                if not rows:
                    continue
                race = {"no": head["no"], "rows": rows}
                if head["dist"]:
                    race["dist"] = head["dist"]
                if going:
                    race["going"] = going
                if weather:
                    race["weather"] = weather
                got = files.get(head["no"]) or {}
                if got.get("mp4"):
                    race["mp4"] = got["mp4"]
                if got.get("pdf"):
                    race["pdf"] = got["pdf"]
                races.append(race)
    races.sort(key=lambda r: r["no"])
    monbetsu_ok(races, npass, marks, date, drop)
    return races


def monbetsu_ok(races, npass, marks, date, drop):
    """合否を付ける。⛔日の「合格頭数 N 頭」と数が合ったときだけ(合わない日は付けずにログへ)。"""
    rows = [row for r in races for row in r["rows"]]
    # ⚠タイムの無い馬は「出走取消」「競走中止」= 検査を受けていない。合否のどちらでもないので付けない
    #   (旧データはこの馬を丸ごと落としていた。⛔落とさずに備考のまま残す)
    ran = [row for row in rows if row.get("time")]
    bad = {id(row) for row in ran if MONBETSU_TIMEOVER in (row.get("note") or "")}
    if npass is None:
        drop.append(f"門別 {date} PDF に「合格頭数」が無い= 合否を付けない({len(rows)}頭)")
    elif len(ran) - len(bad) != npass:
        drop.append(f"門別 {date} 合格頭数と合わない= 合否を付けない"
                    f"(走った {len(ran)} / タイムオーバー {len(bad)} / 合格頭数 {npass} /"
                    f" ×の印 {marks} / 行 {len(rows)})")
    else:
        if marks > len(rows) - len(ran) + len(bad):
            drop.append(f"門別 {date} ×の印 {marks} が 走らなかった馬+タイムオーバー "
                        f"{len(rows) - len(ran)}+{len(bad)} より多い(合否は付けるが要確認)")
        for row in ran:
            row["ok"] = "不合格" if id(row) in bad else "合格"


def collect_monbetsu(existing, backfill):
    if not pdf_lib():
        log("  門別: pdfplumber が入っていないので飛ばす(cloud/requirements.txt)")
        return []
    try:
        dates = monbetsu_dates(backfill)
    except Exception as e:
        log(f"  門別: 索引が読めない {type(e).__name__}: {str(e)[:100]}")
        return []
    days, drop, miss = [], [], 0
    for date in dates:
        if not backfill and date in existing:
            continue
        stem = date.replace("-", "")
        try:
            files = monbetsu_files(date)
            data, _lm = get_bin(MONBETSU_FILE.format(stem, 0, "pdf"))
        except Exception as e:
            miss += 1
            log(f"  門別 {date} 取得失敗 {type(e).__name__}: {str(e)[:100]}")
            continue
        try:
            races = monbetsu_pdf(data, date, files, drop)
        except Exception as e:
            miss += 1
            log(f"  門別 {date} PDF が読めない {type(e).__name__}: {str(e)[:100]}")
            continue
        if not races:
            drop.append(f"門別 {date} 表が読めない(捨てる)")
            continue
        day = {"date": date, "venue": "門別", "races": races,
               "all_pdf": MONBETSU_FILE.format(stem, 0, "pdf")}
        days.append(day)
        log(f"  門別 {date} {sum(len(r['rows']) for r in races)}頭/{len(races)}R "
            f"映像 {sum(1 for r in races if r.get('mp4'))}本")
    for line in drop:
        log("  " + line)
    log(f"  門別: 索引の日 {len(dates)} / 取れた {len(days)} 日 / 取得失敗 {miss}")
    return days


# ---------------------------------------------------------------- §117b 名古屋・金沢の映像
# 下調べ(docs/s117_survey_result.md §3)= どちらも「1日1本」。結果表の読み方は触らない。
NAGOYA_SITE = "https://www.nagoyakeiba.com"
NAGOYA_CAP = NAGOYA_SITE + "/info/program/capability/index.html"
NAGOYA_EMBED_RE = re.compile(r'<iframe[^>]+src="https://www\.youtube\.com/embed/([\w-]{11})')
YT_TITLE_RE = re.compile(r'"videoDetails":\{.*?"title":"(.*?)","lengthSeconds"', re.S)
# 「金シャチけいば情報(第11回能力審査)R8 08 24」= 令和8年8月24日。回番号も見て食い違いを言う
NAGOYA_VID_RE = re.compile(r"R\s*(\d+)[\s./]+(\d{1,2})[\s./]+(\d{1,2})")
NAGOYA_KAI_RE = re.compile(r"第\s*([0-9０-９]+)\s*回")
KANA_YT = ("https://www.youtube.com/feeds/videos.xml?"
           "channel_id=UCMRX5ABMJWPR6aWlyZYeKog")
KANA_ENTRY_RE = re.compile(r"<entry>(.*?)</entry>", re.S)


def yt_title(vid):
    """動画ページの題。読めなければ ""(⛔映像は本文ではないのでここで落ちない)"""
    try:
        page = get("https://www.youtube.com/watch?v=" + vid)
    except Exception as e:
        log(f"  動画の題が読めない {vid} {type(e).__name__}: {str(e)[:60]}")
        return ""
    m = YT_TITLE_RE.search(page)
    if not m:
        return ""
    try:
        return json.loads('"%s"' % m.group(1))
    except ValueError:
        return ""


def nagoya_videos():
    """能力審査結果ページに埋まっている動画 → {実施日: URL}。
    ⚠題の「第N回」だけで合わせると年度をまたいで重なる(第11回は令和6・7・8年度にある)ので、
    題の日付「R8 08 24」で合わせ、回番号は食い違いを言うためだけに使う。"""
    try:
        page = get(NAGOYA_CAP)
    except Exception as e:
        log(f"  名古屋: 能力審査結果ページが読めない {type(e).__name__}: {str(e)[:80]}"
            f"(映像は付けない)")
        return {}
    out = {}
    for vid in dict.fromkeys(NAGOYA_EMBED_RE.findall(page)):
        title = norm(yt_title(vid))
        m = NAGOYA_VID_RE.search(title)
        km = NAGOYA_KAI_RE.search(title)
        if not m:
            log(f"  名古屋 動画 {vid} 「{title[:40]}」に日付が無い(使わない)")
            continue
        date = f"{ERA['令和'] + int(m.group(1))}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if date in out:
            log(f"  名古屋 {date} に動画が2本(先に見つけた方を使う)")
            continue
        out[date] = "https://www.youtube.com/watch?v=" + vid
        log(f"  名古屋 動画 {date} 第{km.group(1) if km else '?'}回 {vid}")
    log(f"  名古屋: ページの動画 {len(out)} 本(日付の読めたもの)")
    return out


def kana_videos():
    """公式チャンネルの RSS(最新15本)から「◯年◯月◯日 … 能力検査」→ {実施日: URL}。
    ⚠RSS は最新の15本だけ= 古い回には付かない(⛔無いものは書かない)。"""
    try:
        xml = get(KANA_YT)
    except Exception as e:
        log(f"  金沢: 公式チャンネルの RSS が読めない {type(e).__name__}: {str(e)[:80]}"
            f"(映像は付けない)")
        return {}
    out = {}
    for entry in KANA_ENTRY_RE.findall(xml):
        tm = re.search(r"<title>(.*?)</title>", entry, re.S)
        vm = re.search(r"<yt:videoId>([\w-]{11})</yt:videoId>", entry)
        if not tm or not vm:
            continue
        title = norm(H.unescape(tm.group(1)))
        if "能力検査" not in title and "能力審査" not in title:
            continue
        dm = YT_DATE_RE.search(title)
        if not dm:
            log(f"  金沢 動画 {vm.group(1)} 「{title[:40]}」に日付が無い(使わない)")
            continue
        date = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
        out.setdefault(date, "https://www.youtube.com/watch?v=" + vm.group(1))
        log(f"  金沢 動画 {date} {vm.group(1)}")
    log(f"  金沢: RSS の能検の動画 {len(out)} 本")
    return out


# ---------------------------------------------------------------- まとめ

BY_SRC = (lambda days: {d.get("src_id") for d in days}, lambda day: day.get("src_id"))

BY_DATE = (lambda days: {d["date"] for d in days}, lambda day: day["date"])

VENUES = {
    "iwate": ("iwate_noken", collect_iwate, *BY_DATE),
    "hyogo": ("hyogo_noken", collect_hyogo, *BY_SRC),
    "saga": ("saga_noken", collect_saga, *BY_SRC),
    "banei": ("banei_noken", collect_banei, *BY_SRC),
    # 笠松は1つの PDF に2日入ることがある(前半/後半)ので日付をキーにする
    "kasamatsu": ("kasamatsu_noken", collect_kasamatsu, *BY_DATE),
    "nagoya": ("nagoya_noken", collect_nagoya, *BY_SRC),
    "kochi": ("kochi_noken", collect_kochi, *BY_SRC),
    "kanazawa": ("kanazawa_noken", collect_kanazawa, *BY_SRC),
    # §117b 手元の PC のジョブから移した5場(主催者公式だけで組む)
    "monbetsu": ("monbetsu_noken", collect_monbetsu, *BY_DATE),
    "ooi": ("ooi_noken", nankan_collector("ooi"), *BY_DATE),
    "funabashi": ("funabashi_noken", nankan_collector("funabashi"), *BY_DATE),
    "kawasaki": ("kawasaki_noken", nankan_collector("kawasaki"), *BY_DATE),
    "urawa": ("urawa_noken", nankan_collector("urawa"), *BY_DATE),
}
ORDER = ["iwate", "hyogo", "saga", "banei", "kasamatsu", "nagoya", "kochi", "kanazawa",
         "monbetsu", "ooi", "funabashi", "kawasaki", "urawa"]


# ---------------------------------------------------------------- §117b-2 5 場の補完(2026-09-06 ユーザー指摘「上がり3F と着順・馬番は大事」)
# 公式(南関)には 着順・馬番・上がり3F・通過・馬場・天候 が無い。旧 DB(chihou_meta `<prefix>_noken`= 手元のジョブが
# 書いている側)は持っているので、**日付+馬名**で当てて足す。⛔公式の行が本体・旧 DB は足すだけ(公式の値は上書きしない)。
# 旧 DB は公開 anon キーで**読むだけ**(js/data.js のもの)。手元ジョブが追いつくと次の朝便で自動的に埋まる。
CHIHOU_URL = "https://jcrcftvrsgmsewwdkqha.supabase.co"
CHIHOU_ENRICH = ("monbetsu", "ooi", "funabashi", "kawasaki", "urawa")
ENRICH_ROW_KEYS = ("fin", "umaban", "last3f", "pass_order")
ENRICH_RACE_KEYS = ("going", "weather")


def chihou_anon_key():
    try:
        js = (HERE.parent / "js" / "data.js").read_text(encoding="utf-8")[:4000]
        m = re.search(r"SUPABASE_KEY\s*=\s*'(eyJ[A-Za-z0-9._-]+)'", js)
        return m.group(1) if m else None
    except OSError:
        return None


def name_key(text):
    return re.sub(r"\s+", "", norm(str(text or "")))


def chihou_enrich(prefix, days):
    """旧 DB の同じ日の行を馬名で当て、無い項目だけ足す。戻り値= (足した行数, 当たらなかった行数)。"""
    if prefix not in CHIHOU_ENRICH or not days:
        return 0, 0
    key = chihou_anon_key()
    if not key:
        log(f"  {prefix}: 旧 DB のキーが読めない= 補完なし")
        return 0, 0
    try:
        old = sb_get_meta(CHIHOU_URL, key, f"{prefix}_noken", table="chihou_meta") or {}
    except Exception as e:                                       # noqa: BLE001
        log(f"  {prefix}: 旧 DB が読めない({type(e).__name__})= 補完なし")
        return 0, 0
    by_date = {}
    for d in old.get("days") or []:
        rows = {}
        for r in d.get("races") or []:
            for row in r.get("rows") or []:
                k = name_key(row.get("name"))
                if not k:
                    continue
                # 同じ日に同名が 2 頭いたら当てない(None を入れて印にする)
                rows[k] = None if k in rows else (row, r)
        by_date[str(d.get("date"))] = rows
    added, missed = 0, 0
    for d in days:
        rows = by_date.get(str(d.get("date")))
        if not rows:
            missed += sum(len(r.get("rows") or []) for r in d.get("races") or [])
            continue
        for r in d.get("races") or []:
            src_races = {}
            for row in r.get("rows") or []:
                hit = rows.get(name_key(row.get("name")))
                if not hit:
                    missed += 1
                    continue
                orow, orace = hit
                put = False
                for k in ENRICH_ROW_KEYS:
                    if k not in row and orow.get(k) not in (None, ""):
                        row[k] = orow[k]
                        put = True
                if put:
                    added += 1
                src_races[id(orace)] = orace
            # 馬場・天候は旧 DB の(当たった馬が属する)レースから。複数に割れたら足さない
            if len(src_races) == 1:
                orace = next(iter(src_races.values()))
                for k in ENRICH_RACE_KEYS:
                    if k not in r and orace.get(k) not in (None, ""):
                        r[k] = orace[k]
    return added, missed


# ---------------------------------------------------------------- §117e 兵庫= 本当のレース単位に組み直す
# ⛔ここまでの当サイトの `races[].no` は**本当の R ではなかった**: 兵庫の公式の結果ページは
#   「種別(ゲート検査/能力検査/発走検査/自主参加)×距離」で表を分けているだけで、レースの区切りを持たない
#   (2026-08-17 園田= 公式は 6 つの塊・本当は 4 レース)。
# 区切りと順番は**提供データ**(レースごとの表)と**映像の板**が持っているので、そこから組み直す。
#   ①行(全頭・タイム・馬体重・合否)は**公式のまま**(⛔上書きしない)
#   ②入れ物(レースの区切り・順番・距離)は提供データ
#   ③提供データに無い馬は**板の馬名**で入れる
#   ④どちらにも無い馬は⛔落とさず「組不明」(no なし)に残す
# ⛔split の無い日は **no を付けない**(偽の番号を DB に残さない= 画面は「検査」見出しに戻る)。
HYOGO_SPLIT_KEY = "hyogo_noken_split"
# 提供データから足す列(公式に無いもの)。⛔time/weight/ok は公式を残す
SPLIT_ADD_KEYS = ("fin", "umaban", "pass_order", "last3f")
UNKNOWN_KIND = "組不明"


def split_name_key(text):
    """馬名の突き合わせ用。全角を寄せ・空白と「※」を落とす(⛔字は変えない)。"""
    return name_key(str(text or "").replace("※", ""))


def name_to_no(pairs):
    """[(no, [馬名…])] → {馬名: no}。同じ日に同名が 2 頭いたら**当てない**(None を入れて印にする)。"""
    idx = {}
    for no, names in pairs:
        for nm in names or []:
            k = split_name_key(nm)
            if not k:
                continue
            idx[k] = None if k in idx else no
    return idx


def kb_to_board(kb_races, board_no):
    """§117f 提供データのレース → 板の R。そのレースの馬名が**1つの板だけ**に居るときだけ付け替える。
    ⛔2つの板に割れたレースは付けない(どちらの R か決められない= その馬は組不明へ)。
    返り値 = ({提供データの no: 板の R}, 割れたレースの説明[])"""
    out, split_up = {}, []
    for r in (kb_races or []):
        hit = {}
        for x in (r.get("rows") or []):
            no = board_no.get(split_name_key(x.get("name")))
            if no is not None:
                hit[no] = hit.get(no, 0) + 1
        if len(hit) == 1:
            out[r.get("no")] = next(iter(hit))
        elif len(hit) > 1:
            split_up.append("%sレース目の馬が板 %s に割れている" % (r.get("no"), sorted(hit)))
    return out, split_up


def hyogo_split_day(day, sp):
    """1 日ぶんを本当のレース単位に組み直す(day を書き換える)。

    ⚠`sp["mismatch"]` の日(板の R と提供データの並びがずれる日)は **板の R を no にする**(§117f)。
      映像には提供データに 1 行も無いレースが挟まっていることがあり、提供データの通し番号は R ではない。
    返り値 = {"races": レース数, "unknown": 組不明の行数, "kb_missing": 提供データに無かった行数,
              "by_board": 板で当てた行数, "conflict": 公式と提供データで値が違った行数}"""
    official = day.get("races") or []
    flat = []                                                 # 公式の全行(どの塊から来たかを覚える)
    for g in official:
        for row in (g.get("rows") or []):
            if g.get("kind") and not row.get("kind"):
                row["kind"] = g["kind"]                       # 行に種別を移す(レースには付けない)
            flat.append({"row": row, "dist": g.get("dist")})
    kb_races = sp.get("races") or []
    kb_no = name_to_no([(r.get("no"), [x.get("name") for x in (r.get("rows") or [])]) for r in kb_races])
    kb_row, kb_at = {}, {}
    for r in kb_races:
        for i, x in enumerate(r.get("rows") or []):
            k = split_name_key(x.get("name"))
            if not k:
                continue
            kb_row[k] = None if k in kb_row else x
            kb_at[k] = i
    boards = sp.get("boards") or []
    board_no = name_to_no([(b.get("no"), b.get("names")) for b in boards])
    # §117f ずれる日= 板の R が本当の R。提供データのレースは馬名で板に付け替える
    by_board = bool(sp.get("mismatch")) and bool(boards)
    remap, split_up = kb_to_board(kb_races, board_no) if by_board else ({}, [])

    buckets, unknown = {}, []
    stat = {"races": 0, "unknown": 0, "kb_missing": 0, "by_board": 0, "conflict": 0, "dup": 0,
            "by_board_race": 0, "split_up": split_up, "mode": "板のR" if by_board else "提供データの並び"}
    for item in flat:
        k = split_name_key((item["row"] or {}).get("name"))
        # ⛔その日に同名が2頭いる馬は**どこにも当てない**(提供データでも板でも決められない)
        amb = bool(k) and ((k in kb_no and kb_no[k] is None) or (k in board_no and board_no[k] is None))
        no = None if amb else (kb_no.get(k) if k else None)
        kx = None if amb else (kb_row.get(k) if k else None)
        if amb:
            stat["dup"] += 1
        elif by_board:
            # ①板に居ればその R ②居なければ、その馬の提供データのレースが板に付け替えられていればその R
            bno = board_no.get(k) if k else None
            if no is None:
                stat["kb_missing"] += 1
            if bno is not None:
                if no is None:
                    stat["by_board"] += 1
                no = bno
            elif no is not None and no in remap:
                stat["by_board_race"] += 1
                no = remap[no]
            else:
                no = None
        elif no is None:
            stat["kb_missing"] += 1
            no = board_no.get(k) if k else None
            if no is not None:
                stat["by_board"] += 1
        if no is None:
            unknown.append(item)
            continue
        item["at"] = kb_at.get(k, 99) if kx else 99
        buckets.setdefault(no, []).append(item)
        if not kx:
            continue
        for key in SPLIT_ADD_KEYS:                            # 公式に無い列だけ足す
            v = kx.get(key)
            if v not in (None, "") and item["row"].get(key) in (None, ""):
                item["row"][key] = v
        for key in ("time", "weight", "ok"):                  # ⛔公式を残す(違いは数えるだけ)
            a, b = item["row"].get(key), kx.get(key)
            if a not in (None, "") and b not in (None, "") and str(a) != str(b):
                stat["conflict"] += 1
                break

    races = []
    back = {v: k for k, v in remap.items()}                    # 板の R → 提供データの no(ずれる日)
    for no in sorted(buckets):
        items = sorted(buckets[no], key=lambda x: x.get("at", 99))
        kno = back.get(no, no)
        kr = next((r for r in kb_races if r.get("no") == kno), None)
        bd = next((b for b in boards if b.get("no") == no), None)
        # ⚠ずれる日は**板の距離**を先に見る(その R の実物なので)
        dist = ((bd or {}).get("dist") or (kr or {}).get("dist") if by_board
                else (kr or {}).get("dist") or (bd or {}).get("dist")) or items[0].get("dist")
        race = {"no": no, "rows": [x["row"] for x in items]}
        if dist:
            race["dist"] = dist
        races.append(race)
    if unknown:
        races.append({"no": None, "kind": UNKNOWN_KIND, "rows": [x["row"] for x in unknown]})
    stat["races"] = len([r for r in races if r.get("no") is not None])
    stat["unknown"] = len(unknown)
    # ⛔公式の塊も残す(情報を潰さない)。⚠2 度目からは day["races"] が組み直し済みなので
    #   **すでにある official_groups を上書きしない**(でないと公式の塊が消える)
    day.setdefault("official_groups", official)
    day["races"] = races
    return stat


def hyogo_split(days, split):
    """兵庫の日を split(提供データ)で組み直す。split に無い日は **no を外す**。
    返り値 = (組み直した日数, 組不明の行がある日の一覧)"""
    got = (split or {}).get("days") or {}
    done, warn = 0, []
    for d in days:
        sp = got.get(str(d.get("date")))
        if not sp:
            for r in (d.get("races") or []):
                r.pop("no", None)                             # ⛔偽の番号を残さない
            continue
        st = hyogo_split_day(d, sp)
        done += 1
        if st.get("mode") == "板のR":
            warn.append("%s %s: **板の R で組んだ**(%dレース / 提供データのレースを板に付け替えた行 %d)%s"
                        % (d.get("date"), d.get("venue"), st["races"], st["by_board_race"],
                           ("/ 割れたレース " + " ・ ".join(st["split_up"])) if st["split_up"] else ""))
        if st["unknown"] or st["kb_missing"]:
            warn.append("%s %s: %dレース / 提供データに無い行 %d(うち板で当てた %d)"
                        "/ 組不明 %d%s%s" % (d.get("date"), d.get("venue"), st["races"],
                                            st["kb_missing"], st["by_board"], st["unknown"],
                                            ("/ 同名2頭 %d" % st["dup"]) if st["dup"] else "",
                                            ("/ 公式と値が違う行 %d" % st["conflict"]) if st["conflict"] else ""))
    return done, warn


def load_hyogo_split(path, base, key):
    """split の出どころ= --split-file の JSON(手元)か nar_meta の hyogo_noken_split(cloud)。"""
    if path:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log(f"  兵庫: --split-file が読めない({type(e).__name__})= 組み直さない")
            return {}
    if not base or not key:
        return {}
    try:
        return sb_get_meta(base, key, HYOGO_SPLIT_KEY) or {}
    except Exception as e:                                       # noqa: BLE001
        log(f"  兵庫: {HYOGO_SPLIT_KEY} が読めない({type(e).__name__})= 組み直さない")
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue", default="all", choices=["all"] + ORDER)
    ap.add_argument("--backfill", action="store_true", help="全量を取り直す")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="days を <ここ>/{venue}_noken.json に書き出す(投入とは別)")
    ap.add_argument("--env")
    ap.add_argument("--split-file", help="§117e 兵庫のレース割り(提供データ)の JSON。"
                                          "省くと nar_meta の hyogo_noken_split を読む")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if (not base or not key) and not args.dry_run:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い(--dry-run なら鍵なしで動く)")
        return 2

    rc = 0
    for name in (ORDER if args.venue == "all" else [args.venue]):
        meta_key, collect, key_set, day_key = VENUES[name]
        stored = (sb_get_meta(base, key, meta_key) if base and key else None) or {"days": []}
        existing = key_set(stored["days"])
        try:
            got = collect(existing, args.backfill)
            # §117b 南関の一部は (days, offsets) を返す。offsets は **別の鍵**へ書く
            new_days, new_offsets = got if isinstance(got, tuple) else (got, None)
        except Exception as e:
            log(f"{name}: 索引の取得に失敗 {type(e).__name__}: {str(e)[:150]}")
            rc = 2
            continue
        if args.backfill:
            merged = new_days
        else:
            merged = stored["days"] + new_days
        # 日付降順・同一キーは新しい方
        seen, days = set(), []
        for d in sorted(merged, key=lambda x: x["date"], reverse=True):
            k = day_key(d)
            if k in seen:
                continue
            seen.add(k)
            days.append(d)
        log(f"{name}: 新規 {len(new_days)} 日 / 合計 {len(days)} 日")
        # §117e 兵庫= 公式の行を「本当のレース」に入れ直す(split が無い日は no を外す)
        split_changed = False
        if name == "hyogo":
            before = json.dumps(days, ensure_ascii=False, sort_keys=True)
            n_done, warn = hyogo_split(days, load_hyogo_split(args.split_file, base, key))
            split_changed = json.dumps(days, ensure_ascii=False, sort_keys=True) != before
            log(f"{name}: レース割り {n_done} 日 / 割りの無い日は no を外した(全 {len(days)} 日)")
            for w in warn:
                log("  " + w)
        # §117g 笠松= 公式のプレイリストをレース別の動画に解く(まだ付いていない日だけ開く)
        vid_days = 0
        if name == "kasamatsu":
            vid_days, lines = kasa_videos(days)
            for line in lines:
                log("  " + line)
        added = 0
        if name in CHIHOU_ENRICH:
            added, missed = chihou_enrich(name, days)
            log(f"{name}: 旧 DB から 着順・馬番・上がり3F・通過・馬場・天候 を補完= 足した行 {added} / 当たらない行 {missed}")
        offs = None
        if new_offsets:
            okey = f"{meta_key}_offsets"
            kept = (sb_get_meta(base, key, okey) if base and key else None) or {"days": {}}
            offs = dict(kept.get("days") or {})
            offs.update(new_offsets)
            log(f"{name}: 頭出し 新規 {len(new_offsets)} 日 / 合計 {len(offs)} 日")
        if args.out:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            path = out / f"{name}_noken.json"
            path.write_text(json.dumps({"days": days}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            log(f"{name}: {path} に書き出し")
            if offs:
                opath = out / f"{name}_noken_offsets.json"
                opath.write_text(json.dumps({"days": offs}, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
                log(f"{name}: {opath} に書き出し")
        if args.dry_run:
            continue
        # §117b-2 新しい日が無くても、旧 DB からの補完が増えた(手元ジョブが追いついた)ときは書く
        if new_days or added or split_changed or vid_days:
            status, msg = upsert(base, key, "nar_meta", "key",
                                 [{"key": meta_key, "value": {"days": days},
                                   "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
            if status not in (200, 201):
                log(f"{name}: 投入失敗 {status} {msg}")
                rc = 1
            else:
                log(f"{name}: nar_meta/{meta_key} 更新")
        if offs:
            status, msg = upsert(base, key, "nar_meta", "key",
                                 [{"key": f"{meta_key}_offsets", "value": {"days": offs},
                                   "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}])
            if status not in (200, 201):
                log(f"{name}: 頭出しの投入失敗 {status} {msg}")
                rc = 1
            else:
                log(f"{name}: nar_meta/{meta_key}_offsets 更新")
    return rc


if __name__ == "__main__":
    sys.exit(main())
