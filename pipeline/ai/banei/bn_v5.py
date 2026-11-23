# -*- coding: utf-8 -*-
"""ばんえい(帯広)第 5 版の部品(ばんえい 決め 12・2026-11-19 合格・nankan-ai-v3 の out/banei_k12_prereg.md)。banei_v3.py が呼ぶ。

研究の写し(計算は同じ・「学ぶ」と「当てる」を分けた):
  土台の木 種 1・2   = v3 の src/banei/seedavg_check.make_parts(第 2 版の木を種だけ替える)→ banei_v3.tree_fit(seed=s)
  CatBoost          = src/banei/mix_pre.make('CB')
  NN 種 0〜2         = src/banei/mix_nn_pre.make(表の材料の全結合・学びの回数は固定 = 定数の nn_epochs)
  並び読み X          = src/banei/seqb5_pre.setup30 + inputs('X') + seq_month(過去 30 走 + 過去走の AI の見込みと外れ + 馬主の替わり
                       + 確定単勝の率を学びだけの補助の答えに・種 801〜803)
  z = T と平らな模型の混ぜ + X + b × 能検、T = 種 0・1・2 の木・CatBoost・NN 0〜2 のロジットの混ぜ(割合は固めた表)

毎朝の読み手(便の中で作る):
  過去 30 走     = seq_banei.build を H = 30 で(banei_v3.seq_arrays(h=30))。10 走の表(平らな模型)とは別に作る。
  過去の AI の見込み = banei_v3.oof_table(第 2 版 種 0 の外した予想 = 固めた表 + 本番の行の meta.p_v2 + 月ごとの埋め)。第 4 版の並び読みの土台と同じ物。
  馬主           = 固めた表 banei_kb/kd_se_owner_banei.parquet(KDSCOPE SE の帯広・その最後の日まで)+ その後と今日の馬は DB の
                   nar_horses の今の馬主から、その日より後の owner_change を戻した値(南関の v7c_owner と同じ決まり)。
                   名前は空白と法人の印((株)(有)…)を外してから比べる(台帳は「曽我部 裕」・DB は「曽我部裕」「（有）竹内産業」)。
  確定単勝(学びの答えだけ)= 固めた表 banei_kb/win_odds_frozen.parquet(競馬ブック・その最後の日まで)+ その後は DB の
                   nar_odds_ticks の確定(f = true)の単勝。予想の入力には入れない。
数(重み・NN の回数・能検の b・勝つ率の b1)は公開のコードに書かない = 固めた表のリリースの banei_kb/banei_v5.json。
"""
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd

import feat_v1 as f1
import seq_core as sc

K = ['race_date', 'race_no', 'runner_number']
H = 30
SEEDS_T = (1, 2)
SEEDS_X = (801, 802, 803)
NN_SEEDS = (0, 1, 2)
NT = sc.NT
TT = int(os.environ.get('BANEI_TREE_THREADS', '16'))
lg = sc.lg
RE_CORP = re.compile(r'[\(（](株|有|同|合|資|名|医|財|社|一社|一財|公財|組|農)[\)）]|^(組|農)[\)）]')
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:7.0f}s] [v5]', *a, flush=True)


def consts_path():
    return os.environ.get('BANEI_V5', f1.OUT + 'banei_v5.json')


def on():
    """第 5 版の数(固めた表のリリース)があるか。無ければ第 4 版の作りのまま。"""
    return os.path.exists(consts_path())


def consts():
    return json.load(open(consts_path(), encoding='utf-8'))


def norm(x):
    x['race_date'] = x.race_date.astype(str).str[:10]; x['race_no'] = x.race_no.astype(int); x['runner_number'] = x.runner_number.astype(int)
    return x


