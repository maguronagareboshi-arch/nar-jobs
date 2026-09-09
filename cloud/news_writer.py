# -*- coding: utf-8 -*-
"""統合ビューア cloud: 主催者公式の発表を**読んで・要約して・うちのページに結びつけて**下書きに溜める(§140 段 1)。

  A 集める  cloud/official_news.py(§139・既存)→ nar_meta key='official_news'
  B 読む    候補 URL の本文を取る(HTML の <main>/<article>・PDF は 3 ページまで)      ← ここから
  C 書く    LLM に「要約+種別+固有名詞」を JSON で書かせる(⛔鍵は Actions の secret)
  D 結ぶ    固有名詞 → うちのページ(nar を eq で 1 行引くだけ。⛔LLM に URL を作らせない)
  E 溜める  news_drafts(旧プロジェクト・status=draft)。⛔ここまでは公開に 1 文字も触れない
  F 承認    /admin(段 2)      G 焼く  approved → data/news/*.md(段 3)

  py -3.12 -X utf8 cloud/news_writer.py --dry-run --fake tests/fixtures/news_writer/llm_ok.json
      = 収集役の結果を読み、公式の本文を取り、偽の LLM 返答で下書きを**標準出力に出すだけ**
  py -3.12 -X utf8 cloud/news_writer.py --items tests/fixtures/news_writer/items.json --dry-run
      = 収集役も読まずに手元の JSON で試す(通信は公式ページの取得だけ)
  python cloud/news_writer.py --apply                      # 便(nar-jobs)。⛔鍵が要る

環境変数:
  OLD_SUPABASE_URL / OLD_SUPABASE_SERVICE_KEY   news_drafts(旧プロジェクト)= 書き込み先
  SUPABASE_URL / SUPABASE_SERVICE_KEY           nar(official_news の読みと D の照合)= 読むだけ
  ANTHROPIC_API_KEY                             無ければ C を飛ばして status='nobody' で溜める
  --env <path> で .env 型のファイルからも読める(official_news.py の load_env と同じ)

終了コード: 0 正常(0 本でも) / 1 DB 書き込み失敗 / 2 official_news が読めない

⛔守ること(設計 docs/proposal_s140_official_news_pipeline_20260909.md §5):
 1. 公式の文を写さない= LLM を信じず**機械で**検査する(本文と公式本文の最長共通部分文字列 ≤ 40 字)。
 2. 他社名を書かない(出典は「公式」)。⛔閲覧者向けの字に他社名を出さない(2026-09-05 指示)。
 3. うちのページへの結びつけは**一致したものだけ**。⛔推定しない・⛔LLM に URL を作らせない。
 4. 1 本の失敗で便を止めない(本文が取れなくても行は残す= 情報を潰さない)。
 5. 本番 DB に重い SQL を流さない= D の照合は全部 eq の 1 行読み。
"""

import argparse
import datetime as dt
import html as _html
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
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# ⛔UA・文字コードの順・.env の読み方は**収集役と同じもの**を使う(2 か所目を作らない)
import official_news as ON                       # noqa: E402

TABLE = "news_drafts"
TIMEOUT = ON.TIMEOUT

# ---------------------------------------------------------------- 場の表
# ⛔js/data.js の VENUES と同じ字(画面の場名)。ここを足すときは向こうも見る。
VENUE_NAME = {
    "obihiro": "帯広", "monbetsu": "門別", "morioka": "盛岡", "mizusawa": "水沢",
    "urawa": "浦和", "funabashi": "船橋", "ooi": "大井", "kawasaki": "川崎",
    "kanazawa": "金沢", "kasamatsu": "笠松", "nagoya": "名古屋", "sonoda": "園田",
    "himeji": "姫路", "kochi": "高知", "saga": "佐賀",
}
# ⚠帯広だけ nar_races の track が **'帯広ば'**(js/data.js:216 の NAR_TRACK_ALIAS と同じ)。
#   画面に出す字は「帯広」のままで、DB を引くときだけこちらを使う。
NAR_TRACK = dict(VENUE_NAME, obihiro="帯広ば")

