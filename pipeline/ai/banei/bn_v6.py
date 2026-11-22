# -*- coding: utf-8 -*-
"""ばんえい(帯広)第 6 版の部品(ばんえい 決め 13・2026-11-23 合格・nankan-ai-v3 の out/banei_k13_prereg.md)。banei_v3.py が呼ぶ。

研究の写し(計算は同じ・「学ぶ」と「当てる」を分けた):
  ① レース全体を読む NN(種 0〜2)= v3 の src/banei/racenn_pre.py(表の材料を 1 頭ずつ読み、同じレースの顔ぶれを注意機構 2 層で読む)
  足し段 A(種 801〜806)       = src/banei/stack_pre.py の GA(並び読み X を止め、過去走ごとの「その時の相手・その日の傾き」9 列 × 30 走
                                 + 今もある 6 列を小さな GRU で読んで X のロジットに足す)
  学び直した並び読み(種 801〜806)= src/banei/seqtab_pre.py の XC(並び読み X の形に、表の材料を 1 頭ずつ 128 に縮めて今の材料の横に足す)
  z = T と平らな模型の混ぜ + w_top × (足し段 A の 6 本平均 + 学び直した並び読みの 6 本平均) + b × 能検
  T = 土台の木 種 0・1・2 のロジットの平均・CatBoost・① 種 0〜2 のロジットの平均 の重み付きの和(重みは固めた表の数)
第 5 版から外れる物 = 1 頭ずつの NN(① に替える)。並び読み X は足し段 A の中にだけ残る(種 801〜806)。
学び方・種・止めどころは研究と同じ。並び読みの学びは bn_v5.x_fit をそのまま使う(模型の形と種だけ差し替える)。
数(重み・① の回数・能検の b・勝つ率の b1)は公開のコードに書かない = 固めた表のリリースの banei_kb/banei_v6.json。無ければ第 5 版の作りのまま。
"""
import json
import os
import time
from contextlib import contextmanager

import numpy as np
import pandas as pd

import bn_v5 as v5m
import feat_v1 as f1
import feat_v2 as f2
import seq_core as sc

K = v5m.K
H = v5m.H
SEEDS_TOP = (801, 802, 803, 804, 805, 806)
RA_SEEDS = (0, 1, 2)
FC0 = 19      # 今の材料の列の数(この後ろが表の材料)
DT = 128
GI_GA = 2     # 研究 stack_pre.KINDS の中の GA の番号(種 = s × 10 + 2・並べ替えの種 = 学びの行の数 + 2)
NT = sc.NT
lg = sc.lg
log = v5m.log


def consts_path():
    return os.environ.get('BANEI_V6', f1.OUT + 'banei_v6.json')


def on():
    """第 6 版の数(固めた表のリリース)があるか。第 5 版の部品(馬主・確定単勝)も要る。"""
    return v5m.on() and os.path.exists(consts_path())


def consts():
    return json.load(open(consts_path(), encoding='utf-8'))