# ---------------------------------------------------------------- 表の材料の模型(CatBoost・NN)
def train_rows(D2, lo):
    """土台の木と同じ学びの行(banei_v3.tree_fit と同じ)。研究 v2_check.load と同じ並び(K の順)。"""
    L = json.load(open(os.environ.get('BANEI_LOCK', f1.OUT + 'banei_v2_lock.json'), encoding='utf-8'))
    d = D2[(D2.scratch == 0)]
    tr = d[d.y_top3.notna() & (d.race_date >= L['start']) & (d.race_date < lo)].sort_values(K)
    return tr, L['cols_v1'] + L['cols_v2']


def cb_fit(tr, cols):
    from catboost import CatBoostClassifier
    m = CatBoostClassifier(iterations=800, learning_rate=0.05, depth=6, l2_leaf_reg=3, rsm=0.5, random_seed=0, thread_count=TT, verbose=0, allow_writing_files=False)
    m.fit(tr[cols], tr.y_top3.astype(int))
    return m


def cb_load(path):
    from catboost import CatBoostClassifier
    m = CatBoostClassifier(); m.load_model(str(path))
    return m


def numeric(d, cols):
    X = np.empty((len(d), len(cols)), dtype='float32')
    for j, c in enumerate(cols):
        s = d[c]
        if isinstance(s.dtype, pd.CategoricalDtype):
            v = s.cat.codes.astype('float32').values; v[v < 0] = np.nan
        elif s.dtype == object:
            v = pd.to_numeric(s, errors='coerce').astype('float32').values
        else:
            v = s.astype('float32').values
        X[:, j] = v
    return X


def nn_prep(Xtr):
    rng = np.random.default_rng(0)
    s = Xtr[np.sort(rng.choice(len(Xtr), min(150_000, len(Xtr)), replace=False))].astype('float64')
    Q = np.nanquantile(s, np.linspace(0, 1, 201), axis=0)
    flag = np.where(np.isnan(s).mean(0) >= 0.01)[0]
    return Q, flag


def nn_transform(X, Q, flag):
    n, p = X.shape
    out = np.zeros((n, p + len(flag)), dtype='float32')
    lv = np.linspace(0, 1, 201)
    for c in range(p):
        x = X[:, c].astype('float64'); q = Q[:, c]; nan = np.isnan(x)
        if np.isnan(q).all() or q[0] == q[-1]:
            continue
        qq, idx = np.unique(q, return_index=True)
        v = (np.interp(np.where(nan, qq[0], x), qq, lv[idx]) - 0.5) * 4
        v[nan] = 0; out[:, c] = v
    for k, c in enumerate(flag):
        out[:, p + k] = np.isnan(X[:, c])
    return out


def nn_net(p):
    import torch.nn as nn
    return nn.Sequential(nn.Linear(p, 256), nn.SiLU(), nn.Dropout(0.3),
                         nn.Linear(256, 128), nn.SiLU(), nn.Dropout(0.2), nn.Linear(128, 1))


def nn_fit(tr, cols, epochs, seed):
    import torch
    torch.manual_seed(seed); torch.set_num_threads(NT)
    Xt = numeric(tr, cols); Q, flag = nn_prep(Xt)
    Xn = nn_transform(Xt, Q, flag); y = tr.y_top3.astype(int).values
    m = nn_net(Xn.shape[1])
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    bce = torch.nn.BCEWithLogitsLoss()
    rng = np.random.default_rng(seed); n, bs = len(Xn), 2048
    for _ in range(epochs):
        m.train(); perm = rng.permutation(n)
        for a in range(0, n, bs):
            i = perm[a:a + bs]
            loss = bce(m(torch.from_numpy(Xn[i]))[:, 0], torch.from_numpy(y[i].astype('float32')))
            opt.zero_grad(); loss.backward(); opt.step()
        sch.step()
    return dict(state={k: v.clone() for k, v in m.state_dict().items()}, Q=Q, flag=flag, p=int(Xn.shape[1]))