# ---------------------------------------------------------------- B 読む
# ⛔役所の定型だけを落とす。収集役の DROP/KINDS は**使わない**(あれは索引用で、
#   「募集」「場外発売」「結果」まで落としてしまう= 2026-09-09 の誤爆 2 件)。
#   要るか要らないかは C が本文を見て決める(語で決めない)。
DROP_HARD = ["入札", "公告", "調達", "契約", "工事", "採用", "任免", "職員", "会計年度"]
BODY_MAX = 6000          # 公式本文はここで切る(LLM に渡す上限でもある)
MAX_NEW = 30             # 1 便で新しく読むのはここまで
SLEEP = 0.5              # 1 本ごとに空ける秒(⛔公式の迷惑にならないように)
PDF_PAGES = 3            # PDF はここまで
SHORT_BODY = 200         # これ未満なら「中身は PDF」を疑う(佐賀の概定番組・金沢の選定馬の型)

_DROP_TAGS = ("script", "style", "nav", "header", "footer", "aside")
# 段落の切れ目だけ空白にする。⛔強調などの内側のタグは詰める(official_news.clean と同じ)=
#   ここで空白を入れると「公式の本文と同じか」の検査がゆるくなる
_BLOCK_END = r"</(?:p|div|li|tr|h[1-6]|section|table|dd|dt|blockquote)\s*>|<br\s*/?>"