# ---------------------------------------------------------------- ① レース全体を読む NN
def ra_net(p):
    import torch
    import torch.nn as nn

    class NetA(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = nn.Sequential(nn.Linear(p, 512), nn.SiLU(), nn.Dropout(0.25), nn.Linear(512, 256), nn.SiLU(), nn.Dropout(0.25))
            layer = nn.TransformerEncoderLayer(256, 4, 512, dropout=0.1, activation='gelu', batch_first=True, norm_first=True)
            self.att = nn.TransformerEncoder(layer, 2, enable_nested_tensor=False)
            self.out = nn.Sequential(nn.Linear(512, 128), nn.SiLU(), nn.Dropout(0.1))
            self.head = nn.Linear(128, 1)

        def forward(self, x, pad):
            h = self.enc(x)
            c = self.att(h, src_key_padding_mask=pad)
            return self.head(self.out(torch.cat([h, c], -1)))[..., 0]
    return NetA()


def race_index(d):
    r = (d.race_date.astype(str) + '_' + d.race_no.astype(str)).to_numpy()
    st = np.r_[0, np.where(r[1:] != r[:-1])[0] + 1]
    assert len(st) == len(pd.unique(r)), 'レースが続いて並んでいない'
    return st, np.diff(np.r_[st, len(r)])


def pad_batch(st, ln):
    L = int(ln.max()); ar = np.arange(L)[None, :]
    pad = ar >= ln[:, None]
    return np.where(pad, 0, st[:, None] + ar), pad


def ra_predict(m, Xn, RI):
    import torch
    m.eval(); st, ln = RI; out = np.zeros(len(Xn))
    with torch.no_grad():
        for a in range(0, len(st), 1024):
            ix, pad = pad_batch(st[a:a + 1024], ln[a:a + 1024])
            o = torch.sigmoid(m(torch.from_numpy(Xn[ix]), torch.from_numpy(pad))).numpy()
            out[ix[~pad]] = o[~pad]
    return np.clip(out, 1e-6, 1 - 1e-6)


def ra_fit(tr, cols, epochs, seeds=RA_SEEDS):
    """racenn_pre.train と同じ(学びの行 = 土台の木と同じ・K の順)。返す = 種ごとの重みと分位の物差し。"""
    import torch
    Xt = v5m.numeric(tr, cols); Q, flag = v5m.nn_prep(Xt)
    Xn = v5m.nn_transform(Xt, Q, flag); del Xt
    Y = tr.y_top3.astype(int).values.astype('float32'); st, ln = race_index(tr)
    out = []
    for seed in seeds:
        t0 = time.time()
        torch.manual_seed(seed); torch.set_num_threads(NT)
        m = ra_net(Xn.shape[1])
        opt = torch.optim.AdamW(m.parameters(), lr=1e-3, weight_decay=1e-5)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
        bce = torch.nn.BCEWithLogitsLoss(reduction='none')
        rng = np.random.default_rng(seed); n, bs, step = len(st), 256, 0
        for _ in range(epochs):
            m.train(); perm = rng.permutation(n)
            for a in range(0, n, bs):
                ix, pad = pad_batch(st[perm[a:a + bs]], ln[perm[a:a + bs]])
                o = m(torch.from_numpy(Xn[ix]), torch.from_numpy(pad))
                ww = torch.from_numpy((~pad).astype('float32'))
                loss = (bce(o, torch.from_numpy(Y[ix])) * ww).sum() / ww.sum()
                if step < 100:
                    for g in opt.param_groups:
                        g['lr'] = 1e-3 * (step + 1) / 100
                opt.zero_grad(); loss.backward()
                torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0); opt.step(); step += 1
            sch.step()
        out.append(dict(state={k: v.clone() for k, v in m.state_dict().items()}, Q=Q, flag=flag, p=int(Xn.shape[1])))
        log('レース全体を読む NN', seed, '学び', len(tr), '回', epochs, '秒', round(time.time() - t0))
    return out


def ra_apply(st, d, cols):
    """d = 当日の行(どの順でもよい)。返す = d の行の順の 3 着内の率。"""
    import torch
    torch.set_num_threads(NT)
    o = np.lexsort((d.runner_number.to_numpy(), d.race_no.to_numpy(), d.race_date.to_numpy()))
    ds = d.iloc[o]
    m = ra_net(st['p']); m.load_state_dict(st['state'])
    p = ra_predict(m, v5m.nn_transform(v5m.numeric(ds, cols), st['Q'], st['flag']), race_index(ds))
    out = np.empty(len(d)); out[o] = p
    return out


# ---------------------------------------------------------------- 並び読み(X・学び直し)の学びと当て = bn_v5 の手順のまま
@contextmanager
def _as(make, seeds=None):
    """bn_v5.x_fit・x_apply を、模型の形と種だけ差し替えて使う(手順は 1 か所 = 第 5 版と同じ計算)。"""
    m0, s0 = v5m.model_x, v5m.SEEDS_X
    v5m.model_x = make
    if seeds is not None:
        v5m.SEEDS_X = tuple(seeds)
    try:
        yield
    finally:
        v5m.model_x, v5m.SEEDS_X = m0, s0


def model_tab(fh, fc, na):
    """seqtab_pre.model_tab: 並び読み X の形 + 表の材料を 1 頭ずつ DT に縮めて今の材料の横に足す。"""
    import torch
    import torch.nn as nn

    class M(nn.Module):
        def __init__(s, d=64):
            super().__init__()
            s.inp = nn.Sequential(nn.Linear(fh, d), nn.GELU())
            s.gru = nn.GRU(d, d, batch_first=True)
            s.tab = nn.Sequential(nn.Dropout(0.1), nn.Linear(fc - FC0, DT), nn.GELU(), nn.Dropout(0.25))
            s.ctx = nn.Sequential(nn.Linear(FC0 + DT + d, d), nn.GELU(), nn.Linear(d, d))
            s.att = nn.TransformerEncoderLayer(d, 4, 2 * d, dropout=0.1, batch_first=True)
            s.out = nn.Linear(2 * d, 1)
            s.aux = nn.Linear(2 * d, na)

        def forward(s, hist, ctx, mask):
            B, N, T, F = hist.shape
            x = s.inp(hist.reshape(B * N, T, F))
            o, h = s.gru(x)
            h = h[-1].reshape(B, N, -1)
            e = s.ctx(torch.cat([ctx[..., :FC0], s.tab(ctx[..., FC0:]), h], -1))
            a = s.att(e, src_key_padding_mask=~mask)
            ea = torch.cat([e, a], -1)
            s._a = s.aux(ea)
            return s.out(ea).squeeze(-1)
    return M()


