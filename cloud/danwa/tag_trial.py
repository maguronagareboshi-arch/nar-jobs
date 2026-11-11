# -*- coding: utf-8 -*-
"""厩舎の話の札: 今の語句ルール(tags.py)と Haiku の選択を 200 頭前後で比べる材料(2026-11-12・試し・書き込みなし)。

  python cloud/danwa/tag_trial.py [--n 200] [--seed 20261112]

nar_kb_danwa(2025-11-10〜2026-11-11)から日をランダムに選び、その日の 1 レースの全頭(comment あり)を
1 回の呼び出しに入れる(danwa_para と同じ形)。200 頭前後になるまでレースを足す。
⛔公開 repo= 原文はログに出さない。出すのは
  race_id<TAB>umaban<TAB>今の札(・区切り)<TAB>Haiku の札(・区切り)
の行と、最後の合計トークン数だけ。DB には書かない(読むだけ)。
環境変数: SUPABASE_URL / SUPABASE_SERVICE_KEY / ANTHROPIC_API_KEY
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tags as T                                 # noqa: E402
import danwa_para as D                           # noqa: E402

D0, D1 = dt.date(2025, 11, 10), dt.date(2026, 11, 11)

# 札の短い定義(一覧の順= tags.py の M の順 + 新しい 2 つ)
DEF = {
    '長めの距離の話': '距離延長・今回は長めの距離',
    '短めの距離の話': '距離短縮・今回は短めの距離',
    '距離が合う': '今回の距離が合っている・ベストの距離',
    '距離・条件に不安': '距離や条件が合うか心配・不向き',
    'コース・回りの話': 'コース形態・右回り/左回り・小回り/大回り',
    '馬場の話': '重馬場・良馬場・道悪・馬場状態',
    '枠の話': '内枠/外枠/ゲート位置',
    '季節・暑さ寒さ': '暑さ・寒さ・季節で調子が変わる',
    '休み明け': '休養明け・放牧明け・久々',
    '使って良くなる': '一度使って上向いた/叩いて良化',
    '一度使ってから': '今回は叩き台・使ってからの馬',
    '前に行く競馬': '先行したい・逃げたい・前で運ぶ',
    '控えて末脚': '控える・差す・追い込む',
    '流れ次第': '展開待ち・流れひとつ・ペース次第',
    '最後のひと押し': '決め手不足・最後に甘くなる・粘り不足',
    'スタート': '出遅れ・ゲート・スタートが鍵',
    '気性・気分': '気性・イレ込み・気分屋・テンション',
    '馬体が重め': '太め・重め残り',
    '馬体が細い': '馬体が細い・体重が減った',
    '成長': '成長した・馬体が増えた・良くなってきた体',
    '遠征・地元': '遠征・輸送・地元での競馬',
    '馬具': '馬具の着用や変更・去勢',
    '相手が強い': '相手関係・強い馬がいる・昇級',
    '砂をかぶるのが苦手': '砂をかぶる・キックバックを嫌う',
    '揉まれると弱い': '馬群で揉まれる・包まれると良くない',
}
LIST = [v[0] for v in T.M.values()] + ['砂をかぶるのが苦手', '揉まれると弱い']
assert set(LIST) == set(DEF), set(LIST) ^ set(DEF)

SYSTEM = (
    "あなたは地方競馬の厩舎関係者の談話(原文)を分類する係です。各馬の原文に当てはまる札を、下の一覧から選びます。\n"
    "決まり:\n"
    "- 原文に書いてあることだけで選ぶ。推測しない・読み込まない。\n"
    "- 当てはまる札が無ければ 0 個でよい。複数あれば全部選ぶ。\n"
    "- 一覧に無い札を作らない。札名は一覧の字のとおりに書く。\n"
    "札の一覧(札名= 定義):\n"
    + "\n".join(f"- {t}= {DEF[t]}" for t in LIST) + "\n"
    "返事は JSON だけ: {\"items\":[{\"umaban\":1,\"tags\":[\"…\"]}, …]}(前後に文を書かない)。"
)


def user_prompt(horses):
    body = [{"umaban": h["umaban"], "comment": h["comment"]} for h in horses]
    return "次の各馬の談話に札を付けてください。\n" + json.dumps(body, ensure_ascii=False)


def parse_tags(text):
    """返事 → {umaban: [札, ...]}(一覧の順・一覧に無い札は捨てる)。読めなければ {}。"""
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m:
        print(f"  ⚠JSON なし 長さ {len(text or '')}", flush=True)
        return {}
    try:
        obj = json.loads(m.group())
    except Exception as e:                       # noqa: BLE001
        print(f"  ⚠JSON 誤り {type(e).__name__}", flush=True)
        return {}
    out = {}
    for it in obj.get("items", []) if isinstance(obj, dict) else []:
        try:
            got = {str(x).strip() for x in (it.get("tags") or [])}
            out[int(it["umaban"])] = [t for t in LIST if t in got]
        except Exception:                        # noqa: BLE001
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261112)
    a = ap.parse_args()
    env = os.environ
    db = D.Rest(env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"])
    import anthropic
    cl = anthropic.Anthropic(api_key=env["ANTHROPIC_API_KEY"])
    rnd = random.Random(a.seed)
    days = [D0 + dt.timedelta(days=i) for i in range((D1 - D0).days + 1)]
    rnd.shuffle(days)
    tin = tout = n = races = 0
    for d in days:
        if n >= a.n:
            break
        rows = db.get(f"{D.SRC}?select=race_id,umaban,comment&race_date=eq.{d.isoformat()}"
                      f"&comment=not.is.null&order=race_id.asc,umaban.asc&limit=1000")
        by = {}
        for r in rows:
            if (r.get("comment") or "").strip():
                by.setdefault(r["race_id"], []).append(dict(r, umaban=int(r["umaban"])))
        if not by:
            continue
        rid = rnd.choice(sorted(by))
        hs = by[rid]
        try:
            res = cl.messages.create(model=D.MODEL, max_tokens=D.MAX_TOKENS, system=SYSTEM,
                                     messages=[{"role": "user", "content": user_prompt(hs)}])
            tin += getattr(res.usage, "input_tokens", 0) or 0
            tout += getattr(res.usage, "output_tokens", 0) or 0
            if res.stop_reason != "end_turn":
                print(f"  ⚠stop={res.stop_reason}", flush=True)
            got = parse_tags("".join(getattr(b, "text", "") for b in res.content))
        except Exception as e:                   # noqa: BLE001
            print(f"  ⚠API {type(e).__name__}", flush=True)
            got = {}
        races += 1
        for h in hs:
            u = h["umaban"]
            now = T.note_tags(h["comment"])
            hk = got.get(u)
            print(f"{rid}\t{u}\t{'・'.join(now)}\t{'・'.join(hk) if hk is not None else '(返事なし)'}", flush=True)
            n += 1
    print(f"合計 頭数 {n}・レース {races}・入力トークン {tin}・出力トークン {tout}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