def decode(raw):
    """bytes → 字。⛔utf-8 → cp932 → euc-jp の順(official_news.fetch と同じ)"""
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def fetch_raw(url):
    """(bytes, Content-Type)。PDF かどうかを見たいので official_news.fetch と違って bytes のまま返す"""
    req = urllib.request.Request(url, headers={"User-Agent": ON.UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read(), (res.headers.get("Content-Type") or "")


def extract_text(html_text):
    """公式ページの HTML → 本文の字(≤ BODY_MAX)。

    ① script/style/nav/header/footer/aside は中身ごと落とす
    ② <main> か <article> があれば**その中だけ**(最初の 1 つ)
    ③ タグを落とし実体参照を戻し空白を畳む
    """
    t = html_text or ""
    for tag in _DROP_TAGS:
        t = re.sub(r"<%s\b[^>]*>.*?</%s\s*>" % (tag, tag), " ", t, flags=re.S | re.I)
    for tag in ("main", "article"):
        m = re.search(r"<%s\b[^>]*>(.*?)</%s\s*>" % (tag, tag), t, flags=re.S | re.I)
        if m:
            t = m.group(1)
            break
    t = re.sub(_BLOCK_END, " ", t, flags=re.I)
    t = re.sub(r"<[^>]*>", "", t)
    t = _html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()[:BODY_MAX]


def pdf_text(raw):
    """PDF の bytes → 字(PDF_PAGES ページまで)。⛔読めなくても例外にしない"""
    try:
        import pdfplumber                        # requirements にある(⛔ここでだけ要る)
    except Exception:                            # noqa: BLE001
        return ""
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = [(p.extract_text() or "") for p in pdf.pages[:PDF_PAGES]]
    except Exception:                            # noqa: BLE001
        return ""
    return re.sub(r"\s+", " ", " ".join(pages)).strip()


def pdf_links(html_text, base):
    """本文ページの中の PDF リンク(絶対 URL・重複なし)"""
    out, seen = [], set()
    for m in re.finditer(r'href="([^"]+\.pdf[^"]*)"', html_text or "", flags=re.I):
        u = ON.abs_url(base, _html.unescape(m.group(1)))
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_pdf(url, ctype):
    return (url or "").lower().split("?")[0].endswith(".pdf") or "pdf" in (ctype or "").lower()


def read_source(url):
    """公式ページ → (本文 or None, 取れなかった理由 or None)。⛔例外を投げない(便を止めない)"""
    try:
        raw, ctype = fetch_raw(url)
    except Exception as e:                       # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)
    if is_pdf(url, ctype):
        body = pdf_text(raw)
        return (body[:BODY_MAX] or None), (None if body else "PDF から字が取れない")
    html_text = decode(raw)
    body = extract_text(html_text)
    # 本文が短くて PDF リンクが**ちょうど 1 本**なら、その PDF も読んで後ろに足す
    # (佐賀の概定番組・金沢の選定馬= ページは見出しだけで中身が PDF の型)
    if len(body) < SHORT_BODY:
        links = pdf_links(html_text, url)
        if len(links) == 1:
            try:
                praw, _ = fetch_raw(links[0])
                extra = pdf_text(praw)
            except Exception:                    # noqa: BLE001
                extra = ""
            if extra:
                body = (body + " " + extra).strip()[:BODY_MAX]
    return (body or None), (None if body else "本文 0 字(画像だけの発表の可能性)")


# ---------------------------------------------------------------- C 書く(LLM)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1500
KIND_SET = ("person", "horse", "venue", "race")
COPY_MAX = 40            # 公式本文とそのまま同じでよい上限(字)
TITLE_MAX = 60
LEDE_MAX = 120
# ⛔閲覧者向けの字に他社名を出さない(2026-09-05 指示)。出どころは「公式」と呼ぶ
COMPETITION_NAMES = ["競馬ブック", "netkeiba", "楽天", "オッズパーク", "SPAT4"]

# ⛔この文言は設計の正本(docs/opus_s140_news_writer_20260909.md §3)。基準はユーザーの 9/9 判定。
SYSTEM_PROMPT = (
    "あなたは地方競馬の情報サイトの編集者です。主催者(競馬場の公式)が出した発表を読み、読者向けの短い記事の下書きを JSON で返します。\n"
    "【出す価値がある発表】騎手・調教師の「〇〇勝達成」「期間限定騎乗」「デビュー」「引退」「移籍」「騎乗停止」「減量の変更」/\n"
    "馬の「能力検査の結果」「重賞の出走予定馬・選定馬」「遠征(予定・結果)」「転入・転出」/ 開催の「中止」「取り止め」「変更」「日程」「砂厚」「馬場」/\n"
    "レースの「番組編成」「格付け」「ネーミングライツ」「新設競走」/「事故による競走除外」「出走制限」「場外発売所の閉所」。\n"
    "【出さない発表】プレゼント・イベント・著名人予想・動画配信・リーディング・「出来事」・「本日の開催情報」・募金・入札・職員募集。\n"
    "迷ったら worth=true にしてください(人が最終判断します)。\n"
    "【書き方】発表の文をそのまま写さない(固有名詞・数字・日付以外は自分の言葉で)。発表に無いことを書かない・推測しない。敬体。\n"
    "他社名・他サイト名を書かない(出典は「公式」と呼ぶ)。専門用語は平易に。\n"
    "本文は次の 4 つだけで書く: 段落 / 行頭「- 」の箇条書き / [文字](https://…) のリンク / 「|」区切りの表(1 行目 見出し・2 行目 各セル「---」)。\n"
    "【返す JSON】{\"worth\":bool,\"kinds\":[\"person\"|\"horse\"|\"venue\"|\"race\" を 1 つ以上],\"title\":\"60字以内\",\"lede\":\"1 文 120 字以内\",\n"
    "\"body\":\"2〜4 段落(表が要る発表は表)\",\"entities\":{\"jockeys\":[],\"trainers\":[],\"horses\":[],\"venues\":[\"kochi\" のような場の英字],\"dates\":[\"YYYY-MM-DD\"]},\"why\":\"1 行\"}"
)


def venue_label(prefixes):
    """['morioka','mizusawa'] → '盛岡・水沢'(知らない字はそのまま出す= 情報を潰さない)"""
    return "・".join(VENUE_NAME.get(p, p) for p in (prefixes or [])) or "不明"


def user_prompt(item, body):
    vs = item.get("v") or []
    return ("場: %s(%s)\n公式の日付: %s\n見出し: %s\n本文:\n%s"
            % (venue_label(vs), "/".join(vs), item.get("d") or "", item.get("t") or "",
               body or "(本文は取れませんでした)"))


def parse_json(text):
    """LLM の返事 → dict。前後の字を剥がす。読めなければ None"""
    s = (text or "").strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        out = json.loads(s[i:j + 1])
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def write_one(item, body, *, client):
    """1 件 → LLM の dict(⛔鍵が無い= client is None なら呼ばずに None)。壊れていたら 1 回だけ再試行"""
    if client is None:
        return None
    user = user_prompt(item, body)
    for again in (False, True):
        try:
            text = client(SYSTEM_PROMPT, user)
        except Exception:                        # noqa: BLE001
            if again:
                return None
            continue
        got = parse_json(text)
        if got is not None:
            return got
    return None


def anthropic_client(api_key):
    """(system, user) → 返事の字。⛔鍵に触るのはここだけ"""
    import anthropic                             # requirements にある(⛔便でだけ要る)
    cl = anthropic.Anthropic(api_key=api_key)

    def call(system, user):
        res = cl.messages.create(model=MODEL, max_tokens=MAX_TOKENS, temperature=0,
                                 system=system, messages=[{"role": "user", "content": user}])
        return "".join(getattr(b, "text", "") for b in res.content)
    return call


def fake_client(path):
    """fixture の dict をそのまま返す偽 client(試験と手元のドライラン用・⛔通信しない)"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    def call(system, user):
        return json.dumps(data, ensure_ascii=False)
    return call


def lcs_len(a, b):
    """最長共通部分文字列の長さ。

    ⛔6,000 字 × 1,500 字の総当たり表は重いので、**長さで二分探索**して集合で当てる
    (長さ L の共通部分があるかは L について単調)。
    """
    a, b = a or "", b or ""
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        pool = {a[i:i + mid] for i in range(len(a) - mid + 1)}
        if any(b[i:i + mid] in pool for i in range(len(b) - mid + 1)):
            lo = mid
        else:
            hi = mid - 1
    return lo


def check_draft(d, body):
    """⛔prompt を信じない。機械で見て、落ちた検査名を並べて返す(空なら合格)"""
    bad = []
    if not isinstance(d, dict):
        return ["返事が JSON の物ではない"]
    if not isinstance(d.get("worth"), bool):
        bad.append("worth が true/false でない")
    kinds = d.get("kinds")
    if (not isinstance(kinds, list) or not kinds
            or any(k not in KIND_SET for k in kinds)):
        bad.append("kinds が person/horse/venue/race の 1 つ以上でない")
    title = d.get("title") if isinstance(d.get("title"), str) else ""
    if not 1 <= len(title.strip()) <= TITLE_MAX:
        bad.append("title が 1〜%d 字でない(%d 字)" % (TITLE_MAX, len(title.strip())))
    lede = d.get("lede") if isinstance(d.get("lede"), str) else ""
    ls = lede.strip()
    if not 1 <= len(ls) <= LEDE_MAX:
        bad.append("lede が 1〜%d 字でない(%d 字)" % (LEDE_MAX, len(ls)))
    elif ls.count("。") != 1 or not ls.endswith("。"):
        bad.append("lede が 1 文でない(。は末尾に 1 つだけ)")
    text = d.get("body") if isinstance(d.get("body"), str) else ""
    if not text.strip():
        bad.append("body が空")
    elif "<" in text:
        bad.append("body に < がある(タグは書かない)")
    elif "![" in text or any(re.match(r"\s*(#|>|\*|\+|\d+\.)\s", ln)
                             for ln in text.split("\n")):
        bad.append("body が 4 規則の外(見出し・引用・番号つき・画像)")
    if body and text:
        n = lcs_len(text, body)
        if n > COPY_MAX:
            bad.append("公式の本文と %d 字そのまま同じ(上限 %d 字)" % (n, COPY_MAX))
    joined = " ".join([title, lede, text])
    for w in COMPETITION_NAMES:
        if w in joined:
            bad.append("他社名が入っている(%s)" % w)
    return bad


# ---------------------------------------------------------------- D 結ぶ(nar を読むだけ)

RELATED_MAX = 5
NOKEN_WORDS = ("能力検査", "能検")


def _name(s):
    """⛔空白(半角・全角)を除いた完全一致で引く= 公式の表記ゆれで外さない"""
    return re.sub(r"[\s　]+", "", str(s or "")).strip()


def _q(s):
    return urllib.parse.quote(str(s), safe="")


def person_link(kind, nm, nar):
    """騎手・調教師の名前 → うちのページの名前(略称)。⛔当たらなければ None

    ⚠公式のお知らせは**フルネーム**(高橋利幸)、うちの人物ページは **nar_runs 由来の略称**(高橋利)。
      ここを合わせないと騎手の話が 1 本も結べない= まず nar_persons.name_full で略称に直す。
    ⛔**nar_runs を名前で引かない**= 索引が無く、**当たらない名前で全表走査**になる
      (2026-09-09 実測: `nar_runs?jockey=eq.<居ない名前>` は **3.1 秒で HTTP 500**)。
      画面の騎手ページと同じ `nar_person_stats`(集計済み)なら当たり 138ms / 外れ 69ms。
    """
    rows = nar("nar_persons?select=name_short&kind=eq.%s&name_full=eq.%s&limit=2" % (kind, _q(nm)))
    # ⛔同じフルネームが 2 行= どちらか分からないので直さずそのまま試す(⛔別人に飛ばさない)
    name = rows[0].get("name_short") if len(rows) == 1 and rows[0].get("name_short") else nm
    if nar("nar_person_stats?select=name&kind=eq.%s&name=eq.%s&limit=1" % (kind, _q(name))):
        return name
    return None


def relate(entities, *, nar, kinds=(), title=""):
    """固有名詞 → うちのページ [{label, path}](≤5)。⛔一致しないものは付けない・失敗したら []

    ⚠`kinds` と `title` は能検の行(§4 の 5 行目)にだけ要る。設計の呼び方
      `relate(entities, nar=nar)` はそのまま通る(既定あり)。
    """
    e = entities if isinstance(entities, dict) else {}
    out = []

    def add(label, path):
        if len(out) < RELATED_MAX and not any(r["path"] == path for r in out):
            out.append({"label": label, "path": path})

    try:
        for who, kind, word in (("jockeys", "jockey", "騎手"), ("trainers", "trainer", "調教師")):
            for raw in (e.get(who) or [])[:RELATED_MAX]:
                if len(out) >= RELATED_MAX:
                    break
                nm = _name(raw)
                if not nm:
                    continue
                got = person_link(kind, nm, nar)
                if got:
                    add("%s %sの成績" % (got, word), "/%s/%s" % (kind, _q(got)))
        for raw in (e.get("horses") or [])[:RELATED_MAX]:
            if len(out) >= RELATED_MAX:
                break
            nm = _name(raw)
            if not nm:
                continue
            # ⛔同名 2 頭のときは付けない(別の馬のページへ飛ばさない)= ちょうど 1 行のときだけ
            rows = nar("nar_horses?select=horse_name&horse_name=eq.%s&limit=2" % _q(nm))
            if len(rows) == 1:
                # ⚠/horse/:id は**素の馬名ではない**。js/data.js:2049 getHorse は
                #   kb:/kochi:/name:/nar:/narb: で始まる id しか受けない(素の名前は null=空ページ)。
                #   nar_horses に居る馬は nar_runs にも居るので 'nar:<馬名>' が正しい id。
                add("%s の成績" % nm, "/horse/%s" % _q("nar:" + nm))
        vs = [v for v in (e.get("venues") or []) if v in VENUE_NAME]
        ds = [d for d in (e.get("dates") or []) if re.match(r"^\d{4}-\d{2}-\d{2}$", str(d or ""))]
        for v in vs:
            for d in ds:
                if len(out) >= RELATED_MAX:
                    break
                # ⚠列は track(場の**和名**)と race_date。⛔venue/date という列は無い
                if nar("nar_races?select=race_date&track=eq.%s&race_date=eq.%s&limit=1"
                       % (_q(NAR_TRACK[v]), d)):
                    y, mo, da = d.split("-")
                    add("%s %d月%d日 の出馬表" % (VENUE_NAME[v], int(mo), int(da)),
                        "/venue/%s/%s" % (v, d))
        if "horse" in (kinds or ()) and any(w in (title or "") for w in NOKEN_WORDS):
            for v in vs:
                add("%s の能力検査" % VENUE_NAME[v], "/noken/%s" % v)
    except Exception:                            # noqa: BLE001
        return []                                # ⛔照合が落ちても便は止めない
    return out[:RELATED_MAX]


# ---------------------------------------------------------------- REST(読み・書き)


def rest_get(base, key, path):
    """GET /rest/v1/<path> → list。⛔失敗は例外(呼び手が決める)"""
    req = urllib.request.Request(
        base.rstrip("/") + "/rest/v1/" + path,
        headers={"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        out = json.loads(res.read().decode("utf-8"))
    return out if isinstance(out, list) else []


def insert_drafts(base, key, rows):
    """⛔既にある source_url は**書かない**(人が直した行を上書きしない)"""
    body = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/rest/v1/%s?on_conflict=source_url" % TABLE,
        data=body, method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "Prefer": "resolution=ignore-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.status


# ⛔公開の anon キー(js/data.js:18-19 と同じ。閲覧専用・RLS で select だけ)。
#   鍵ではないので手元のドライランで nar を読むのに使う。⛔書き込みには使えない。
NAR_PUBLIC = ("https://qgsnsdjvzzeazbazjlwa.supabase.co",
              "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
              "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFnc25zZGp2enplYXpiYXpqbHdhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc0MTg0NDIsImV4cCI6MjEwMjk5NDQ0Mn0."
              "a4pjf8WKgcVGL3d8ZBdP4dJDpnDkM2EnKofnXdHE2I8")


def read_items(base, key):
    """nar_meta の official_news → items。読めなければ None(呼び手が exit 2)"""
    try:
        rows = rest_get(base, key, "nar_meta?select=value&key=eq.%s&limit=1" % ON.META_KEY)
    except Exception as e:                       # noqa: BLE001
        print("⛔official_news が読めません: %s" % e)
        return None
    if not rows:
        print("⛔nar_meta に '%s' がありません(収集役をまだ流していない)" % ON.META_KEY)
        return None
    items = (rows[0].get("value") or {}).get("items")
    if not isinstance(items, list):
        print("⛔official_news の形が違います(items がありません)")
        return None
    return items


def seen_urls(base, key):
    """既に下書きにある source_url。⛔収集役は 120 日で切るので、その窓ぶんだけ引けば足りる"""
    cut = (dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
           - dt.timedelta(days=ON.MAX_AGE_DAYS + 20)).isoformat()
    rows = rest_get(base, key, "%s?select=source_url&src_date=gte.%s&limit=5000" % (TABLE, cut))
    return {r.get("source_url") for r in rows if r.get("source_url")}


# ---------------------------------------------------------------- 組み立て


def site_id_for(venues):
    """場の prefix → 収集役の SITES.id。⚠索引の items は源の id を持たないのでここで引き直す"""
    for s in ON.SITES:
        if set(s["venues"]) & set(venues or []):
            return s["id"]
    return "unknown"


def candidates(items, seen, limit=MAX_NEW):
    """新しい順・役所の定型を除き・既読を除いて limit 本まで"""
    out = []
    for it in sorted(items, key=lambda r: str(r.get("d") or ""), reverse=True):
        u, t = it.get("u"), it.get("t") or ""
        if not u or not it.get("d") or u in seen:
            continue
        if any(w in t for w in DROP_HARD):
            continue
        out.append(it)
        if len(out) >= limit:
            break
    return out


def row_for(item, body, draft, bad, related, model):
    """1 件 → news_drafts の 1 行。⛔落ちた下書きも中身ごと残す(人が直せる= 情報を潰さない)"""
    row = {
        "source_url": item.get("u"),
        "source_site": site_id_for(item.get("v")),
        "venues": item.get("v") or [],
        "src_date": item.get("d"),
        "src_title": item.get("t") or "",
        "src_body": body,
        "status": "nobody",
        "worth": None, "kinds": [], "title": None, "lede": None, "body": None,
        "related": [], "why": None, "model": None,
    }
    if draft is None:
        return row
    row["model"] = model
    row["worth"] = draft.get("worth") if isinstance(draft.get("worth"), bool) else None
    row["kinds"] = [k for k in (draft.get("kinds") or []) if k in KIND_SET]
    for k in ("title", "lede", "body"):
        v = draft.get(k)
        row[k] = v.strip() if isinstance(v, str) else None
    row["related"] = related
    # ⛔worth=false でも draft で残す(人が却下する。拾えないより安い)
    row["status"] = "failed" if bad else "draft"
    row["why"] = ("検査に落ちました: " + " / ".join(bad)) if bad else (
        draft.get("why") if isinstance(draft.get("why"), str) else None)
    return row


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="news_drafts へ書く(既定はドライラン)")
    ap.add_argument("--dry-run", action="store_true", help="書かない(既定)")
    ap.add_argument("--env", help="*_SUPABASE_* / ANTHROPIC_API_KEY のある .env")
    ap.add_argument("--fake", help="偽の LLM 返答(JSON ファイル)。⛔鍵の代わりに試すため")
    ap.add_argument("--items", help="収集役の代わりに読む JSON({items:[…]} か素の配列)")
    a = ap.parse_args()

    env = ON.load_env(a.env) if a.env else os.environ
    old_base, old_key = env.get("OLD_SUPABASE_URL"), env.get("OLD_SUPABASE_SERVICE_KEY")
    if a.apply and not (old_base and old_key):
        # ⚠secret がまだ無い= 何も書かずに正常終了する(⛔朝の便を止めない)
        print("OLD_SUPABASE_URL / OLD_SUPABASE_SERVICE_KEY がありません= 何も書かずに終わります")
        return 0

    nar_base, nar_key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
    if not (nar_base and nar_key):
        nar_base, nar_key = NAR_PUBLIC          # 手元のドライラン= 公開 anon で読むだけ

    # ---- A の結果を読む
    if a.items:
        with open(a.items, encoding="utf-8") as f:
            got = json.load(f)
        items = got.get("items") if isinstance(got, dict) else got
        if not isinstance(items, list):
            print("⛔--items の形が違います(items の配列がありません)")
            return 2
    else:
        items = read_items(nar_base, nar_key)
        if items is None:
            return 2

    # ---- 既読を除く
    seen = set()
    if a.apply:
        try:
            seen = seen_urls(old_base, old_key)
        except Exception as e:                   # noqa: BLE001
            print("⛔既読が読めません: %s" % e)
            return 1
    todo = candidates(items, seen)
    print("候補 %d 件(索引 %d 件・既読 %d 件)" % (len(todo), len(items), len(seen)))

    # ---- C の呼び手を決める
    api_key = env.get("ANTHROPIC_API_KEY")
    if a.fake:
        client, model = fake_client(a.fake), "fake"
    elif api_key:
        client, model = anthropic_client(api_key), MODEL
    else:
        client, model = None, None
        print("⚠ANTHROPIC_API_KEY がありません= 本文だけ溜めます(status=nobody)")

    def nar(path):
        try:
            return rest_get(nar_base, nar_key, path)
        except Exception:                        # noqa: BLE001
            return []

    rows = []
    for i, item in enumerate(todo):
        if i:
            time.sleep(SLEEP)                    # ⛔公式に続けて叩かない
        body, err = read_source(item.get("u"))
        draft = write_one(item, body, client=client)
        bad = check_draft(draft, body) if draft is not None else []
        rel = relate(draft.get("entities") if draft else None, nar=nar,
                     kinds=(draft or {}).get("kinds") or (), title=item.get("t") or "") if (
            draft and not bad) else []
        row = row_for(item, body, draft, bad, rel, model)
        if err and not row["why"]:
            row["why"] = "公式の本文が取れませんでした(%s)" % err
        rows.append(row)

    for r in rows:
        print("[%-6s] %-9s %s | %s | %s"
              % (r["status"], venue_label(r["venues"]), r["src_date"],
                 (r["title"] or r["src_title"])[:44], (r["why"] or "")[:60]))
    n = len(rows)
    print("n=%d draft=%d failed=%d nobody=%d"
          % (n, sum(1 for r in rows if r["status"] == "draft"),
             sum(1 for r in rows if r["status"] == "failed"),
             sum(1 for r in rows if r["status"] == "nobody")))

    if not a.apply:
        print("(ドライラン。書くには --apply。⛔鍵が要ります)")
        return 0
    if not rows:
        print("新しい発表はありません")
        return 0
    try:
        st = insert_drafts(old_base, old_key, rows)
    except Exception as e:                       # noqa: BLE001
        print("投入に失敗: %s" % e)
        return 1
    print("%s に %d 行入れました(HTTP %s・既にある source_url は書きません)" % (TABLE, len(rows), st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