def seq_fit(make, hist, aux, S, lo, lam, seeds=SEEDS_TOP):
    with _as(make, seeds):
        return v5m.x_fit(hist, aux, S, lo, lam)


def seq_logit(make, state, hist, S, rows, na=1):
    """止めた並び読みのロジット(外した分)を、レースの番号 rows の馬に。x_apply と同じ計算(見込みの無い馬は空)。"""
    import torch
    torch.set_num_threads(NT)
    R = S['R']
    aux = np.full((S['n'], na), np.nan, np.float32)
    M = make(hist.shape[2], S['ctx'].shape[1], na)
    M.load_state_dict(state); M.eval()
    out = np.full(S['n'], np.nan, np.float32)
    with torch.no_grad():
        for b in range(0, len(rows), 512):
            rs = rows[b:b + 512]
            h, c, m, _, _, _, _ = v5m._xbatch(hist, aux, S, rs, True)
            z = M(h, c, m).numpy(); idx = R[rs]; mm = m.numpy()
            out[idx[mm]] = z[mm]
    return out


def res_rows(S, lo):
    """外した分の学びの行(レースの番号)を、研究と同じ並べ替え・同じ 9:1 で分ける。"""
    res_tr = np.where(S['has_off'] & (S['rdate'] >= sc.RES_START) & (S['rdate'] < lo))[0]
    p = np.random.default_rng(100).permutation(res_tr); cut2 = int(len(p) * 0.9)
    return res_tr, p[:cut2], p[cut2:]


# ---------------------------------------------------------------- 学び直した並び読みの表の材料
def tab_rows(E, D2, cols, day):
    """並び読みの行 E に表の材料(土台の木と同じ列)を結ぶ。返す = 生の値(結べない行は空)と結べた印。
    研究 seqtab_pre.table_rows の表 = 出走取消でなく結果のある行。本番は当日の行(結果はまだ無い)も結ぶ。"""
    L = json.load(open(os.environ.get('BANEI_LOCK', f1.OUT + 'banei_v2_lock.json'), encoding='utf-8'))
    d = D2[(D2.scratch == 0) & (D2.race_date >= L['start']) & (D2.y_top3.notna() | (D2.race_date >= day))].drop_duplicates(K).reset_index(drop=True)
    X = v5m.numeric(d, cols)
    key = d[K].copy(); key['_j'] = np.arange(len(d)); del d
    j = v5m.norm(E[K].copy()).reset_index(drop=True).merge(key, on=K, how='left', validate='m:1')['_j'].to_numpy()
    ok = ~np.isnan(j)
    out = np.full((len(j), len(cols)), np.nan, np.float32)
    out[ok] = X[j[ok].astype(int)]
    return out, ok


def tab_ctx(ctx0, Xraw, ok, Q, flag, only=None):
    """今の材料 19 列の横に、分位で −2〜2 にした表の材料を足す。only = その行だけ計算する(当てる時・他の行は 0)。"""
    assert ctx0.shape[1] == FC0, ctx0.shape
    w = Xraw.shape[1] + len(flag)
    T = np.zeros((len(Xraw), w), np.float32)
    use = ok if only is None else (ok & only)
    if use.any():
        T[use] = v5m.nn_transform(Xraw[use], Q, flag)
    return np.ascontiguousarray(np.concatenate([ctx0, T], 1).astype(np.float32))


# ---------------------------------------------------------------- 足し段 A の材料
def race_of_row(S):
    R = S['R']; rid = np.full(S['n'], -1, np.int64)
    rr, ss = np.where(R >= 0); rid[R[rr, ss]] = rr
    return rid


def _zs(d, g, c):
    m = d.groupby(g)[c].transform('mean'); s = d.groupby(g)[c].transform('std')
    return (d[c] - m) / (s.fillna(0) + 1e-3)


