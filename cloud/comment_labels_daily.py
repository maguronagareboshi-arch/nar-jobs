# -*- coding: utf-8 -*-
"""高知の騎手コメントの「よく出る話」分類を毎日足す(2026-11-13)。

  python cloud/comment_labels_daily.py --dry-run [--limit N]   … DB に書かない(件数と見本の鍵だけ出す・API は --limit 分だけ呼ぶ)
  python cloud/comment_labels_daily.py --apply [--limit N]     … nar_comment_labels へ upsert(既にある hid は上書きしない)
  python cloud/comment_labels_daily.py --check 40              … 分類済みから無作為 N 文を付け直して既存との一致率を出す(書かない)

- 対象= view nar_race_comments_lab の track=高知・labels is null の行の一意な文(hid = left(md5(btrim(comment)),10))。
- 分類の決まり= data/comment_taxonomy_v2.md(29 話)を system に入れ、claude-sonnet-5-5 に 40 文ずつ。文だけを読む(日付・着順・後の情報は渡さない)。
- labels の形は 10/31 の一括分と同じ= [{"k","s","v"?,"e"}]。model 列に MODEL。返ってこなかった文は書かない(次の便でまた拾う)。
- 冪等: labels の無い文だけ選び、upsert は on_conflict=hid の ignore-duplicates(手で直した行を上書きしない)。
- --apply の終わりに nar_job_heartbeat(job=comment_labels)。例外で落ちても fail を書いて exit 0(取得の便全体を赤にしない)。
- ⛔公開 repo= ログには件数・鍵・hid だけ(文・根拠の言葉は出さない)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / ANTHROPIC_API_KEY
"""
import argparse
import collections
import hashlib
import json
import os
import random
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import beat as B                                 # noqa: E402

ROOT = os.path.dirname(HERE)
TAXONOMY = os.path.join(ROOT, "data", "comment_taxonomy_v2.md")
VIEW = "nar_race_comments_lab"
TABLE = "nar_comment_labels"
TRACK = "高知"
LLM = "claude-sonnet-5-5"
MODEL = "claude-sonnet-5-5 (api daily, taxonomy v2.1)"
BATCH = 40
JOB = "comment_labels"
UA = "nar-jobs/1.0"

V_OK = {"waku": {"out", "in"}, "pace": {"fast", "slow"}, "kyori": {"long", "short"},
        "kyori_pref": {"long", "short", "fit"}, "baba": {"wet", "dry", "heavy", "light"}}
KEYS = ["gate", "ikiashi", "senko", "sashi", "suna", "waku", "kakari", "shimai_amai", "shimai_tsuyoi", "pace",
        "kimochi", "kisho", "sosa", "kyori", "kyori_pref", "baba", "natsu", "tsukare", "joshou", "kankaku",
        "bataiju", "nenrei", "kenko", "bagu", "chikara", "ashishitsu", "course", "shiage", "norikata"]

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["i", "l"],
        "properties": {
            "i": {"type": "integer"},
            "l": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["k", "s", "e"],
                "properties": {
                    "k": {"type": "string", "enum": KEYS},
                    "s": {"type": "string", "enum": ["+", "-", "0"]},
                    "v": {"type": "string", "enum": sorted(set().union(*V_OK.values()))},
                    "e": {"type": "string"}}}}}}}}}

RULE = ("あなたは高知競馬のレース後の騎手コメントを、下の表の決まりどおりに分類する係です。\n"
        "入力は番号付きの文の並び(1 行= 番号<TAB>文)。文ごとに、表の鍵だけを使って 0〜複数のラベルを付けてください。\n"
        "文に書かれていることだけで判断する(推測で足さない・迷ったら付けない)。e は原文から 15 字以内をそのまま抜く。\n"
        "v は表で向きの指定がある鍵だけ・書かれていなければ省く。全部の番号について items に 1 つずつ返す(付けるものが無ければ l は空)。\n\n")


def log(msg):
    print(msg, flush=True)


def hid_of(comment):
    """DB の left(md5(btrim(comment)),10) と同じ(btrim は半角空白だけを落とす)。"""
    return hashlib.md5(comment.strip(" ").encode("utf-8")).hexdigest()[:10]