def nn_apply(st, d, cols):
    import torch
    torch.set_num_threads(NT)
    m = nn_net(st['p']); m.load_state_dict(st['state']); m.eval()
    with torch.no_grad():
        o = torch.sigmoid(m(torch.from_numpy(nn_transform(numeric(d, cols), st['Q'], st['flag'])))[:, 0]).numpy()
    return np.clip(o.astype('float64'), 1e-6, 1 - 1e-6)


def nn_save(states, path):
    import torch
    torch.save([dict(state=s['state'], Q=s['Q'], flag=s['flag'], p=s['p']) for s in states], path)


def nn_load(path):
    import torch
    return torch.load(path, weights_only=False)


# ---------------------------------------------------------------- 馬主(走った時の馬主)
def oname(s):
    if not isinstance(s, str):
        return None
    s = RE_CORP.sub('', s.replace('　', '').replace(' ', '')).strip()
    return s or None


def _rest(path):
    import bn_kb
    return bn_kb.rest(path)


def db_owner_asof(names, lo, days):
    """馬名 → {日付: その日の馬主}(nar_horses の今の馬主 + その日より後の owner_change を戻す)。v7c_owner.db_owner_asof と同じ。"""
    names = sorted({n for n in names if isinstance(n, str) and n})
    cur = {}
    for i in range(0, len(names), 100):
        q = 'in.(' + ','.join('"' + n.replace('"', '') + '"' for n in names[i:i + 100]) + ')'
        for x in _rest('/rest/v1/nar_horses?select=horse_name,owner&limit=5000&horse_name=' + urllib.parse.quote(q)):
            cur[x['horse_name']] = x['owner']
    ch, off = [], 0
    while True:
        r = _rest('/rest/v1/nar_horse_changes?select=horse_name,race_date,from_value&kind=eq.owner_change'
                  f'&race_date=gt.{lo}&order=race_date.desc,horse_name&limit=1000&offset={off}')
        ch += r
        if len(r) < 1000:
            break
        off += 1000
    hist = {}
    for c in ch:
        hist.setdefault(c['horse_name'], []).append(c)
    out = {}
    for n, o0 in cur.items():
        out[n] = {}
        for d in days:
            o = o0
            for c in hist.get(n, []):
                if str(c['race_date'])[:10] > d:
                    o = c['from_value']
            out[n][d] = o
    return out


def owner_table(E, names, day):
    """行(K)ごとの走った時の馬主(名前はならした形)。台帳の最後の日より後の行と今日の行は DB から。DB が読めなければ空(= 馬主の分からない走り)。"""
    kd = pd.read_parquet(f1.OUT + 'kd_se_owner_banei.parquet')
    kd = kd.rename(columns={'race': 'race_no', 'umaban': 'runner_number'}).dropna(subset=['race_date', 'race_no', 'runner_number'])
    kd = norm(kd).drop_duplicates(K)[K + ['owner']]
    kmax = str(kd.race_date.max())[:10]
    w = norm(E[K].copy()).merge(kd, on=K, how='left', validate='m:1')
    w['owner'] = w.owner.map(oname)
    w['horse_name'] = names
    late = (w.race_date > kmax) & (w.race_date <= day) & w.owner.isna()
    info = dict(台帳の最後の日=kmax, 台帳の後の行=int(late.sum()))
    keys = set(kd.owner.map(oname).dropna())
    pre = sorted((k for k in keys if len(k) >= 4), key=len, reverse=True)

    def fit(o):
        # 台帳は長い名前が 7 文字で切れ「組合」などを落とす(トンデンファー・スピカスタッペン)→ DB の名前を台帳の名前の前方一致に寄せる(南関の v7c_owner と同じ)
        o = oname(o)
        if o is None or o in keys:
            return o
        return next((k for k in pre if o.startswith(k)), o)
    if late.any() and os.environ.get('BANEI_NO_DB') != '1':
        try:
            db = db_owner_asof(w.horse_name[late].tolist(), kmax, sorted(w.race_date[late].unique()))
            w.loc[late, 'owner'] = [fit(db.get(n, {}).get(d)) for n, d in zip(w.horse_name[late], w.race_date[late])]
        except Exception as e:  # noqa: BLE001  ⛔DB が読めない日は台帳の後を空(馬主の分からない走り)で続ける
            info['DB'] = repr(e)[:160]
    info['台帳の後 取れた'] = int((late & w.owner.notna()).sum())
    log('馬主', info)
    return w[K + ['owner']], info


