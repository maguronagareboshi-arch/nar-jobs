# -*- coding: utf-8 -*-
"""厩舎の話から「馬ごとの寸評」を Haiku で作る試し(2026-11-12・1 日分・書き込みなし)。

  python cloud/danwa/sunpyo_trial.py --track 川崎 --date 2026-11-11 --out out/sunpyo_trial.tsv

その日・その場の nar_kb_danwa の各馬について、nar_danwa_note から horse_id で その日以前(当日を含む)の
para がある行を新しい順に最大 8 件取る(3 件未満は飛ばす)。Haiku には para 一覧(日付付き)だけを渡す(原文は渡さない)。
出来た文は対象各行の原文 comment と danwa_para の 8 字検査で照合(距離は同じ扱い)。引っかかれば 1 回だけ作り直し、
駄目なら failed。札の回数は Haiku ではなく対象行の tags の集計(2 回以上・多い順・最大 3 つ)。
⛔公開 repo= ログには件数と状態だけ(文・原文・札は出さない)。結果は tsv ファイルにだけ書く。DB には書かない(読むだけ)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / ANTHROPIC_API_KEY
"""
import argparse
import collections
import json
import os
import re
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import danwa_para as D                           # noqa: E402

MAX_TALKS, MIN_TALKS = 8, 3
LEN_MIN, LEN_MAX = 40, 90

SYSTEM = (
    "あなたは地方競馬サイトの編集者です。ある馬について、厩舎関係者の話を言い換えた文が日付付きで並んでいます。\n"
    "これを読み、陣営が繰り返し言っていることを短くまとめます。\n"
    "決まり:\n"
    f"- 1〜2 文・全角 {LEN_MIN}〜{LEN_MAX} 字。文末は「。」で終える。平易な日本語で書く。\n"
    "- 陣営の話であることが分かる書き方にする(例「〜という話が続く」「陣営は〜と見ている」)。\n"
    "- 1 回だけ出た話より、何度も出た話を優先する。\n"
    "- 勝ち負け・着順・買い目の見立ては書かない。並んだ文に無い事柄を足さない。断定を強めない。\n"
    "- 「上位」「勝機」「勝ち負け」など、着順や勝敗の見込みを表す言い方はしない。\n"
    "- 調教師・厩舎・騎手などの人名、新聞社や他社の名前、クラス名(C1 など)・重賞・斤量・ブリンカーなどの専門語を出さない。\n"
    f"- 並んだ文や元の談話と同じ {D.NGRAM} 字以上の並びを使わない(言い回しを変える)。\n"
    "- 返事は JSON だけ: {\"sunpyo\":\"…\"}(前後に文を書かない)。"
)


def q(v):
    return urllib.parse.quote(str(v), safe="")


def user_prompt(talks, why=None):
    body = [{"date": t["race_date"], "para": t["para"]} for t in talks]
    s = "次の話(新しい順)から、この馬の寸評を書いてください。\n" + json.dumps(body, ensure_ascii=False)
    if why:
        s += "\n前回は次の理由で不合格でした。直してください: " + json.dumps(why, ensure_ascii=False)
    return s


def parse_sunpyo(text):
    m = re.search(r'\{.*\}', text or "", re.S)
    if not m:
        return ""
    try:
        obj = json.loads(m.group())
    except Exception:                            # noqa: BLE001
        return ""
    s = str(obj.get("sunpyo") or "").strip() if isinstance(obj, dict) else ""
    if s and s[-1] not in "。！？!?":
        s += "。"
    return s


def check(s, comments):
    """寸評の検査 → 理由の list(空= 合格)。8 字(距離は同じ扱い)は danwa_para.check_para のものを各原文に当てる。"""
    if not s:
        return ["空"]
    why = []
    for c in comments:
        for w in D.check_para(c, s):
            if w.startswith("8字") or w == "原文と同じ":
                why.append("8字" if w.startswith("8字") else w)
        if why:
            break
    if not (LEN_MIN <= len(s) <= LEN_MAX):
        why.append(f"字数{len(s)}")
    m = D.BAN.search(s)
    if m:
        why.append("語:" + m.group())
    m = D.STRONG.search(s)
    if m and m.group() not in "".join(comments):
        why.append("断定:" + m.group())
    return why