def race_feats(S, E, D1, day):
    """stack_pre.race_feats: 1 行 = 1 走。そのレースの中での AI の見込みと結果の 9 列。当日より前の結果だけを使う(当日の行は全部 0)。"""
    off = S['off']
    f = v5m.norm(D1[K + ['finish', 'dnf']].copy()).drop_duplicates(K)
    kb = pd.read_parquet(f2.KB, columns=['race_date', 'race_no', 'umaban', 'time_sec', 'pass1', 'seg_obst']).rename(columns={'umaban': 'runner_number'})
    kb['race_date'] = pd.to_datetime(kb.race_date).dt.strftime('%Y-%m-%d')
    kb['runner_number'] = pd.to_numeric(kb.runner_number, errors='coerce'); kb = kb.dropna(subset=['runner_number'])
    kb = v5m.norm(kb)
    kb = kb[kb.race_date < day].drop_duplicates(K)
    for c in ('time_sec', 'pass1', 'seg_obst'):
        kb[c] = pd.to_numeric(kb[c], errors='coerce')
    d = v5m.norm(E[K].copy()).reset_index(drop=True)
    d = d.merge(f, on=K, how='left').merge(kb, on=K, how='left')
    assert len(d) == S['n']
    today = (d.race_date >= day).to_numpy()
    d.loc[today, ['finish', 'dnf', 'time_sec', 'pass1', 'seg_obst']] = np.nan
    d['rid'] = race_of_row(S); d['off'] = off
    g = d.groupby('rid')
    N = g.rid.transform('size').astype(float); den = (N - 1).clip(lower=1)
    d['pr'] = g.off.rank(ascending=False, method='average')
    fin = d.finish.astype(float); fin[d.dnf == 1] = N[d.dnf == 1]
    d['fin'] = fin
    d['f1'] = (d.pr - 1) / den
    d['f2'] = (d.fin - 1) / den
    d['f3'] = d.f1 - d.f2
    d['tb'] = d.time_sec - g.time_sec.transform('min'); d['tz'] = _zs(d, 'rid', 'tb')
    mr = g.f1.transform('mean'); mt = d.groupby('rid').tz.transform('mean')
    d['_c'] = (d.f1 - mr) * (d.tz - mt); d['_v'] = (d.f1 - mr) ** 2
    sl = d.groupby('rid')._c.transform('sum') / (d.groupby('rid')._v.transform('sum') + 1e-6)
    d['tm'] = -(d.tz - mt - sl * (d.f1 - mr)).clip(-3, 3) / 2
    mf = d.groupby('rid').f2.transform('mean')
    d['_a'] = (d.f1 - mr) * (d.f2 - mf); d['_b'] = (d.f2 - mf) ** 2
    d['f4'] = (d.groupby('rid')._a.transform('sum') /
               np.sqrt(d.groupby('rid')._v.transform('sum') * d.groupby('rid')._b.transform('sum') + 1e-9))
    d['oz'] = _zs(d, 'rid', 'seg_obst')
    d['stp'] = ((d.dnf == 1) | (d.oz > 2)).astype(float)
    d['_s3'] = d.stp * (d.pr <= 3); d['_s4'] = d.stp * (d.pr <= 4)
    s3 = d.groupby('rid')._s3.transform('sum'); s4 = d.groupby('rid')._s4.transform('sum')
    d['f5'] = np.where(d.pr <= 3, s4 - d.stp, s3) / 3
    d['f6'] = (d.groupby('rid').stp.transform('sum') - d.stp) / den
    d['t3'] = np.floor(3 * (d.pass1 - 1) / N).clip(0, 2)
    ok3 = d.f3.notna() & d.t3.notna()
    d['_x'] = d.f3.where(ok3, 0); d['_n'] = ok3.astype(float)
    sd_ = d.groupby(['race_date', 't3'])._x.transform('sum'); nd_ = d.groupby(['race_date', 't3'])._n.transform('sum')
    sr_ = d.groupby(['rid', 't3'])._x.transform('sum'); nr_ = d.groupby(['rid', 't3'])._n.transform('sum')
    d['f7'] = ((sd_ - sr_) / (nd_ - nr_).where(nd_ - nr_ > 0)).fillna(0)
    has = np.isfinite(off) & d.fin.notna().to_numpy()
    cols = ['f1', 'f2', 'f3', 'tm', 'f4', 'f5', 'f6', 'f7']
    F = np.nan_to_num(d[cols].to_numpy(np.float32))
    F = np.concatenate([F, has[:, None].astype(np.float32)], 1); F[~has] = 0
    log('足し段 A の元', '有りの行', round(float(has.mean()), 3), '時計のある行', round(float(d.time_sec.notna().mean()), 3),
        '通過順のある行', round(float(d.pass1.notna().mean()), 3), '止まりの率', round(float(d.stp.mean()), 4))
    return F


