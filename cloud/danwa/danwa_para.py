# -*- coding: utf-8 -*-
"""南関の「厩舎の話」(nar_kb_danwa)を毎日 言い換え・札付けして nar_danwa_note へ入れる(2026-11-09)。

  python cloud/danwa/danwa_para.py                      # 既定= 今日-1 〜 今日+1・言い換え+札
  python cloud/danwa/danwa_para.py --from 2026-11-10 --to 2026-11-10 --dry-run --tags-only
  python cloud/danwa/danwa_para.py --from 2025-01-01 --to 2026-11-08 --tags-only   # 過去の札の埋め

⛔競馬ブックの許可は「原文そのままは不可・言い換えなら可」= 原文(comment)は para に絶対に入れない。
  検査(check_para)で外れた馬だけ 1 回作り直す。2 回だめなら para=null・status=failed。
対象: --from〜--to の nar_kb_danwa のうち、nar_danwa_note に無い行 / src_hash(comment の sha1)が変わった行。
  status=ok で src_hash が同じ行は飛ばす(手の言い換え model=hand-* もこれで守られる)。
札: 全行に tags.py(AI 不要)。--tags-only は言い換えをせず札だけ(新しい行・原文が変わった行は para=null・pending)。
ANTHROPIC_API_KEY が無いときは札だけ入れて status=pending(便を落とさない)。
読むのは月ごと・1000 行ずつ(一意な order)。書くのは upsert・500 行ずつ。⛔重い SQL は使わない。
終わりに nar_job_heartbeat(job=danwa_para)を書く(--dry-run・--tags-only では書かない)。
例外で落ちても heartbeat に fail を書いて exit 0(取得の便全体を赤にしない)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / ANTHROPIC_API_KEY(--env の .env でも可)。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))       # cloud/(beat.py)
import tags as T                                 # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
SRC = "nar_kb_danwa"
DST = "nar_danwa_note"
JOB = "danwa_para"
MODEL = "claude-haiku-5-5"
MAX_TOKENS = 4000
PAGE = 1000
CHUNK = 500
TIMEOUT = 60
MAX_TRIES = 2                                    # 1 回目 + 作り直し 1 回

# ---------------------------------------------------------------- 検査(work/build.py と同じ決まり)
PUN = re.compile(r'[\s、。，．,.・…「」『』()（）!！?？〜~ー―-]')
BAN = re.compile(r'調教師|厩舎|テンコー|増田|ブリンカー|Ｃ[１２３]|Ｂ[１２３]|C[123]|B[123]|オープン|重賞|斤量')
# 断定を強める語(原文に無いのに足したら外す)
STRONG = re.compile(r'必ず|確実|間違いな|絶対|勝てる|勝ち負け|負けられない|楽勝|圧勝|鉄板')
LEN_MIN, LEN_MAX, NGRAM = 20, 80, 8


def norm(s):
    return PUN.sub('', unicodedata.normalize('NFKC', s or ''))


def check_para(src, para, trainer=None):
    """言い換え 1 文を検査 → 外れた理由の list(空= 合格)。"""
    if not isinstance(para, str) or not para.strip():
        return ['空']
    para = para.strip()
    why = []
    ns, np_ = norm(src), norm(para)
    if ns and np_ == ns:
        why.append('原文と同じ')
    hit = next((ns[i:i + NGRAM] for i in range(len(ns) - NGRAM + 1) if ns[i:i + NGRAM] in np_), None)
    if hit:
        why.append('8字:' + hit)
    if not (LEN_MIN <= len(para) <= LEN_MAX):
        why.append(f'字数{len(para)}')
    m = BAN.search(para)
    if m:
        why.append('語:' + m.group())
    if trainer:
        nm = re.sub(r'[\s　]', '', str(trainer))
        for part in {nm, nm[:2]} - {''}:
            if len(part) >= 2 and part in para:
                why.append('調教師名:' + part)
                break
    m = STRONG.search(para)
    if m and m.group() not in (src or ''):
        why.append('断定:' + m.group())
    return why


def src_hash(comment):
    return hashlib.sha1((comment or '').encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- 言い換え(呼び方は cloud/news_writer.py と同じ)
SYSTEM = (
    "あなたは地方競馬サイトの編集者です。厩舎関係者の談話(原文)を、意味を変えずに平易な日本語 1 文へ言い換えます。\n"
    "決まり:\n"
    f"- 1 頭 1 文・{LEN_MIN}〜{LEN_MAX} 字。\n"
    f"- 原文と同じ {NGRAM} 字以上の並びを使わない(語順と言い回しを変える)。原文を写さない。\n"
    "- 調教師・厩舎・騎手などの人名、新聞社や他社の名前、クラス名(C1 など)・重賞・斤量・ブリンカーなどの専門語を出さない。\n"
    "- 原文を 1 つずつ読み、言っている内容は全部残す(抜かない)。\n"
    "- 原文より断定を強めない(「必ず」「確実」「勝てる」などを足さない)。推測や情報の追加をしない。\n"
    "- 返事は JSON だけ: {\"items\":[{\"umaban\":1,\"para\":\"…\"}, …]}(前後に文を書かない)。"
)


def user_prompt(horses, why=None):
    body = [{"umaban": h["umaban"], "comment": h["comment"]} for h in horses]
    s = "次の各馬の談話を言い換えてください。\n" + json.dumps(body, ensure_ascii=False)
    if why:
        s += "\n前回は次の理由で不合格でした。直してください: " + json.dumps(why, ensure_ascii=False)
    return s


def parse_items(text):
    """返事 → {umaban: para}。読めなければ {}。"""
    if not text:
        return {}
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        print(f"  ⚠JSON なし 長さ {len(text)}", flush=True)
        return {}
    try:
        obj = json.loads(m.group())
    except Exception as e:                       # noqa: BLE001
        pos = getattr(e, "pos", None)
        near = m.group()[max(0, pos - 40):pos + 40] if pos is not None else ""
        print(f"  ⚠JSON 誤り {type(e).__name__}: {str(e)[:80]} 長さ {len(text)} 付近 {near!r}", flush=True)
        return {}
    out = {}
    for it in obj.get("items", []) if isinstance(obj, dict) else []:
        try:
            out[int(it["umaban"])] = str(it.get("para") or "").strip()
        except Exception:                        # noqa: BLE001
            continue
    return out


def anthropic_client(api_key):
    """(system, user) → 返事の字。⛔鍵に触るのはここだけ"""
    import anthropic                             # cloud/requirements.txt にある(便でだけ要る)
    cl = anthropic.Anthropic(api_key=api_key)

    def call(system, user):
        # ⛔temperature は渡さない(news_writer.py と同じ)
        res = cl.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                                 system=system, messages=[{"role": "user", "content": user}])
        text = "".join(getattr(b, "text", "") for b in res.content)
        if res.stop_reason != "end_turn":        # 読めない返事の手掛かり(原文は出さない)
            print(f"  ⚠stop={res.stop_reason} out_tokens={getattr(res.usage, 'output_tokens', '?')}", flush=True)
        return text
    return call


def paraphrase_race(horses, call):
    """1 レースの馬(comment のあるもの)→ {umaban: (para|None, tries, why)}。外れた馬だけ作り直す。"""
    res = {h["umaban"]: (None, 0, ['未']) for h in horses}
    todo, why = list(horses), None
    for _ in range(MAX_TRIES):
        if not todo:
            break
        try:
            got = parse_items(call(SYSTEM, user_prompt(todo, why)))
        except Exception as e:                   # noqa: BLE001
            print(f"  ⚠API {type(e).__name__}: {str(e)[:120]}", flush=True)
            got = {}
        nxt, why = [], {}
        for h in todo:
            u = h["umaban"]
            p = got.get(u)
            bad = check_para(h["comment"], p, h.get("trainer"))
            tries = res[u][1] + 1
            if bad:
                res[u] = (None, tries, bad)
                nxt.append(h)
                why[u] = bad
            else:
                res[u] = (p, tries, [])
        todo = nxt
    return res


# ---------------------------------------------------------------- DB(PostgREST・標準ライブラリだけ)
class Rest:
    def __init__(self, base, key):
        self.base, self.key = base.rstrip("/"), key

    def _h(self, extra=None):
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key,
             "Accept": "application/json", "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def get(self, path):
        req = urllib.request.Request(self.base + "/rest/v1/" + path, headers=self._h())
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            out = json.loads(r.read().decode("utf-8"))
        return out if isinstance(out, list) else []

    def get_all(self, table, select, d0, d1, extra=""):
        out, off = [], 0
        while True:
            q = (f"{table}?select={select}&race_date=gte.{d0}&race_date=lte.{d1}{extra}"
                 f"&order=race_id.asc,umaban.asc&limit={PAGE}&offset={off}")
            rows = self.get(q)
            out += rows
            if len(rows) < PAGE:
                return out
            off += PAGE

    def upsert(self, table, rows, on_conflict):
        for i in range(0, len(rows), CHUNK):
            part = rows[i:i + CHUNK]
            data = json.dumps(part, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base}/rest/v1/{table}?on_conflict={on_conflict}", data=data, method="POST",
                headers=self._h({"Prefer": "resolution=merge-duplicates,return=minimal"}))
            for k in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=TIMEOUT):
                        break
                except urllib.error.HTTPError as e:
                    if e.code < 500 or k == 2:
                        raise
                    time.sleep(2 * (k + 1))


def months(d0, d1):
    """[d0, d1] を月ごとに切る → [(a, b), ...]"""
    out, a = [], d0
    while a <= d1:
        nm = (a.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        b = min(d1, nm - dt.timedelta(days=1))
        out.append((a, b))
        a = nm
    return out


# ---------------------------------------------------------------- 本体
def load_env(path):
    env = dict(os.environ)
    if path:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def pick(src_rows, have, tags_only):
    """対象の行を選ぶ。have = {(race_id, umaban): note 行}"""
    out = []
    for r in src_rows:
        k = (r["race_id"], int(r["umaban"]))
        h = have.get(k)
        sh = src_hash(r.get("comment"))
        if h and h.get("src_hash") == sh:
            if h.get("status") == "ok":
                continue                         # 済み(手の言い換えもここで守る)
            if tags_only or not (r.get("comment") or "").strip():
                continue                         # 札は原文で決まる= 同じ原文なら作り直さない
        out.append(r)
    return out


def note_row(r, para, status, model, tries, now):
    return {"race_id": r["race_id"], "umaban": int(r["umaban"]), "track": r.get("track"),
            "race_date": r.get("race_date"), "horse_id": r.get("horse_id"),
            "para": para, "tags": T.note_tags(r.get("comment")), "src_hash": src_hash(r.get("comment")),
            "model": model, "status": status, "tries": tries, "updated_at": now}


def run(a, env):
    base, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
    today = dt.datetime.now(JST).date()
    d0 = dt.date.fromisoformat(a.date_from) if a.date_from else today - dt.timedelta(days=1)
    d1 = dt.date.fromisoformat(a.date_to) if a.date_to else today + dt.timedelta(days=1)
    db = Rest(base, key) if base and key else None
    if a.src_json:                               # 本番から読んだ nar_kb_danwa の行(試験用・読むだけ)
        src_all = json.load(open(a.src_json, encoding="utf-8"))
        src_all = [r for r in src_all if d0.isoformat() <= str(r["race_date"]) <= d1.isoformat()]
        groups = [(d0, d1, src_all)]
    else:
        if db is None:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY が無い")
        groups = [(m0, m1, None) for m0, m1 in months(d0, d1)]
    api_key = None if a.tags_only else env.get("ANTHROPIC_API_KEY")
    call = None
    if api_key:
        try:
            call = anthropic_client(api_key)
        except Exception as e:                   # noqa: BLE001  SDK が無い等= 札だけ入れる
            print(f"⚠anthropic が使えない({type(e).__name__})= 札だけ入れて status=pending", flush=True)
    elif not a.tags_only:
        print("ANTHROPIC_API_KEY が無い= 札だけ入れて status=pending", flush=True)
    st = {"src": 0, "target": 0, "tagged": 0, "ok": 0, "failed": 0, "pending": 0, "written": 0, "api_races": 0}
    left = a.limit
    for m0, m1, rows in groups:
        if rows is None:
            rows = db.get_all(SRC, "track,race_date,race_no,umaban,race_id,horse_id,trainer,comment", m0, m1)
        have = {}
        if db is not None:
            try:
                for h in db.get_all(DST, "race_id,umaban,src_hash,status,model", m0, m1):
                    have[(h["race_id"], int(h["umaban"]))] = h
            except urllib.error.HTTPError as e:
                if not a.dry_run:
                    raise
                print(f"⚠{DST} が読めない(HTTP {e.code})= dry-run なので全部を対象として数える", flush=True)
        tg = pick(rows, have, a.tags_only)
        if left is not None:
            tg, left = tg[:left], max(0, left - len(tg))
        st["src"] += len(rows)
        st["target"] += len(tg)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        out = []
        by_race = {}
        for r in tg:
            by_race.setdefault(r["race_id"], []).append(r)
        for rid, rs in sorted(by_race.items()):
            talk = [dict(r, umaban=int(r["umaban"])) for r in rs if (r.get("comment") or "").strip()]
            res = {}
            if call and talk:
                res = paraphrase_race(talk, call)
                st["api_races"] += 1
            for r in rs:
                u = int(r["umaban"])
                has = bool((r.get("comment") or "").strip())
                if a.tags_only or not has or not call:
                    row = note_row(r, None, "pending", None, 0, now)
                else:
                    p, tries, why = res.get(u, (None, 0, ['未']))
                    if p is not None and norm(p) == norm(r["comment"]):
                        p, why = None, ['原文と同じ']            # 念のため二重に止める
                    if p is None:
                        print(f"  ✗{rid}-{u} {' '.join(why)}", flush=True)
                    row = note_row(r, p, "ok" if p else "failed", MODEL, tries, now)
                st[row["status"]] += 1
                st["tagged"] += 1 if row["tags"] else 0
                out.append(row)
        if out and not a.dry_run:
            db.upsert(DST, out, "race_id,umaban")
            st["written"] += len(out)
        print(f"{m0}〜{m1}: 原文 {len(rows)}・対象 {len(tg)}・書き {0 if a.dry_run else len(out)}", flush=True)
        if left == 0:
            break
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", help="YYYY-MM-DD(既定= 今日-1)")
    ap.add_argument("--to", dest="date_to", help="YYYY-MM-DD(既定= 今日+1)")
    ap.add_argument("--tags-only", action="store_true", help="言い換えをせず札だけ入れる")
    ap.add_argument("--dry-run", action="store_true", help="書かない")
    ap.add_argument("--limit", type=int, help="対象の行をここまで")
    ap.add_argument("--env", help="SUPABASE_* / ANTHROPIC_API_KEY のある .env")
    ap.add_argument("--src-json", help="nar_kb_danwa の行の JSON(試験用・DB の代わりに読む)")
    a = ap.parse_args()
    env = load_env(a.env)
    beat_on = not a.dry_run and not a.tags_only
    if beat_on:
        os.environ.setdefault("SUPABASE_URL", env.get("SUPABASE_URL", ""))
        os.environ.setdefault("SUPABASE_SERVICE_KEY", env.get("SUPABASE_SERVICE_KEY", ""))
    try:
        st = run(a, env)
    except Exception as e:                       # noqa: BLE001
        traceback.print_exc()
        if beat_on:
            import beat
            beat.beat(JOB, False, f"{type(e).__name__}: {str(e)[:100]}")
        return 0                                 # ⛔取得の便全体を赤にしない(heartbeat の fail を見張りが拾う)
    print("集計 " + json.dumps(st, ensure_ascii=False), flush=True)
    if beat_on:
        import beat
        # 便は回り切った= ok(言い換えの不合格・pending は見張りの「para が null の頭数」で拾う)
        beat.beat(JOB, True,
                  f"対象 {st['target']}・ok {st['ok']}・failed {st['failed']}・pending {st['pending']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
