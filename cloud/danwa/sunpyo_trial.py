# -*- coding: utf-8 -*-
"""厩舎の話から「馬ごとの寸評」を Haiku で作る試し 2(2026-11-12・1 日分・書き込みなし)。

  python cloud/danwa/sunpyo_trial.py --track 川崎 --date 2026-11-11 --out out/sunpyo_trial.tsv

寸評= 陣営の過去の話と、そのレースの実際の着順を照らし合わせて話どおりだったかを事実として書き、
今回の話がそれと比べてどうかを書く(1〜3 文・全角 60〜120 字)。
その日・その場の nar_kb_danwa の各馬について、nar_danwa_note から horse_id で para を取り、
当日より前を新しい順に最大 8 件(2 件未満は飛ばす)・当日の para を「今回の話」とする(当日の話が無ければ飛ばす)。
前の話には場・距離(nar_races.distance_m)・着順を付ける。着順は画面の厩舎の話タブと同じ所=
getRaceHistory → runs_by_horses(nar_runs)の finish / finish_note を、馬名で引いて同じ日・同じ場で当てる(無ければ「不明」)。
Haiku には原文 comment を渡さない(写し検査にだけ使う)。
出来た文は対象各行の原文 comment と danwa_para の 8 字検査で照合(距離は同じ扱い)・今回の見込みの言葉(OUTLOOK)も検査。
引っかかれば 1 回だけ作り直し、駄目なら failed。考える段階は off(disabled)と low(output_config.effort=low)の 2 通りを同じ馬で出す。
札の回数は Haiku ではなく前の話の tags の集計(2 回以上・多い順・最大 3 つ)。
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

MAX_TALKS, MIN_TALKS = 8, 2                      # 前の話 最大 8 件・2 件未満は飛ばす
LEN_MIN, LEN_MAX = 60, 120
# 今回の見込みを表す言葉(過去の着順は事実として書いてよい)。入っていたら作り直し(写し検査と同じ扱い・1 回だけ)
OUTLOOK = re.compile(r'上位|勝機|勝ち負け|好勝負|勝ち切|圏内|好走必至|有力|チャンス|期待大')
# 考える段階 2 通り(Haiku 5.5: 既定は adaptive・effort medium。disabled は effort high 以下で可・low= output_config.effort)
MODES = {"off": {"max_tokens": 600, "thinking": {"type": "disabled"}},
         "low": {"max_tokens": D.MAX_TOKENS, "output_config": {"effort": "low"}}}

SYSTEM = (
    "あなたは地方競馬サイトの編集者です。ある馬について、厩舎関係者の過去の話(言い換え文)と、そのレースの実際の着順が並んでいます。"
    "あわせて今回のレースの話があります。\n"
    "過去の話と着順を照らし合わせて、話どおりの結果だったかを事実として書き、そのうえで今回の話がそれと比べてどうかを書きます。\n"
    "見本: 「春は『使うたびに良くなる』の話どおり2着・3着と走ったが、夏以降『状態は良い』と言われた2戦はともに8着。"
    "今回は『ひと叩きして上向き』という話で、前走からの変わり身が見どころ。」\n"
    "決まり:\n"
    f"- 1〜3 文・全角 {LEN_MIN}〜{LEN_MAX} 字。文末は「。」で終える。平易な日本語で書く。\n"
    "- 過去の着順は並んだ値どおりに事実として書いてよい。着順が「不明」の走は着順に触れない。\n"
    "- 今回の勝ち負け・着順・上位の予想は書かない。「上位」「勝機」「勝ち負け」「好勝負」など、今回の見込みを表す言葉は使わない。\n"
    "- 並んだ文に無い事柄を足さない。断定を強めない。\n"
    "- 調教師・厩舎・騎手などの人名、新聞社や他社の名前、クラス名(C1 など)・重賞・斤量・ブリンカーなどの専門語を出さない。\n"
    f"- 元の談話と同じ {D.NGRAM} 字以上の並びを使わない(言い回しを変える)。\n"
    "- 返事は JSON だけ: {\"sunpyo\":\"…\"}(前後に文を書かない)。"
)


def q(v):
    return urllib.parse.quote(str(v), safe="")


def user_prompt(past, today, why=None):
    body = [{"date": t["race_date"], "track": t.get("track") or "不明", "distance": t.get("dist") or "不明",
             "finish": t.get("fin") or "不明", "para": t["para"]} for t in past]
    s = ("前の話(新しい順・各走の着順付き):\n" + json.dumps(body, ensure_ascii=False)
         + "\n今回の話:\n" + json.dumps({"date": today["race_date"], "para": today["para"]}, ensure_ascii=False)
         + "\nこの馬の寸評を書いてください。")
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
    m = OUTLOOK.search(s)
    if m:
        why.append("見込み:" + m.group())
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


def fin_str(r):
    """nar_runs の 1 行 → 着順の文字(画面と同じ= finish>0 は N着・それ以外は finish_note・margin の取消等・無ければ 不明)。"""
    try:
        f = int(r.get("finish")) if r.get("finish") is not None else None
    except Exception:                            # noqa: BLE001
        f = None
    if f and f > 0:
        return f"{f}着"
    note = (r.get("finish_note") or "").strip()
    if note:
        return note
    m = re.search(r'取消|除外|中止|失格', str(r.get("margin") or ""))
    return m.group() if m else "不明"


def attach_finish(db, name, date, past, trk):
    """前の話に 場・距離・着順を付ける。着順= nar_runs を馬名で引き、同じ日・同じ場(画面の dwRunOf と同じ)で当てる。
    場の名前が合わないときは、その日の走が 1 つだけなら当てる。距離= nar_races.distance_m。"""
    runs = []
    if name:
        runs = db.get(f"nar_runs?select=track,race_date,race_no,finish,finish_note,margin&horse_name=eq.{q(name)}"
                      f"&race_date=lt.{date}&order=race_date.desc,race_no.desc&limit=200")
    keys = {}
    for t in past:
        t["track"] = trk.get(t["race_id"], {}).get("track")
        cand = [r for r in runs if r.get("race_date") == t["race_date"]]
        hit = [r for r in cand if r.get("track") == t["track"]] or (cand if len(cand) == 1 else [])
        if hit:
            r = hit[0]
            t["fin"] = fin_str(r)
            t["track"] = r.get("track") or t["track"]
            keys[(r.get("track"), r.get("race_date"), r.get("race_no"))] = t
        else:
            t["fin"] = "不明"
    if keys:
        cond = ",".join(f"and(track.eq.{q(k[0])},race_date.eq.{k[1]},race_no.eq.{k[2]})" for k in keys)
        for r in db.get(f"nar_races?select=track,race_date,race_no,distance_m&or=({cond})&limit=200"):
            t = keys.get((r.get("track"), r.get("race_date"), r.get("race_no")))
            if t and r.get("distance_m"):
                t["dist"] = f"{r['distance_m']}m"


def make(cl, kw, past, today, comments, st, tag, label):
    s, why, hi, ho, rt = "", ["未"], 0, 0, 0
    for k in range(2):                           # 1 回目 + 作り直し 1 回
        try:
            res = cl.messages.create(model=D.MODEL, system=SYSTEM, **kw,
                                     messages=[{"role": "user", "content": user_prompt(past, today, why if k else None)}])
            hi += getattr(res.usage, "input_tokens", 0) or 0
            ho += getattr(res.usage, "output_tokens", 0) or 0
            if res.stop_reason != "end_turn":
                print(f"  ⚠{tag} stop={res.stop_reason}", flush=True)
            s = parse_sunpyo("".join(getattr(b, "text", "") for b in res.content))
        except Exception as e:                   # noqa: BLE001
            print(f"  ⚠{tag} API {type(e).__name__}", flush=True)
            s = ""
        why = check(s, comments)
        if not why:
            break
        if k == 0:
            rt = 1
            st[tag + "_retry"] += 1
        print(f"  ✗{label} {tag} 試行{k + 1} {' '.join(w.split(':')[0] for w in why)}", flush=True)
    status = "ok" if not why else "failed"
    st[tag + "_" + status] += 1
    st[tag + "_in"] += hi
    st[tag + "_out"] += ho
    return [clean(s), status, rt, hi, ho]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", default="out/sunpyo_trial.tsv")
    a = ap.parse_args()
    env = os.environ
    db = D.Rest(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])
    import anthropic
    cl = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])

    src = db.get(f"{D.SRC}?select=*&race_date=eq.{a.date}&track=eq.{q(a.track)}"
                 f"&order=race_no.asc,umaban.asc&limit=1000")
    if not src:
        tr = sorted({r.get("track") for r in db.get(f"{D.SRC}?select=track&race_date=eq.{a.date}&limit=1000")})
        print(f"⚠対象 0 行。その日の track の値: {tr}", flush=True)
        return 1
    st = collections.Counter()
    head = ["race_no", "umaban", "horse_name", "n_talks", "n_fin"]
    for m in MODES:
        head += [f"sunpyo_{m}", f"status_{m}", f"retry_{m}", f"in_tok_{m}", f"out_tok_{m}"]
    lines = ["\t".join(head + ["chips"])]
    for h in src:
        st["horses"] += 1
        hid = h.get("horse_id")
        rows = []
        if hid:
            rows = db.get(f"{D.DST}?select=race_id,umaban,race_date,para,tags&horse_id=eq.{q(hid)}"
                          f"&race_date=lte.{a.date}&para=not.is.null"
                          f"&order=race_date.desc,race_id.desc&limit={MAX_TALKS + 3}")
            rows = [t for t in rows if (t.get("para") or "").strip()]
        today = next((t for t in rows if t["race_date"] == a.date and t["race_id"] == h.get("race_id")), None) \
            or next((t for t in rows if t["race_date"] == a.date), None)
        past = [t for t in rows if t["race_date"] < a.date][:MAX_TALKS]
        base = [h.get("race_no"), h.get("umaban"), clean(h.get("horse_name")), len(past)]
        if not today or len(past) < MIN_TALKS:
            st["skip"] += 1
            lines.append("\t".join(map(str, base + [0] + ["", "skip", 0, 0, 0] * len(MODES) + [""])))
            continue
        ids = sorted({t["race_id"] for t in past + [today]})
        cm, trk = {}, {}
        for r in db.get(f"{D.SRC}?select=race_id,umaban,track,comment&race_id=in.({','.join(q(x) for x in ids)})&limit=1000"):
            cm[(r["race_id"], int(r["umaban"]))] = r.get("comment") or ""
            trk.setdefault(r["race_id"], {"track": r.get("track")})
        comments = [cm.get((t["race_id"], int(t["umaban"])), "") for t in past + [today]]
        comments = [c for c in comments if c.strip()]
        attach_finish(db, h.get("horse_name"), a.date, past, trk)
        nfin = sum(1 for t in past if t.get("fin") and t["fin"] != "不明")
        st["fin_known"] += nfin
        st["fin_all"] += len(past)
        label = f"R{h.get('race_no')}-{h.get('umaban')}"
        row = base + [nfin]
        for m, kw in MODES.items():
            row += make(cl, kw, past, today, comments, st, m, label)
        lines.append("\t".join(map(str, row + [chips(past)])))
        print(f"{label} 件数{len(past)} 着順{nfin} off={row[6]} low={row[11]}", flush=True)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"合計 頭数 {st['horses']}・飛ばし {st['skip']}・着順あり {st['fin_known']}/{st['fin_all']}", flush=True)
    for m in MODES:
        print(f"  {m}: ok {st[m + '_ok']}・failed {st[m + '_failed']}・作り直し {st[m + '_retry']}"
              f"・入力トークン {st[m + '_in']}・出力トークン {st[m + '_out']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