def ga_inputs(hist, S, E, D1, day):
    """足し段 A の入力 = 過去 30 走ごとの 9 列 + 今もある 6 列(過去走の AI の見込み・外れ・見込みあり・同じ馬主・両方分かる + 何日前)。
    hist = bn_v5.x5 の返し(過去 30 走の 29 列 + 5 列)。"""
    F = race_feats(S, E, D1, day)
    n = S['n']; raw = S['hist']; flag = raw[:, :, -1]; hk = S['hk']; date = S['date']
    A = np.zeros((n, H, F.shape[1]), np.float32)
    for k in range(1, H + 1):
        s = H - k
        j = np.arange(n) - k; jj = np.where(j >= 0, j, 0)
        ok = (j >= 0) & (hk[jj] == hk) & (date[jj] < date) & (flag[:, s] == 1)
        A[ok, s] = F[jj[ok]]
    FR = raw.shape[2] - 6
    return np.ascontiguousarray(np.concatenate([A, hist[:, :, raw.shape[2]:], raw[:, :, FR:FR + 1]], 2).astype(np.float32))


def model_g(fq):
    """stack_pre.model_g の GA(並び読みの中の値は渡さない = 0 を渡す・研究の既定)。"""
    import torch
    import torch.nn as nn

    class G(nn.Module):
        def __init__(s):
            super().__init__()
            s.gru = nn.GRU(fq, 32, batch_first=True)
            s.e = nn.Sequential(nn.Linear(128 + 32, 32), nn.GELU())
            s.att = nn.TransformerEncoderLayer(32, 2, 64, dropout=0.1, batch_first=True)
            s.out = nn.Linear(64, 1)
            nn.init.zeros_(s.out.weight); nn.init.zeros_(s.out.bias)

        def forward(s, q, mask):
            B, N, T, Fq = q.shape
            _, h = s.gru(q.reshape(B * N, T, Fq))
            e = s.e(torch.cat([torch.zeros(B, N, 128), h[-1].reshape(B, N, -1)], -1))
            a = s.att(e, src_key_padding_mask=~mask)
            return s.out(torch.cat([e, a], -1)).squeeze(-1)
    return G()


def _gbatch(S, QA, zX, rs):
    import torch
    R, off, y3 = S['R'], S['off'], S['y3']
    idx = R[rs]; m = (idx >= 0); ii = np.where(m, idx, 0); m = m & ~np.isnan(off[ii]) & np.isfinite(zX[ii])
    base = zX[ii] + np.nan_to_num(off[ii])
    return (torch.from_numpy(QA[ii]), torch.from_numpy(m), torch.from_numpy(np.where(m, y3[ii], 0).astype(np.float32)),
            torch.from_numpy(np.nan_to_num(base).astype(np.float32)))


