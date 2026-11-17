"""展開シミュレーターの DATA に、その日の騎手の本物の勝負服を載せる(毎日の仕組み用・出走表を読まない版・2026-11-17)。
普段は tenkai_sim_build.py が続けて呼ぶ。単独: py -3.12 -X utf8 src/f5_scripts/tenkai_silks_db.py out/tenkai_sim_1118.html
手で作った 11/16 の台本 tenkai_silks.py との違い = 馬 → 騎手の元だけ(升目の読み方 silk は同じ式):
  馬 → 騎手の短い名前 = DATA の h.jk(自分の DB の出走馬の表から tenkai_sim_live.py が入れる)
  騎手の短い名前 → 免許の番号 = 自分の DB の騎手の台帳 nar_persons(同じ短い名前が 2 人いたら 現役 → 所属がその場 → 南関 の順で 1 人に決まる時だけ使う)
  勝負服の図 = 公式サイト keiba.go.jp の /Image/Main/Uniform/U0<番号>.jpg(騎手 1 人 1 回だけ・手元に置いて 2 回目は取りに行かない)
⛔公式サイトの出走表(/KeibaWeb/TodayRaceInfo/)と騎手の頁(/KeibaWeb/DataRoom/)は robots.txt で自動の読み取りが禁じられているので読まない。
⛔robots.txt の Crawl-delay 10 に合わせ、図を取る間は 10 秒あける。
図はそのまま載せず、胴 24×32・袖 6×16 の升目ごとの色の番号(色は 5 色まで)に直して DATA.silks に入れる。
利用規約は画像の転載・複製に事前の許しを求める。2026-11-17 ユーザー「許可はもらっています」= 公に出す版にも載せる(引っ込めるときは --public / TKSIM_SILKS を外す)。
便では読み取った升目を公開バケットの 1 本(tenkai/sim/v1/silks.json)にためて、新しい騎手の図だけ取りに行く。"""
import io, json, os, sys, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tenkai_sim_live as L

CACHE = Path(os.environ.get('TKSIM_SILK_CACHE', 'C:/Users/kouki/nankan_ai/v3/tenkai_silks')); CACHE.mkdir(parents=True, exist_ok=True)   # 図の手元の置き場(便では一時の置き場)
UA = {'User-Agent': 'python-requests (tenkai silks; 1 image per rider, cached)'}
GAP = 10.0
BW, BH, SW, SH = 24, 32, 6, 16
_last = [0.0]
fetched = []


def get_image(lic):
    """図を手元から。無ければ公式サイトから 1 回だけ取る(無い騎手は空のファイルを置いて 2 度と取りに行かない)。"""
    import requests
    f = CACHE / f'U{lic}.jpg'
    if not f.exists():
        time.sleep(max(0.0, GAP - (time.time() - _last[0])))
        try:
            r = requests.get(f'https://www.keiba.go.jp/Image/Main/Uniform/U0{lic}.jpg', headers=UA, timeout=30); _last[0] = time.time()
        except Exception:
            _last[0] = time.time(); return None
        if r.status_code >= 500 or r.status_code in (403, 429): return None        # 向こうの都合 = 置かずに次の回でもう一度
        f.write_bytes(r.content if r.status_code == 200 and r.headers.get('content-type', '').startswith('image') else b''); fetched.append(lic)
    b = f.read_bytes()
    return b or None