# ---------------------------------------------------------------- 確定単勝(学びの補助の答えだけ)
def final_odds(since):
    """DB の nar_odds_ticks の確定(f = true)の単勝 → K + win_odds。読めなければ空。"""
    if os.environ.get('BANEI_NO_DB') == '1':
        return pd.DataFrame(columns=K + ['win_odds'])
    try:
        rs, off = [], 0
        while True:
            r = _rest(f'/rest/v1/nar_odds_ticks?select=race_date,race_no,w&track=eq.{urllib.parse.quote("帯広ば")}&f=is.true'
                      f'&race_date=gte.{since}&order=race_date,race_no&limit=1000&offset={off}')
            rs += r
            if len(r) < 1000:
                break
            off += 1000
    except Exception as e:  # noqa: BLE001
        log('確定単勝が読めない', repr(e)[:160]); return pd.DataFrame(columns=K + ['win_odds'])
    out = []
    for r in rs:
        w = r.get('w') or {}
        if isinstance(w, str):
            w = json.loads(w)
        for n, o in w.items():
            try:
                out.append((str(r['race_date'])[:10], int(r['race_no']), int(n), float(o)))
            except (TypeError, ValueError):
                pass
    return pd.DataFrame(out, columns=K + ['win_odds']).drop_duplicates(K, keep='last')


def market_aux(E, day):
    """seqb5_pre.market_aux と同じ: log(市場の勝つ率 × 頭数)/1.5(±3)。頭数分そろわないレースは空。前の日まで。"""
    k = norm(pd.read_parquet(f1.OUT + 'win_odds_frozen.parquet'))[K + ['win_odds']]
    kmax = str(k.race_date.max())[:10]
    k = pd.concat([k, final_odds((pd.Timestamp(kmax) + pd.Timedelta(days=1)).date().isoformat())], ignore_index=True)
    k = k[k.race_date < day].drop_duplicates(K)
    w = norm(E[K + ['rkey']].copy()).merge(k, on=K, how='left', validate='m:1')
    q = 1 / w.win_odds.where(w.win_odds >= 1.0)
    full = q.notna().groupby(w.rkey).transform('all')
    q = q / q.groupby(w.rkey).transform('sum')
    n = w.groupby('rkey').rkey.transform('size')
    a = (np.log(q * n) / 1.5).clip(-3, 3).where(full)
    log('確定単勝', '固めた表の最後', kmax, '答えのある行', int(np.isfinite(a).sum()), '・最後の日', w.race_date[np.isfinite(a.to_numpy())].max())
    return a.to_numpy(np.float32)


