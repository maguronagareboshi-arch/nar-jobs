# -*- coding: utf-8 -*-
"""本体 cloud: 騎手・調教師のプロフィール(生年月日・所属)を nar_persons へ入れる(DESIGN §65 / §54.2)。

公式 keiba.go.jp の DataRoom に**一覧ページ**がある(2026-08-30 実測。8/29 の設計より楽な道):
  一覧 `DataRoom/RiderList?k_pageNum=N&k_nameCondition=include&k_genneki_flag=1&k_shozoku=*&k_sei=`
       50人/ページ・行に k_riderLicenseNo と氏名。⛔`k_genneki_flag=1` で**現役だけ**(騎手400/調教師612)
       ⛔**k_flag は付けない**= あれはページ送りの向き(1=次へ)で、付けると先頭50人が取れない
  個票 `DataRoom/RiderMark?k_riderLicenseNo=N` に**生年月日**(実測 38070 西謙一= 1986/03/04)
  調教師は TrainerList / TrainerMark?k_trainerLicenseNo=N で**同じ形**(実測 18026 西春夫= 1948/01/17)

  py -3 -X utf8 cloud/persons.py                                   # ドライラン(既定)。一覧だけ読んで数える
  py -3 -X utf8 cloud/persons.py --full                            # 個票まで読む(1,012ページ・約20分)
  py -3 -X utf8 cloud/persons.py --env pipeline/.env.nar --full --apply   # 実弾(nar_persons へ upsert)
  py -3 -X utf8 cloud/persons.py --env pipeline/.env.nar --verify  # オラクル= nar_person_stats.name との突合
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY(--apply と --verify で使う)
終了コード: 0 正常 / 1 投入失敗 / 2 前提の読み取りに失敗

⛔ 実地で分かったこと(2026-08-30):
 1. ⛔ページに `meta charset` が無いが**中身は UTF-8**。cp932 で読むと化ける=**明示して読む**。
 2. 氏名は全角空白で飾られている(例 `江　田　　照　男`)。
    ⛔**2つ以上の空白が姓と名の切れ目**。1つの空白は字間の飾り。
 3. ⭐出典(nar_runs.jockey)の略し方= **姓[:2] + 名[:3-len(姓[:2])]**(必ず3文字)。
    佐々木大輔→佐々大 / 山本聡哉→山本聡 / 西謙一→西謙一 / 長谷川剛史→長谷剛。
 4. ⛔略称は**一意ではない**(#X1)。⛔**2つの数がある**= ①この表の中で行が重なる略称は**12組**
    (騎手4・調教師8) ②そのうち**nar_person_stats に行がある(=成績が実際に混ざっている)**のは**8組**。
    ⚠`加藤和` は**3行**(「加藤和宏」が生年月日の違う2人)。⚠**画面はその略称に生年月日を出さない**
    (⛔一覧を持たず**引いた行が1行でなければ出さない**で判定している= 増えても直さなくてよい)。
 5. ⚠公式の一覧に**同姓同名で番号が2つ**ある人がいる(実測: 調教師「加藤和宏」)。名寄せしない=番号のまま持つ。
 6. `/KeibaWeb/DataRoom/` は高知 Worker の PROXY_PATHS に無い。**サーバ側から取る前提**(画面から直は不可)。
 7. ⛔一覧の `No.` は**絞り込む前の通し番号**なので、現役だけに絞ると 51 から始まる。件数と突き合わせるときは
    `検索結果: N 件`(騎手400・調教師612)を見る。⛔`No.` を人数と読み違えない。
"""

import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://www.keiba.go.jp/KeibaWeb/DataRoom"
WAIT = 1.2                       # ⛔取得間隔(§54.1 と同じ礼儀)
PER_PAGE = 50

KINDS = {
    "jockey":  {"list": "RiderList",   "mark": "RiderMark",   "param": "k_riderLicenseNo",   "label": "騎手"},
    "trainer": {"list": "TrainerList", "mark": "TrainerMark", "param": "k_trainerLicenseNo", "label": "調教師"},
}