def chips(talks):
    n = len(talks)
    cnt = collections.Counter()
    for t in talks:
        for g in set(t.get("tags") or []):
            cnt[g] += 1
    top = sorted([(g, k) for g, k in cnt.items() if k >= 2], key=lambda x: -x[1])[:3]
    return "・".join(f"{g} {n}回中{k}回" for g, k in top)


def clean(s):
    return re.sub(r'[\t\r\n]+', ' ', str(s or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="out/sunpyo_trial.tsv")
    ap.add_argument("--thinking", choices=["on", "off"], default="on")   # off= 考える段階を切る(Haiku 5.5 は effort high 以下で disabled 可)
    a = ap.parse_args()
    env = os.environ
    db = D.Rest(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])
    import anthropic
    cl = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
    kw = ({"max_tokens": 600, "thinking": {"type": "disabled"}} if a.thinking == "off"
          else {"max_tokens": D.MAX_TOKENS})

    src = db.get(f"{D.SRC}?select=*&race_date=eq.{a.date}&track=eq.{q(a.track)}"
                 f"&order=race_no.asc,umaban.asc&limit=1000")
    if not src:
        tr = sorted({r.get("track") for r in db.get(f"{D.SRC}?select=track&race_date=eq.{a.date}&limit=1000")})
        print(f"⚠対象 0 行。その日の track の値: {tr}", flush=True)
        return 1
    st = collections.Counter()
    tin = tout = 0
    lines = ["race_no\tumaban\thorse_name\tn_talks\tsunpyo\tchips\tstatus\tin_tok\tout_tok"]
    for h in src:
        st["horses"] += 1
        hid = h.get("horse_id")
        talks = []
        if hid:
            talks = db.get(f"{D.DST}?select=race_id,umaban,race_date,para,tags&horse_id=eq.{q(hid)}"
                           f"&race_date=lte.{a.date}&para=not.is.null"
                           f"&order=race_date.desc,race_id.desc&limit={MAX_TALKS}")
            talks = [t for t in talks if (t.get("para") or "").strip()]
        base = [h.get("race_no"), h.get("umaban"), clean(h.get("horse_name")), len(talks)]
        if len(talks) < MIN_TALKS:
            st["skip"] += 1
            lines.append("\t".join(map(str, base + ["", "", "skip", 0, 0])))
            continue
        ids = sorted({t["race_id"] for t in talks})
        cm = {}
        for r in db.get(f"{D.SRC}?select=race_id,umaban,comment&race_id=in.({','.join(q(x) for x in ids)})&limit=1000"):
            cm[(r["race_id"], int(r["umaban"]))] = r.get("comment") or ""
        comments = [cm.get((t["race_id"], int(t["umaban"])), "") for t in talks]
        comments = [c for c in comments if c.strip()]
        s, why, hi, ho = "", ["未"], 0, 0
        for k in range(2):                       # 1 回目 + 作り直し 1 回
            try:
                res = cl.messages.create(model=D.MODEL, system=SYSTEM, **kw,
                                         messages=[{"role": "user", "content": user_prompt(talks, why if k else None)}])
                hi += getattr(res.usage, "input_tokens", 0) or 0
                ho += getattr(res.usage, "output_tokens", 0) or 0
                if res.stop_reason != "end_turn":
                    print(f"  ⚠stop={res.stop_reason}", flush=True)
                s = parse_sunpyo("".join(getattr(b, "text", "") for b in res.content))
            except Exception as e:               # noqa: BLE001
                print(f"  ⚠API {type(e).__name__}", flush=True)
                s = ""
            why = check(s, comments)
            if not why:
                break
            st["retry" if k == 0 else "fail_why"] += 1
            print(f"  ✗R{h.get('race_no')}-{h.get('umaban')} 試行{k + 1} {' '.join(w.split(':')[0] for w in why)}", flush=True)
        status = "ok" if not why else "failed"
        st[status] += 1
        tin, tout = tin + hi, tout + ho
        lines.append("\t".join(map(str, base + [clean(s), chips(talks), status, hi, ho])))
        print(f"R{h.get('race_no')}-{h.get('umaban')} 件数{len(talks)} {status}", flush=True)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"合計 頭数 {st['horses']}・ok {st['ok']}・failed {st['failed']}・飛ばし {st['skip']}"
          f"・作り直し {st['retry']}・入力トークン {tin}・出力トークン {tout}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