# ---------------------------------------------------------------- 並び読み X
def x5(S30, own):
    """seqb5_pre.setup30 の ②③(過去走の AI の見込み・外れ・見込みの有無・同じ馬主・両方分かる)。own = 行ごとの馬主(ならした名前・空は None)。"""
    hist = S30['hist']; n = S30['n']; FR = hist.shape[2] - 6
    flag = hist[:, :, -1]
    hk = S30['hk']; date = S30['date']
    off = S30['off']; pai = 1 / (1 + np.exp(-np.nan_to_num(off))); y3 = S30['y3']
    known = pd.notna(own)
    X = np.zeros((n, H, 5), np.float32)
    chk = 0.0
    dn = (pd.to_datetime(pd.Series(date)) - pd.Timestamp('2014-01-01')).dt.days.to_numpy(float)
    for k in range(1, H + 1):
        s = H - k
        j = np.arange(n) - k; jj = np.where(j >= 0, j, 0)
        ok = (j >= 0) & (hk[jj] == hk) & (date[jj] < date) & (flag[:, s] == 1)
        if k <= 3 and ok.any():
            g = np.log1p(np.maximum(dn - dn[jj], 0)) / 3 - 1.5
            chk = max(chk, float(np.abs(g[ok] - hist[ok, s, FR]).max()))
        ha = ok & np.isfinite(off[jj])
        X[ha, s, 0] = np.clip(off[jj][ha], -4, 4) / 2
        X[ha, s, 1] = y3[jj][ha] - pai[jj][ha]
        X[ha, s, 2] = 1
        bo = ok & known[jj] & known
        X[bo, s, 3] = (own[jj][bo] == own[bo])
        X[bo, s, 4] = 1
    assert chk < 1e-3, ('過去走の並びが合わない', chk)
    log('並び読み X の材料', '見込み付きの過去走', round(float(X[..., 2].sum() / max(flag.sum(), 1)), 3),
        '馬主の分かる過去走', round(float(X[..., 4].sum() / max(flag.sum(), 1)), 3))
    return np.ascontiguousarray(np.concatenate([S30['hist'], X], 2))


def model_x(fh, fc, na):
    import torch
    import torch.nn as nn

    class M(nn.Module):
        def __init__(s, d=64):
            super().__init__()
            s.inp = nn.Sequential(nn.Linear(fh, d), nn.GELU())
            s.gru = nn.GRU(d, d, batch_first=True)
            s.ctx = nn.Sequential(nn.Linear(fc + d, d), nn.GELU(), nn.Linear(d, d))
            s.att = nn.TransformerEncoderLayer(d, 4, 2 * d, dropout=0.1, batch_first=True)
            s.out = nn.Linear(2 * d, 1)
            s.aux = nn.Linear(2 * d, na)

        def forward(s, hist, ctx, mask):
            B, N, T, F = hist.shape
            x = s.inp(hist.reshape(B * N, T, F))
            o, h = s.gru(x)
            h = h[-1].reshape(B, N, -1)
            e = s.ctx(torch.cat([ctx, h], -1))
            a = s.att(e, src_key_padding_mask=~mask)
            ea = torch.cat([e, a], -1)
            s._a = s.aux(ea)
            return s.out(ea).squeeze(-1)
    return M()


def _xbatch(hist, aux, S, rs, res):
    import torch
    R, off, y3, ctx = S['R'], S['off'], S['y3'], S['ctx']
    idx = R[rs]; m = idx >= 0; ii = np.where(m, idx, 0); o = off[ii]
    if res:
        m = m & ~np.isnan(o)
    ax = aux[ii]; ma = m[..., None] & ~np.isnan(ax)
    return (torch.from_numpy(hist[ii]), torch.from_numpy(ctx[ii]), torch.from_numpy(m), torch.from_numpy(np.where(m, y3[ii], 0)),
            torch.from_numpy(np.nan_to_num(o)), torch.from_numpy(np.nan_to_num(ax)), torch.from_numpy(ma))