def log(msg):
    print(msg, flush=True)


def load_env(path):
    for raw in io.open(path, encoding="utf-8").read().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get(url):
    """⛔UTF-8 と決め打って読む(ページに charset の宣言が無い)。"""
    r = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(r, timeout=40) as x:
        return x.read().decode("utf-8", errors="replace")


def req(base, key, path, method="GET", body=None):
    r = urllib.request.Request(base + path, method=method, data=body, headers={
        "apikey": key, "Authorization": "Bearer " + key, "User-Agent": UA,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(r, timeout=90) as x:
        return x.status, x.read().decode("utf-8")


def text_lines(html):
    h = re.sub(r"(?s)<(script|style).*?</\1>", " ", html)
    return [x.strip() for x in re.sub(r"<[^>]+>", "\n", h).split("\n") if x.strip()]


def split_name(raw):
    """飾りの空白を落として (姓, 名)。⛔2つ以上の空白が切れ目・1つは字間。"""
    parts = [re.sub(r"[\s　]", "", p) for p in re.split(r"[\s　]{2,}", raw)]
    parts = [p for p in parts if p]
    if len(parts) >= 2:
        return parts[0], "".join(parts[1:])
    return ("".join(parts), "")


def short_name(sei, mei):
    """⭐nar_runs と同じ3文字の略称= 姓[:2] + 名[:3-len(姓[:2])]。"""
    a = sei[:2]
    return (a + mei[:max(0, 3 - len(a))])[:3]


def fetch_list(kind, active_only=True):
    """{license_no: 生の氏名} を全ページぶん。ページ数は1ページ目の総件数から決める。"""
    cfg = KINDS[kind]
    flag = "1" if active_only else "*"
    out, page, total = {}, 1, None
    while True:
        # ⛔k_flag は**ページ送りの向き**(1=次へ / -1=前へ)。付けると1ページぶんずれて
        #   先頭の50人が永久に取れない(2026-08-30 実測: k_flag=1 だと 350/400 しか取れなかった)。
        #   ⛔付けないのが「そのページを見る」の意味。
        url = (f"{BASE}/{cfg['list']}?k_pageNum={page}&k_nameCondition=include"
               f"&k_genneki_flag={flag}&k_shozoku=*&k_sei=")
        html = get(url)
        found = dict(re.findall(cfg["param"] + r"=(\d+)[^>]*>([^<]+)<", html))
        if not found:
            break
        before = len(out)
        out.update({k: v.strip() for k, v in found.items()})
        if total is None:
            m = re.search(r"検索結果:\s*</?[^>]*>?\s*([0-9,]+)", re.sub(r"\s+", " ", html))
            total = int(m.group(1).replace(",", "")) if m else None
        # ⛔新しい人が1人も増えないページまで来たら終わり(ページ送りの上限に当たった合図)
        if len(out) == before:
            break
        page += 1
        if page > 60:            # 安全弁(50人×60ページ= 3,000人)
            log(f"  ⚠{cfg['label']}: ページが60を超えたので止めます")
            break
        time.sleep(WAIT)
    return out, total


def fetch_profile(kind, license_no):
    """{birth, area, name_full} 。取れない項目は None。"""
    cfg = KINDS[kind]
    t = text_lines(get(f"{BASE}/{cfg['mark']}?{cfg['param']}={license_no}"))
    out = {"birth": None, "area": None}
    for i, x in enumerate(t):
        if x == "生年月日" and i + 1 < len(t):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", t[i + 1])
            if m:
                out["birth"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        elif x == "所属" and i + 1 < len(t) and out["area"] is None:
            out["area"] = t[i + 1][:20]
    return out


def collect(kind, full, limit=None):
    cfg = KINDS[kind]
    listed, total = fetch_list(kind)
    log(f"[{cfg['label']}] 一覧= {len(listed)} 人(公式の総件数 {total})")
    rows, dup = [], {}
    for lic, raw in listed.items():
        sei, mei = split_name(raw)
        s = short_name(sei, mei)
        dup.setdefault(s, []).append(sei + mei)
        rows.append({"kind": kind, "license_no": lic, "name_full": sei + mei,
                     "name_sei": sei, "name_mei": mei, "name_short": s,
                     "birth": None, "area": None, "active": True})
    amb = {k: v for k, v in dup.items() if len(set(v)) > 1}
    log(f"  ⛔略称が同じ別人: {len(amb)} 組 " + json.dumps(amb, ensure_ascii=False))
    if not full:
        log("  (ドライラン: 個票は読んでいません。--full で読みます)")
        return rows, amb
    n = 0
    for r in rows:
        if limit and n >= limit:
            break
        try:
            p = fetch_profile(kind, r["license_no"])
            r["birth"], r["area"] = p["birth"], p["area"]
        except Exception as e:                       # 1人読めなくても止めない
            log(f"  ⚠{r['name_full']}({r['license_no']}) を読めません: {e}")
        n += 1
        if n % 50 == 0:
            log(f"  … {n}/{len(rows)}")
        time.sleep(WAIT)
    got = sum(1 for r in rows if r["birth"])
    log(f"  生年月日が取れた: {got}/{len(rows)}")
    return rows, amb


def apply_rows(base, key, rows):
    body = json.dumps([{k: v for k, v in r.items()} for r in rows], ensure_ascii=False).encode("utf-8")
    st, txt = req(base, key, "/rest/v1/nar_persons?on_conflict=kind,license_no", "POST", body)
    if st >= 300:
        log(f"⛔投入に失敗 status={st} {txt[:300]}")
        return False
    return True


def verify(base, key, rows):
    """オラクル= nar_person_stats.name(=nar_runs 由来)と name_short がどれだけ当たるか。"""
    ok = True
    for kind in KINDS:
        mine = set()
        st, txt = req(base, key,
                      f"/rest/v1/nar_person_stats?select=name&kind=eq.{kind}"
                      f"&track=eq.all&period=eq.all&limit=2000")
        if st < 300:
            mine = {r["name"] for r in json.loads(txt)}
        made = {}
        for r in rows:
            if r["kind"] == kind:
                made.setdefault(r["name_short"], []).append(r["name_full"])
        hit = [k for k in made if k in mine]
        amb = [(k, v) for k, v in made.items() if len(set(v)) > 1 and k in mine]
        log(f"[{KINDS[kind]['label']}] 突合: 当たり {len(hit)} / 公式 {len(made)} / DB {len(mine)}"
            f" / ⛔曖昧 {len(amb)} " + json.dumps([k for k, _ in amb], ensure_ascii=False))
        if mine and not hit:
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env")
    ap.add_argument("--full", action="store_true", help="個票(生年月日)まで読む。1,012ページ・約20分")
    ap.add_argument("--apply", action="store_true", help="nar_persons へ upsert(--full と一緒に使う)")
    ap.add_argument("--verify", action="store_true", help="nar_person_stats.name との突合だけ見る")
    ap.add_argument("--limit", type=int, default=0, help="個票を読む人数の上限(試すとき用)")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if (a.apply or a.verify) and not (base and key):
        log("⛔SUPABASE_URL / SUPABASE_SERVICE_KEY がありません")
        return 2

    allrows = []
    for kind in KINDS:
        try:
            rows, _ = collect(kind, full=a.full, limit=a.limit or None)
        except Exception as e:
            log(f"⛔{KINDS[kind]['label']} の一覧を読めません: {e}")
            return 2
        allrows += rows

    if a.verify:
        return 0 if verify(base, key, allrows) else 1
    if not a.apply:
        log("(ドライラン。--apply で投入します)")
        return 0
    if not a.full:
        log("⛔--apply は --full と一緒に使ってください(生年月日が空のまま入るため)")
        return 2
    for i in range(0, len(allrows), 200):
        if not apply_rows(base, key, allrows[i:i + 200]):
            return 1
    log(f"投入しました: {len(allrows)} 行")
    return 0 if verify(base, key, allrows) else 1


if __name__ == "__main__":
    sys.exit(main())