class Rest:
    def __init__(self, url, key):
        self.url, self.key = url.rstrip("/"), key

    def call(self, path, method="GET", body=None, prefer=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key, "User-Agent": UA,
             "Content-Type": "application/json"}
        if prefer:
            h["Prefer"] = prefer
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        for n in range(3):
            r = urllib.request.Request(self.url + "/rest/v1/" + path, data=data, method=method, headers=h)
            try:
                with urllib.request.urlopen(r, timeout=90) as x:
                    raw = x.read().decode("utf-8")
                    return (json.loads(raw) if raw.strip() else None), x.headers
            except urllib.error.HTTPError as e:
                if e.code >= 500 and n < 2:
                    time.sleep(3 * (n + 1)); continue
                raise RuntimeError(f"HTTP {e.code} {e.read().decode('utf-8')[:200]}")
            except (urllib.error.URLError, TimeoutError):
                if n < 2:
                    time.sleep(3 * (n + 1)); continue
                raise

    def count(self, q):
        _, hd = self.call(f"{VIEW}?select=race_date&{q}&limit=1", prefer="count=exact")
        return int(hd.get("Content-Range", "*/0").split("/")[-1])


def base_q(labeled):
    return f"track=eq.{urllib.parse.quote(TRACK)}&labels={'not.is.null' if labeled else 'is.null'}"


def fetch_unlabeled(db):
    """labels の無い高知コメント → {hid: 文}(古い順・一意)。"""
    out, off = {}, 0
    while True:
        rows, _ = db.call(f"{VIEW}?select=comment&{base_q(False)}&order=race_date,race_no,umaban"
                          f"&limit=1000&offset={off}")
        for r in rows:
            c = (r.get("comment") or "").strip(" ")
            if c:
                out.setdefault(hid_of(c), c)
        if len(rows) < 1000:
            return out
        off += 1000


def fetch_sample(db, n, seed):
    """分類済みから無作為 n 文 → [(hid, 文, 既存 labels)]。"""
    total = db.count(base_q(True))
    rnd = random.Random(seed)
    got, seen = [], set()
    for off in rnd.sample(range(total), min(total, n * 3)):
        rows, _ = db.call(f"{VIEW}?select=comment,labels&{base_q(True)}&order=race_date,race_no,umaban"
                          f"&limit=1&offset={off}")
        if not rows:
            continue
        c = (rows[0].get("comment") or "").strip(" ")
        h = hid_of(c)
        if c and h not in seen:
            seen.add(h)
            got.append((h, c, rows[0].get("labels") or []))
        if len(got) >= n:
            break
    return got, total


def clean(labels):
    """形を揃える(鍵 1 つにつき 1 つ・v は表にある向きだけ・e は 15 字まで)。"""
    out, ks = [], set()
    for x in labels or []:
        k, s = x.get("k"), x.get("s")
        if k not in KEYS or s not in ("+", "-", "0") or k in ks:
            continue
        ks.add(k)
        o = {"k": k, "s": s}
        v = x.get("v")
        if v and v in V_OK.get(k, ()):
            o["v"] = v
        o["e"] = (x.get("e") or "")[:15]
        out.append(o)
    return out