def g_fit(S, QA, zX, tr, va, seed):
    """stack_pre.run_month の足し段の学び(z = X + G + 第 2 版の見込み・G の出口は 0 から・止めどころは学びの行の終わりの 1 割)。"""
    import torch
    torch.set_num_threads(NT)
    F_ = torch.nn.functional

    def gloss(G):
        G.eval(); vl, vn = 0.0, 0
        with torch.no_grad():
            for b in range(0, len(va), 512):
                q, m, y, o = _gbatch(S, QA, zX, va[b:b + 512])
                z = G(q, m) + o
                vl += float(F_.binary_cross_entropy_with_logits(z[m], y[m], reduction='sum')); vn += int(m.sum())
        return vl / vn
    t0 = time.time()
    torch.manual_seed(seed * 10 + GI_GA)
    G = model_g(QA.shape[2])
    opt = torch.optim.AdamW(G.parameters(), lr=1e-3, weight_decay=1e-4)
    v0 = gloss(G)
    best, bstate, bad, ep = v0, {k: v.clone() for k, v in G.state_dict().items()}, 0, -1
    rng = np.random.default_rng(len(tr) + GI_GA)
    for ep in range(15):
        G.train()
        qq = rng.permutation(tr)
        for b in range(0, len(qq), 128):
            q, m, y, o = _gbatch(S, QA, zX, qq[b:b + 128])
            if not bool(m.any()):
                continue
            z = G(q, m) + o
            loss = F_.binary_cross_entropy_with_logits(z[m], y[m])
            opt.zero_grad(); loss.backward(); opt.step()
        vl = gloss(G)
        if vl < best - 1e-6:
            best, bstate, bad = vl, {k: v.clone() for k, v in G.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 3:
                break
    log('足し段 A', '種', seed, '止めどころの損 X だけ', round(v0, 5), '足し段', round(best, 5), '差', round(v0 - best, 5), '回', ep, '秒', round(time.time() - t0))
    return bstate


def g_apply(state, S, QA, zX, rows):
    """返す = X のロジット + 足し段(rows のレースの馬・他は空)。"""
    import torch
    torch.set_num_threads(NT)
    G = model_g(QA.shape[2]); G.load_state_dict(state); G.eval()
    R = S['R']; out = np.full(S['n'], np.nan, np.float32)
    with torch.no_grad():
        for b in range(0, len(rows), 512):
            rs = rows[b:b + 512]
            q, m, _, _ = _gbatch(S, QA, zX, rs)
            z = G(q, m).numpy(); idx = R[rs]; mm = m.numpy()
            out[idx[mm]] = zX[idx[mm]] + z[mm]
    return out


# ---------------------------------------------------------------- 学ぶ・当てる(banei_v3 から)
def fit_top(hist, aux, S, E, D1, D2, cols, day, lam):
    """上の段を学ぶ: 並び読み X(6 種)→ 止めて足し段 A(6 種)/ 学び直した並び読み(6 種)。返す = 保存する物の辞書。"""
    xs = seq_fit(v5m.model_x, hist, aux, S, day, lam)
    res_tr, tr, va = res_rows(S, day)
    QA = ga_inputs(hist, S, E, D1, day)
    gs = []
    for s, st in zip(SEEDS_TOP, xs):
        zX = seq_logit(v5m.model_x, st, hist, S, res_tr)
        gs.append(g_fit(S, QA, zX, tr, va, s))
    del QA
    Xraw, ok = tab_rows(E, D2, cols, day)
    trm = ok & (S['date'] < day)
    Q, flag = v5m.nn_prep(Xraw[trm])
    S2 = dict(S, ctx=tab_ctx(S['ctx'], Xraw, ok, Q, flag)); del Xraw
    log('学び直した並び読み', '入力', S2['ctx'].shape, '物差しの行', int(trm.sum()), '結べた行', round(float(ok.mean()), 4))
    cs = seq_fit(model_tab, hist, aux, S2, day, lam)
    return dict(x=xs, g=gs, xc=cs, Q=Q, flag=flag, seeds=list(SEEDS_TOP))


def save_top(top, path):
    import torch
    torch.save(top, path)


def load_top(path):
    import torch
    return torch.load(path, weights_only=False)


def apply_top(top, hist, S, E, D1, D2, cols, day, nxt):
    """当日の行の 足し段 A の 6 本平均・学び直した並び読みの 6 本平均(S の行の順・当日でない行は空)。"""
    te = np.where((S['rdate'] >= day) & (S['rdate'] < nxt))[0]
    QA = ga_inputs(hist, S, E, D1, day)
    ga = np.mean([g_apply(g, S, QA, seq_logit(v5m.model_x, x, hist, S, te), te) for x, g in zip(top['x'], top['g'])], 0)
    del QA
    Xraw, ok = tab_rows(E, D2, cols, day)
    cur = (S['date'] >= day) & (S['date'] < nxt)
    S2 = dict(S, ctx=tab_ctx(S['ctx'], Xraw, ok, top['Q'], top['flag'], only=cur))
    xc = np.mean([seq_logit(model_tab, c, hist, S2, te) for c in top['xc']], 0)
    return ga, xc, int((cur & ~ok).sum())


def tree_mix(p_seeds, p_cb, p_ra, C):
    """T = w_seed × (種のロジットの平均) + w_cb × CatBoost のロジット + w_ra × (① のロジットの平均)。"""
    s3 = np.mean([lg(np.asarray(p, float)) for p in p_seeds], 0)
    ra = np.mean([lg(np.asarray(p, float)) for p in p_ra], 0)
    return C['w_seed'] * s3 + C['w_cb'] * lg(np.asarray(p_cb, float)) + C['w_ra'] * ra