def x_fit(hist, aux, S, lo, lam=1.0):
    """seqb5_pre.seq_month の学ぶ所(lo より前の行・種ごとに 単独 → 外した分・補助の損 × lam)。返す = 種ごとの重み。"""
    import torch
    torch.set_num_threads(NT)
    F_ = torch.nn.functional
    rdate = S['rdate']

    def train(M, tr, va, res, lr, eps):
        opt = torch.optim.AdamW([p for p in M.parameters() if p.requires_grad], lr=lr, weight_decay=1e-4)
        rng = np.random.default_rng(len(tr))
        best, bstate, bad = 1e9, {k: v.clone() for k, v in M.state_dict().items()}, 0
        for ep in range(eps):
            M.train()
            q = rng.permutation(tr)
            for b in range(0, len(q), 128):
                h, c, m, y, o, ax, ma = _xbatch(hist, aux, S, q[b:b + 128], res)
                if not bool(m.any()):
                    continue
                z = M(h, c, m) + (o if res else 0)
                loss = F_.binary_cross_entropy_with_logits(z[m], y[m])
                if lam > 0 and bool(ma.any()):
                    loss = loss + lam * F_.smooth_l1_loss(M._a[ma], ax[ma])
                opt.zero_grad(); loss.backward(); opt.step()
            M.eval()
            with torch.no_grad():
                vl, vn = 0.0, 0
                for b in range(0, len(va), 512):
                    h, c, m, y, o, _, _ = _xbatch(hist, aux, S, va[b:b + 512], res)
                    z = M(h, c, m) + (o if res else 0)
                    vl += float(F_.binary_cross_entropy_with_logits(z[m], y[m], reduction='sum')); vn += int(m.sum())
            vl /= vn
            if vl < best - 1e-6:
                best, bstate, bad = vl, {k: v.clone() for k, v in M.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= 2:
                    break
        M.load_state_dict(bstate)
        return best, ep

    pre_tr = np.where((rdate >= sc.START) & (rdate < lo))[0]
    pre_tr = pre_tr[np.argsort(rdate[pre_tr], kind='stable')]
    cut = int(len(pre_tr) * 0.9)
    res_tr = np.where(S['has_off'] & (rdate >= sc.RES_START) & (rdate < lo))[0]
    p = np.random.default_rng(100).permutation(res_tr); cut2 = int(len(p) * 0.9)
    states = []
    for s in SEEDS_X:
        t0 = time.time()
        torch.manual_seed(s)
        M = model_x(hist.shape[2], S['ctx'].shape[1], aux.shape[1])
        b1, e1 = train(M, pre_tr[:cut], pre_tr[cut:], False, 1e-3, 15)
        torch.nn.init.zeros_(M.out.weight); torch.nn.init.zeros_(M.out.bias)
        b2, e2 = train(M, p[:cut2], p[cut2:], True, 3e-4, 15)
        log('並び読み X', lo, '種', s, '単独', round(b1, 5), e1, '外した分', round(b2, 5), e2, '秒', round(time.time() - t0))
        states.append({k: v.clone() for k, v in M.state_dict().items()})
    return states


def x_apply(states, hist, S, lo, hi, na=1):
    import torch
    torch.set_num_threads(NT)
    R, rdate = S['R'], S['rdate']
    aux = np.full((S['n'], na), np.nan, np.float32)
    te = np.where((rdate >= lo) & (rdate < hi))[0]
    outs = []
    for st in states:
        M = model_x(hist.shape[2], S['ctx'].shape[1], na)
        M.load_state_dict(st)
        out = np.full(S['n'], np.nan)
        M.eval()
        with torch.no_grad():
            for b in range(0, len(te), 512):
                rs = te[b:b + 512]
                h, c, m, _, _, _, _ = _xbatch(hist, aux, S, rs, True)
                z = M(h, c, m).numpy(); idx = R[rs]
                out[idx[m.numpy()]] = z[m.numpy()]
        outs.append(out)
    return np.mean(outs, axis=0)


def tree_mix(p_seeds, p_cb, p_nn, C):
    """T = w_seed × (種のロジットの平均) + w_cb × CatBoost のロジット + w_nn × (NN のロジットの平均)。"""
    s3 = np.mean([lg(np.asarray(p, float)) for p in p_seeds], 0)
    nn = np.mean([lg(np.asarray(p, float)) for p in p_nn], 0)
    return C['w_seed'] * s3 + C['w_cb'] * lg(np.asarray(p_cb, float)) + C['w_nn'] * nn
