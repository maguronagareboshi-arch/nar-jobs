# -*- coding: utf-8 -*-
"""厩舎談話の言い回しの型(2026-10-14・パターン化)。⛔予想の計算には使わない(表示だけ)。
談話 → 見出し + 節に分ける → 数字・距離・クラス・場名・騎手名・つなぎの語・丁寧語・語尾をならして「型」の鍵にする。
型ごとの札はエージェントが付けた辞書(out/dw_pat/)を引く。本番は素の Python だけで動く。
"""
import re
import unicodedata

VENUES = ('大井|川崎|船橋|浦和|門別|盛岡|水沢|金沢|笠松|名古屋|園田|姫路|高知|佐賀|帯広|ホッカイドウ|北海道|岩手|兵庫|愛知|東海|'
          '九州|中京|阪神|京都|東京|中山|新潟|福島|小倉|札幌|函館')

# 節の切れ目にする「、」の手前の言い終わり(理由・逆接・条件・並べ・て形)
CUT = re.compile(r'(?:が|けど|けれど|けれども|ので|から|し|ば|なら|たら|だら|ても|でも|のに|ものの|とはいえ|ながら|て|で)$')
LEAD = re.compile(r'^(?:ただ|ただし|でも|それでも|まあ|まぁ|あと|それに|また|なので|だから)、')
# 札を変えないつなぎの語(理由・逆接・並べ)。「叩いてから」の「から」は残す(手前が言い切りの時だけ外す)
CONJ = [re.compile(r'(?<=[いただるずうんす])(?:けれども|けれど|けど|から|が|し)$'),
        re.compile(r'(?:なので|ので|のに|ものの|とはいえ)$')]
# 丁寧語 → 常体(鍵だけの書き換え。エージェントに見せるのは一番多い元の形)
POLITE = [
    ('ていません', 'ていない'), ('ありません', 'ない'), ('ません', 'ない'),
    ('でしょう', 'だろう'), ('でした', 'だった'),
    ('ていました', 'ていた'), ('ています', 'ている'), ('ました', 'た'), ('します', 'する'), ('います', 'いる'),
    ('ます', 'る'),
]
TAIL = re.compile(r'(?:と思います|と思う|ですよね|ですね|ですよ|です|よね|ねえ|ね|よ|な|わ|(?<!ま)だ)$')


def nfkc(s):
    return unicodedata.normalize('NFKC', re.sub(r'\s+', '', s if isinstance(s, str) else ''))


def split(text):
    """→ (見出し, [節...])。見出し = 最初の「。」の手前(空もある)。"""
    t = nfkc(text)
    head, body = t.split('。', 1) if '。' in t else ('', t)
    out = []
    for sent in re.split(r'[。!?]', body):
        if not sent:
            continue
        buf = ''
        for seg in re.split(r'(、)', sent):
            if seg == '、':
                if CUT.search(buf):
                    out.append(buf)
                    buf = ''
                else:
                    buf += '、'
            else:
                buf += seg
        if buf:
            out.append(buf)
    return head, out


def split2(text):
    """→ (見出し, [(節, 文の番号)...])。split と同じ切り方で、どの文の節かも返す。"""
    head, out = split(text)
    t = nfkc(text)
    body = t.split('。', 1)[1] if '。' in t else t
    sents = [x for x in re.split(r'[。!?]', body) if x]
    got, si, pos = [], 0, 0
    for c in out:
        while si < len(sents) and c not in sents[si][pos:]:
            si, pos = si + 1, 0
        if si < len(sents):
            pos = sents[si].index(c, pos) + len(c)
        got.append((c, min(si, len(sents) - 1)))
    return head, got


def key(clause):
    """節(か見出し)→ 型の鍵。"""
    s = clause
    s = re.sub(r'\d{3,4}(?:メートル|m|M)', '#m', s)
    s = re.sub(r'\d{3,}', '#', s)
    s = re.sub(r'[ABC][1-3](?:[一二三四五六七八九十]+|\([一二三四五六七八九十]+\))?', '@級', s)
    s = re.sub(VENUES, '@場', s)
    s = re.sub(r'[一-龥々ァ-ヶー]{1,5}(?=騎手|ジョッキー)', '@', s)
    s = LEAD.sub('', s)
    for _ in range(4):
        prev = s
        s = s.rstrip('、…・')
        s = TAIL.sub('', s)
        for c in CONJ:
            s = c.sub('', s)
        for a, b in POLITE:
            if s.endswith(a):
                s = s[:-len(a)] + b
                break
        if s == prev:
            break
    return s