def classify(cl, system, texts, st):
    """texts= [文] → {番号(0 始まり): labels}。返ってこなかった番号は入れない。"""
    user = "\n".join(f"{i + 1}\t{t.replace(chr(10), ' ').replace(chr(9), ' ')}" for i, t in enumerate(texts))
    msg = cl.messages.create(
        model=LLM, max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    u = msg.usage
    st["in"] += u.input_tokens
    st["out"] += u.output_tokens
    st["cache_r"] += getattr(u, "cache_read_input_tokens", 0) or 0
    st["cache_w"] += getattr(u, "cache_creation_input_tokens", 0) or 0
    st["calls"] += 1
    if msg.stop_reason != "end_turn":
        st["bad_stop_" + str(msg.stop_reason)] += 1
        return {}
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    res = {}
    for it in json.loads(txt).get("items", []):
        i = int(it.get("i", 0)) - 1
        if 0 <= i < len(texts) and i not in res:
            res[i] = clean(it.get("l"))
    st["missing"] += len(texts) - len(res)
    return res


def cost(st):
    """Sonnet 5.5 の値段($2/$10 per MTok・cache 書き 1.25 倍・読み $0.10)。"""
    return (st["in"] * 2 + st["cache_w"] * 2.5 + st["cache_r"] * 0.1 + st["out"] * 10) / 1e6


def label_all(cl, system, items, st):
    """items= [(hid, 文)] → {hid: labels}"""
    out = {}
    for i in range(0, len(items), BATCH):
        part = items[i:i + BATCH]
        try:
            res = classify(cl, system, [t for _, t in part], st)
        except Exception as e:                   # noqa: BLE001  1 束の失敗は飛ばす(次の便でまた拾う)
            st["batch_error"] += 1
            log(f"  ⚠束 {i // BATCH + 1} {type(e).__name__}: {str(e)[:160]}")
            continue
        for j, l in res.items():
            out[part[j][0]] = l
        log(f"  束 {i // BATCH + 1}: {len(part)} 文 → 返り {len(res)}")
    return out


def compare(sample, new):
    """一致率: 文ごとの鍵の集合の完全一致・鍵の適合/再現・鍵が合ったときの s の一致。"""
    c = collections.Counter()
    for h, _, old in sample:
        if h not in new:
            c["none"] += 1; continue
        a = {x["k"]: x for x in old}
        b = {x["k"]: x for x in new[h]}
        c["n"] += 1
        c["exact"] += set(a) == set(b)
        c["empty_both"] += (not a and not b)
        both = set(a) & set(b)
        c["tp"] += len(both); c["old"] += len(a); c["new"] += len(b)
        c["s_ok"] += sum(1 for k in both if a[k].get("s") == b[k].get("s"))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="書かない(--limit 分だけ API を呼んで見本を出す)")
    g.add_argument("--apply", action="store_true", help="nar_comment_labels へ upsert")
    g.add_argument("--check", type=int, metavar="N", help="分類済みから無作為 N 文で一致率(書かない)")
    ap.add_argument("--limit", type=int, help="分類する一意な文をここまで(dry-run の既定 5)")
    ap.add_argument("--seed", type=int, default=20261113)
    a = ap.parse_args(argv)

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い"); return 2
    db = Rest(url, key)
    st = collections.Counter()
    try:
        with open(TAXONOMY, encoding="utf-8") as f:
            system = RULE + f.read()
        cl = None
        if a.check:
            sample, total = fetch_sample(db, a.check, a.seed)
            log(f"分類済み(行) {total}・見本 {len(sample)} 文")
            import anthropic
            cl = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            new = label_all(cl, system, [(h, t) for h, t, _ in sample], st)
            c = compare(sample, new)
            n = max(c["n"], 1)
            log(f"一致 文の鍵の集合が完全一致 {c['exact']}/{c['n']}({c['exact'] / n:.0%})・両方空 {c['empty_both']}"
                f"・返り無し {c['none']}")
            log(f"鍵 一致 {c['tp']}・既存 {c['old']}・新 {c['new']}・再現 {c['tp'] / max(c['old'], 1):.0%}"
                f"・適合 {c['tp'] / max(c['new'], 1):.0%}・鍵が合ったときの s 一致 {c['s_ok']}/{c['tp']}")
            diff = collections.Counter()
            for h, _, old in sample:
                if h in new:
                    for k in {x["k"] for x in old} ^ {x["k"] for x in new[h]}:
                        diff[k] += 1
            log("食い違いの多い鍵 " + "・".join(f"{k} {v}" for k, v in diff.most_common(8)))
        else:
            todo = fetch_unlabeled(db)
            log(f"未分類の一意な文 {len(todo)}")
            items = list(todo.items())                       # 古い順(dict は入れた順)
            lim = a.limit if a.limit is not None else (5 if a.dry_run else None)
            if lim is not None:
                items = items[:lim]
            if items:
                import anthropic
                cl = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
                new = label_all(cl, system, items, st)
                rows = [{"hid": h, "labels": l, "model": MODEL} for h, l in new.items()]
                kc = collections.Counter(x["k"] for r in rows for x in r["labels"])
                log(f"付いた文 {len(rows)}/{len(items)}・空 {sum(1 for r in rows if not r['labels'])}"
                    f"・鍵 " + "・".join(f"{k} {v}" for k, v in kc.most_common(10)))
                for r in rows[:5]:
                    log(f"  見本 {r['hid']} " + ",".join(x["k"] + x["s"] + ("/" + x["v"] if x.get("v") else "")
                                                        for x in r["labels"]))
                if a.apply and rows:
                    for i in range(0, len(rows), 500):
                        db.call(f"{TABLE}?on_conflict=hid", "POST", rows[i:i + 500],
                                prefer="resolution=ignore-duplicates,return=minimal")
                    st["written"] = len(rows)
            log(f"書き {st['written'] if a.apply else 0}(dry-run は書かない)")
        log(f"API {st['calls']} 回・入力 {st['in']}・cache 書き {st['cache_w']}・読み {st['cache_r']}・出力 {st['out']}"
            f"・費用 ${cost(st):.4f}・束の失敗 {st['batch_error']}・返り漏れ {st['missing']}")
        if a.apply:
            ok = st["batch_error"] == 0
            B.beat(JOB, ok, f"書き {st['written']}" + ("" if ok else f"・束の失敗 {st['batch_error']}"))
    except Exception:                            # noqa: BLE001
        traceback.print_exc()
        if a.apply:
            B.beat(JOB, False, "例外")
        return 0                                 # ⛔取得の便全体を赤にしない
    return 0


if __name__ == "__main__":
    sys.exit(main())