def silk(lic):
    """勝負服の図 → 色(5 色まで)と 胴・袖の升目の色の番号。図が無ければ None。(tenkai_silks.py の silk と同じ式)"""
    from PIL import Image
    raw = get_image(lic)
    if not raw: return None
    try: im = Image.open(io.BytesIO(raw)).convert('RGB').resize((200, 200), Image.LANCZOS)
    except Exception: return None
    bc, sc = im.crop((58, 40, 142, 180)), im.crop((18, 68, 38, 172))                                   # 胴(ふちの線と襟を避けた内側)・左の袖
    px = np.vstack([np.asarray(bc, float).reshape(-1, 3), np.asarray(sc, float).reshape(-1, 3)])
    key = (px // 24).astype(int); key = key[:, 0] * 144 + key[:, 1] * 12 + key[:, 2]
    ks, cnt = np.unique(key, return_counts=True)
    cen = sorted(((px[key == k].mean(0), n) for k, n in zip(ks, cnt)), key=lambda c: -c[1])
    keep = []
    for c, n in cen:
        if keep and n < 0.008 * len(px): continue
        if any(np.abs(c - k).sum() < 90 for k in keep): continue
        mix = False
        for a in range(len(keep)):
            for b in range(a + 1, len(keep)):
                ab = keep[b] - keep[a]; t = np.clip(((c - keep[a]) @ ab) / (ab @ ab), 0, 1)
                if np.linalg.norm(c - (keep[a] + t * ab)) < 45 and 0.1 < t < 0.9: mix = True
        if not mix: keep.append(c)
    keep = np.array(keep[:5])

    def grid(crop, w, h):   # 升ごとに、その中の画素の色の番号の多数決
        a = np.asarray(crop, float); lab = np.abs(a[:, :, None, :] - keep[None, None, :, :]).sum(3).argmin(2); H, W = lab.shape; out = []
        for y in range(h):
            for x in range(w):
                blk = lab[y * H // h:(y + 1) * H // h, x * W // w:(x + 1) * W // w].ravel(); out.append(str(np.bincount(blk, minlength=len(keep)).argmax()))
        return ''.join(out)
    hexs = ['#%02x%02x%02x' % tuple(int(round(v)) for v in c) for c in keep]
    return {'p': hexs, 'b': grid(bc, BW, BH), 's': grid(sc, SW, SH)}


def licenses(names, track):
    """騎手の短い名前 → 免許の番号(1 人に決まらない名前は入れない)。台帳は 1 回の読みで済ます。"""
    names = sorted(set(names))
    if not names: return {}
    rows = L.rest('nar_persons?select=license_no,name_short,area,active&kind=eq.jockey&name_short=in.(%s)' % ','.join(L._q(n) for n in names))
    out, full = {}, None

    def loose(n, r):   # 出走表の略し方が決まりと違う人(本田正重 → 本田重 など): 姓の頭 + 名の中の字(順は保つ)
        sei, mei = r.get('name_sei') or '', r.get('name_mei') or ''
        for k in range(1, len(n)):
            if sei[:max(k, min(len(sei), 2))] == n[:k] or sei == n[:k]:
                it = iter(mei)
                if all(ch in it for ch in n[k:]): return True
        return False
    for n in names:
        c = [r for r in rows if r['name_short'] == n]
        if not c:
            if full is None: full = L.rest('nar_persons?select=license_no,name_short,name_sei,name_mei,area,active&kind=eq.jockey&active=eq.true&limit=2000')
            c = [r for r in full if loose(n, r)]
        for keep in (lambda r: r.get('active'), lambda r: r.get('area') == track, lambda r: r.get('area') in L.NK):
            if len(c) > 1 and any(keep(r) for r in c): c = [r for r in c if keep(r)]
        if len(c) == 1: out[n] = str(c[0]['license_no'])
    return out


def attach(data, store=None):
    """DATA に h.sk と DATA.silks を足す。store = 既に読み取ってある升目 {免許の番号: 升目}(あれば図を取りに行かない・新しく読んだ分を足して返す)。戻り = 数え。"""
    hs = [h for r in data['races'] for h in r['h']]
    for h in hs: h.pop('sk', None)
    lic = licenses([h['jk'] for h in hs if h.get('jk')], data['track'])
    silks = {}
    store = {} if store is None else store
    for h in hs:
        k = lic.get(h.get('jk'))
        if not k: continue
        if k not in silks:
            if k not in store:
                v = silk(k)
                if v: store[k] = v
            silks[k] = store.get(k)
        if silks[k]: h['sk'] = k
    data['silks'] = {k: v for k, v in silks.items() if v}
    dup = sum(len(x) - len(set(x)) for x in ([h['sk'] for h in r['h'] if h.get('sk')] for r in data['races']))
    return {'馬': len(hs), '本物の勝負服が付いた馬': sum(1 for h in hs if h.get('sk')),
            '騎手の名前が無い馬': sum(1 for h in hs if not h.get('jk')),
            '番号が決まらない騎手': sorted({h['jk'] for h in hs if h.get('jk') and h['jk'] not in lic}),
            '図が無い騎手': sorted({h['jk'] for h in hs if lic.get(h.get('jk')) and not silks.get(lic[h['jk']])}),
            '騎手': len(data['silks']), '新しく取った図': len(fetched), '同じ R で騎手の重なり': dup}


if __name__ == '__main__':
    import tenkai_sim_build as B
    B.env()
    HTML = Path(sys.argv[1]); src = HTML.read_text(encoding='utf-8')
    i = src.index('const DATA = ') + len('const DATA = '); e = src.index('\n', i)
    data = json.loads(src[i:e].rstrip().rstrip(';'))
    print(attach(data))
    HTML.write_text(src[:i] + json.dumps(data, ensure_ascii=False) + ';' + src[e:], encoding='utf-8')