# ---- 札を付ける(本番の形・素の Python) ----
import gzip  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402

ONE_OF = ('S', 'E')  # 状態と結論は談話に 1 つまで(後ろの節 = 結びを優先)
# 過去形の節(「展開が向いたとはいえ」)は前走の話: 補助の読み手から流れ次第 R1・結論 E を出さない。
# 「前走・前回」と言う過去形の節は前のレースの走り(手引き = P)なので、運び R・条件 C も出さない。
# 相手 A(「メンバーが揃った」)と脚質の R2〜R6 は過去形でも今回の話のことが多いので残す(尾の見本・調整用で確かめ)
PAST = re.compile(r'た$')
# 反証(out/dw_pat/audit_report.md・10/14)の直し。K['fix'] に入れた番号だけ効く(本番は全部)
FIX_ALL = {1, 2, 3, 4, 5, 7, 8}
# 1. 故障・病気の安全網: 病名がはっきりした語があれば D1 を必ず出す(歩様・トモ・蹄・治療のような普通の言い回しにも出る語は入れない)
ILL = re.compile(r'神経痛|ヘルニア|外傷|裂傷|打撲|ケガ|怪我|熱発|発熱|熱を出|鼻出血|鼻血|喉|ノド|喘鳴|心房細動|疝痛|骨折|骨片|剥離|屈腱|腱炎|靭帯|球節|捻挫|ソエ|骨瘤|跛行|ハ行|笹針|手術|ショックウェーブ|挫石|挫跖|裂蹄')
ILL_NOT = re.compile(r'(?:喉|ノド)(?:の)?(?:渇|乾)|手術(?:は|も)?(?:せず|しない|なし)')
# 2. 「前走・前回」と言う節は過去形でなくても前のレースの話: 補助から今回の札(運び R・条件 C・相手 A・使い方 U・結論 E)を出さない
PREV_DROP = ('R', 'C', 'A', 'U', 'E')
# 3. 打ち消しの見張り: 「問題はない・気にならない・苦にしない」の節では、補助から不安側の札を出さない
NEG_OK = re.compile(r'問題(?:は|も)?な|問題(?:は|も)?ありません|気になら|心配(?:は|も)?な|心配(?:は|も)?ありません|苦にしな|大丈夫|こなせ|融通が利')
WORRY = ('C2', 'C4', 'A2', 'H4', 'B1', 'B2', 'S3', 'P6', 'D1')
# 5. 向きのはっきりした言い回しの表(型・補助どちらの札にも当てる): (語, 外す札, 足す札)
WORD_FIX = [
    (re.compile(r'経験を積(?:んで|ん|め)'), ('H4',), ('H5',)),
    (re.compile(r'重い(?:なか|中|馬場)|馬場が重|重馬場|重(?:い|たい)ダート'), ('B1',), ()),  # 重い = 馬場の重さ(太めではない)
    # 11R(10/14)の読み違い
    (re.compile(r'前走より|前回より|前走から(?:比べ|見)'), ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8'), ()),  # 「前走より体が大きく」は前走の評価ではない
    (re.compile(r'(?:集中|走りに集中)(?:できる|できれば|すると)(?:と)?(?:強|しっかり|走)'), ('M1',), ()),  # 前向きの言い方の集中
    (re.compile(r'発展途上|まだ(?:体が)?(?:子供|幼い|成長途上)|成長途上'), ('S3',), ('B4',)),
    # 最後の判定(final_report.md)の読み違い
    (re.compile(r'速い時計(?:が|も)?(?:ある|出せ|持)|持ち時計(?:が|は)?(?:上|速|ある)|時計(?:は|も)?(?:速い|上位|互角|足りる)'), ('T1',), ()),
    (re.compile(r'(?:速い|軽い|脚抜きのいい)馬場(?:が|は)?(?:合|向|得意|理想|いい)|時計のかかる馬場(?:は|が)?(?:合わ|向かな|苦手)'), ('C12',), ('C13',)),
    (re.compile(r'物足りな'), ('P1', 'P2'), ()),
    (re.compile(r'きっかけ'), ('S3',), ('L1',)),  # きっかけ待ち = 近走不振(状態の話ではない)
    (re.compile(r'[2２二]着|連対|好走'), ('P7', 'L1'), ()),
    (re.compile(r'(?:デキ|出来|状態|仕上がり)(?:は|も|が)?(?:まだ)?[0-9七八]+(?:[〜~][0-9七八九]+)?分'), ('S1', 'S2'), ('S3',)),
    (re.compile(r'相手(?:も|は)?(?:手頃|楽)|メンバー(?:も|は)?(?:手頃|楽)'), ('A2',), ('A1',)),
    (re.compile(r'追い切(?:り)?(?:を|も)?(?:やり|し)?切れ(?:てい)?な|攻め切れ|乗り込み不足|追い切れ(?:てい)?な'), (), ('K2',)),
    (re.compile(r'上積みまでは|上積み(?:は|が)?(?:どうか|ない|なさそう|見込めな|期待できな)'), ('U1',), ()),
    # 反証 2(audit2_report.md)の向き違い
    (re.compile(r'悪くな(?:い|かっ)|悪くはな'), ('L1', 'P6', 'P7', 'S3', 'E4'), ()),
    (re.compile(r'もうひと押し|もう一押し'), ('P1',), ()),
    (re.compile(r'もうひと追い|もう一追い|もう少し乗り込|乗り込みがほしい|乗り込みが欲しい|仕上がり(?:は|も)?[0-9]分|[7-9七八九]分(?:の|程度|ぐらい|くらい)?(?:の)?(?:仕上|デキ|出来)'), ('S1',), ('K2',)),
    (re.compile(r'(?:休み明け|放牧明け|久々)を?[2-3二三]度(?:叩|使)'), ('U2',), ('U1',)),
    (re.compile(r'間隔が(?:あまり)?(?:ない|詰ま|短)'), ('U2',), ('U4',)),
]
ONLY_ONE = (('K2', 'S1'),)  # 調整不足と状態が良いが並んだら、調整不足だけ残す
LAST_WINS = (('M1', 'M2'), ('C2', 'C8'))  # 気性の課題と良さが並んだら、後ろの節(結び)の方だけ残す
# 7. 補助の読み手が外れやすく、外れると向きを誤解させる札は補助から出さない(辞書の型からは出す)。
#    正解 1,000 件で補助の正しさ L1 55%・Q2 60%・C2 71%・A1 78%・C9/E4/S4 80%(10/14)
FALLBACK_MUTE = {'L1', 'Q2', 'C2', 'A1', 'C9', 'E4', 'S4'}
# 8. 文の流れ: 文の中で「前走は・前回は・デビュー戦は」の後、「今回・今度・ここ」が出るまでの節は前の回の話。
#    今・今回の札(休み明け・初出走・馬体・状態・調教・条件・運び・相手・結論)を出さない(辞書の札にも当てる・前走 P・近走 L・馬 Q・気性 M・故障 D・騎手 J は残す)
PAST_START = re.compile(r'前走|前回|前々走|前\d走|この前|デビュー戦(?:は|で|の)|初戦(?:は|で|の)|新馬戦(?:は|で|の)|転入(?:初)?戦(?:は|で|の)|前のレース')
PAST_END = re.compile(r'今回|今度|ここ|今は|今の|次|この中間|中間|現状|このクラス|このメンバー|前走後|前回後|その後')
PAST_KEEP = ('P', 'L', 'Q', 'M', 'D', 'J', 'H1', 'Y', 'G', 'S', 'K')  # 状態と調教はほぼいつも今の話
PAST_CMP = re.compile(r'(?:前走|前回|前々走)(?:時)?(?:より|と(?:比べ|変わ|同じ)|並み|から|後|以上|以来|の後)')  # 比べの言い方は前の回の話ではない
PAST_GO = re.compile(r'(?:て|で|ており|ていて|でいて)$')  # 前の回の話が次の節へ続くのは「〜て・〜で」だけ
# 4. 画面の矛盾を出さない: 向きが逆の組は後ろの節の札だけ残す
PAIRS = (('A1', 'A2'), ('C1', 'C2'), ('C3', 'C4'), ('H4', 'H5'), ('S1', 'S3'), ('S2', 'S3'))
PREV = re.compile(r'前走|前回|前々走|前\d走|この前')


def load(dict_path, model_path=None):
    """辞書(型の鍵 → 札)と補助の読み手(辞書に無い節用)を読む。"""
    def _read(path):  # .json か .json.gz(本番は圧縮して置く)
        path = str(path)
        with (gzip.open(path, 'rt', encoding='utf-8') if path.endswith('.gz') else open(path, encoding='utf-8')) as f:
            return json.load(f)
    d = _read(dict_path)
    m = _read(model_path) if model_path else None
    return {'clause': d['clause'], 'head': d['head'], 'model': m, 'tail': 'mix', 'oneof': 'last',
            'ctx': {'clause': set(d.get('ctx_clause', [])), 'head': set(d.get('ctx_head', []))}, 'ctx_mode': 'keep'}


def _grams(t, n_max):
    out = {}
    for n in range(1, n_max + 1):
        for i in range(len(t) - n + 1):
            g = t[i:i + n]
            out[g] = out.get(g, 0) + 1
    return out


def _model_scores(M, text):
    """補助の読み手の確率 {札: p}(文字 1〜4 字 × 札ごとの回帰)。sklearn の TfidfVectorizer(char, sublinear_tf, l2) + LogisticRegression と同じ計算。
    l2 の大きさは削った語彙で計るので学びの時と少しずれる(尾の見本で札の一致を確かめ済み)。"""
    idf, W, B = M['idf'], M['coef'], M['bias']
    v = {g: (1.0 + math.log(c)) * idf[g] for g, c in _grams(text, M['n_max']).items() if g in idf}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    p = {}
    for code in M['codes']:
        w = W[code]
        if not w:
            continue
        z = B[code] + sum(x * w.get(g, 0.0) for g, x in v.items()) / norm
        p[code] = 1.0 / (1.0 + math.exp(-z))
    return p


def _pick(p, th, extra=()):
    """確率 → 札(しきい値以上 + extra)。状態 S と結論 E は 1 つ(しきい値を一番大きく越えた札)。"""
    got = [c for c in p if p[c] >= th[c]] + [c for c in extra if c in p]
    got = list(dict.fromkeys(got))
    for one in ONE_OF:
        same = [c for c in got if c.rstrip('0123456789') == one]
        if len(same) > 1:
            keep = max(same, key=lambda c: p[c] - th[c])
            got = [c for c in got if c.rstrip('0123456789') != one or c == keep]
    return got


def _model_tags(M, text):
    return _pick(_model_scores(M, text), M['th'])


def _seg_tags(table, k, min_cover=0.6, min_len=2):
    """辞書に無い節を「辞書にある型のつなぎ」として読む。結び(節の終わり)が辞書の型で覆えた時だけ札を出す。
    覆う字数が最大になる切り方(同じなら切れ目が少ない方)。状態 S と結論 E は後ろの型を取る。→ (札, 使った型) か None"""
    L = len(k)
    if L < 2:
        return None
    best = [(0, 0, None)] * (L + 1)  # best[j] = (覆った字数, -切れ目の数, 前の位置と型)
    for j in range(1, L + 1):
        cand = (best[j - 1][0], best[j - 1][1], (j - 1, None))  # j-1 字目は覆わない
        for i in range(max(0, j - 40), j - min_len + 1):
            piece = k[i:j]
            if piece in table:
                c = (best[i][0] + (j - i), best[i][1] - 1, (i, piece))
                if c[:2] > cand[:2]:
                    cand = c
        best[j] = cand
    if best[L][2] is None or best[L][2][1] is None or best[L][0] < min_cover * L:
        return None
    pieces, j = [], L
    while j > 0 and best[j][2] is not None:
        i, piece = best[j][2]
        if piece is not None:
            pieces.append(piece)
        j = i
    pieces.reverse()
    got = []
    for piece in pieces:
        for c in table[piece].split():
            if c.rstrip('0123456789') in ONE_OF:
                got = [x for x in got if x.rstrip('0123456789') != c.rstrip('0123456789')]
            if c not in got:
                got.append(c)
    return got, pieces


def read(K, text, why=None):
    """談話 → 札のリスト。why に list を渡すと、節ごとの読み(節・型の鍵・札・出どころ)を足す。
    出どころ = 型(辞書にある言い回し)/ つなぎ(辞書の型のつなぎで読めた)/ 補助(辞書から学んだ読み手)/ なし。"""
    h, cl = split2(text)
    seq = []  # (札, 見出しか)
    units = ([(h, True, -1)] if h else []) + [(c, False, si) for c, si in cl]
    past, cur_si, go = False, None, False
    for raw, is_head, si in units:
        if si != cur_si:
            past, cur_si, go = False, si, False  # 文が替われば前の回の話は終わり
        if not is_head:
            if PAST_START.search(raw) and not PAST_CMP.search(raw) and not PAST_END.search(raw):
                past = True
            elif not (past and go) or PAST_END.search(raw):
                past = False
            go = bool(PAST_GO.search(raw))
        k = key(raw)
        if not k:
            continue
        table = K['head'] if is_head else K['clause']
        tail = K.get('tail', 'mix')  # 辞書に無い節: mix = 補助 + 補助も半分以上うなずく「つなぎ」の札 / seg = つなぎ優先 / model = 補助だけ
        seg = None if k in table or tail == 'model' else _seg_tags(table, k, min_cover=0.3)
        if k in table and k in K['ctx']['head' if is_head else 'clause'] and K.get('ctx_mode') != 'keep':
            # 前後の文で意味が決まる型: drop = 札を出さない / model = 補助の読み手に回す
            if K['ctx_mode'] == 'drop' or K['model'] is None:
                tags, src = [], '文脈'
            else:
                M = K['model']
                tags, src = _pick(_model_scores(M, ('^' if is_head else '') + k), M['th']), '文脈'
        elif k in table:
            tags, src = table[k].split(), '型'
        elif tail == 'seg' and seg is not None:
            tags, src = seg[0], 'つなぎ'
        elif K['model'] is not None:
            M = K['model']
            p = _model_scores(M, ('^' if is_head else '') + k)
            extra = [c for c in (seg[0] if seg else []) if p.get(c, 0.0) >= 0.5 * M['th'][c]] if tail == 'mix' else []
            tags, src = _pick(p, M['th'], extra), '補助'
            fix = K.get('fix', FIX_ALL)
            if 2 in fix and PREV.search(k):
                tags = [c for c in tags if c.rstrip('0123456789') not in PREV_DROP]
            elif K.get('past', 'on') == 'on' and PAST.search(k):
                drop = ('R', 'E', 'C') if PREV.search(k) else ('R1', 'E', 'C5', 'C12', 'C13')  # 過去形の節の馬場は前の回の馬場の話
                tags = [c for c in tags if c not in drop and c.rstrip('0123456789') not in drop]
            if 7 in fix:
                tags = [c for c in tags if c not in FALLBACK_MUTE]
            if 3 in fix and NEG_OK.search(raw):
                tags = [c for c in tags if c not in WORRY]
        elif seg is not None:
            tags, src = seg[0], 'つなぎ'
        else:
            tags, src = [], 'なし'
        if 8 in K.get('fix', FIX_ALL) and past:
            tags = [c for c in tags if c in PAST_KEEP or c.rstrip('0123456789') in PAST_KEEP]
        if 5 in K.get('fix', FIX_ALL):
            for rx, out, add in WORD_FIX:
                if rx.search(raw):
                    tags = [c for c in tags if c not in out] + [c for c in add if c not in tags]
        seq.append((tags, is_head))
        if 1 in K.get('fix', FIX_ALL) and ILL.search(raw) and not ILL_NOT.search(raw) and 'D1' not in tags:
            seq[-1] = (tags + ['D1'], is_head)
            tags = seq[-1][0]
        if why is not None:
            why.append((raw, k, tags, src))
    got = []
    for tags, _ in seq:
        got += [c for c in tags if c.rstrip('0123456789') not in ONE_OF and c not in got]
    if 4 in K.get('fix', FIX_ALL):
        last = {c: n for n, (tags, _) in enumerate(seq) for c in tags}  # 札ごとに最後に出た節
        for a, b in PAIRS:
            if a in last and b in last:
                lose = a if last[a] < last[b] else b if last[b] < last[a] else None
                got = [c for c in got if c not in (lose, ) and (lose or c not in (a, b))]
        for a, b in LAST_WINS:
            if a in got and b in got:
                got.remove(a if last[a] < last[b] else b)
        for keep, lose in ONLY_ONE:
            if keep in got and lose in got:
                got.remove(lose)
    mode = K.get('oneof', 'last')
    for one in ONE_OF:
        hits = [(is_head, c) for tags, is_head in seq for c in tags if c.rstrip('0123456789') == one]
        if not hits:
            continue
        if mode == 'first':
            pick = hits[0][1]
        elif mode == 'body_last':  # 本文にあれば本文の最後・無ければ見出し
            body = [c for is_head, c in hits if not is_head]
            pick = body[-1] if body else hits[-1][1]
        else:  # last = 結びを優先
            pick = hits[-1][1]
        got.append(pick)
    if 5 in K.get('fix', FIX_ALL):  # 談話全体で向きが決まる言い回し
        t = nfkc(text)
        if re.search(r'物足りな', t) and 'P1' in got:
            got = [c for c in got if c != 'P1'] + ([] if 'P7' in got else ['P7'])
        if re.search(r'[2２二]着|連対', t):
            got = [c for c in got if c not in ('P7', 'L1')]
    if 'D2' in got and 'D1' not in got:
        got.append('D1')
    return got
