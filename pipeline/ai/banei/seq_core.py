# -*- coding: utf-8 -*-
"""ばんえい 第 3 版の並び読み(外した分)と平らな模型(2026-10-28 nar-jobs に写した)。

v3 の src/banei/seq_check.py の seq_month・flat_month と src/f5_scripts/seq_day.py の model の写し。計算は同じで、
「学ぶ」と「当てる」を分けた(朝に学んで模型を保存 → 直前の周で当日の体重を入れた材料に当てる)。
学ぶ行は lo より前の日だけ = 当日の体重・水分は学びに入らない。分けても同じ値になることは banei_v3.py selftest で確かめる。
"""
import os

import numpy as np

MAXN = 10
START = '2014-04-01'      # 単独の学び・平らな模型の学びの始まり
RES_START = '2017-04-01'  # 外した分の学びの始まり(第 2 版の見込みのある所)
SEEDS = (801, 802, 803)
W_FLAT = 0.2
NT = int(os.environ.get('BANEI_THREADS', '8'))
lg = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))  # noqa: E731


def model(fh, fc):
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

        def forward(s, hist, ctx, mask):
            B, N, T, F = hist.shape
            x = s.inp(hist.reshape(B * N, T, F))
            o, h = s.gru(x)
            h = h[-1].reshape(B, N, -1)
            e = s.ctx(torch.cat([ctx, h], -1))
            a = s.att(e, src_key_padding_mask=~mask)
            return s.out(torch.cat([e, a], -1)).squeeze(-1)
    return M()


def _batch(hist, ctx, S, rs, res):
    import torch
    R, off, y3 = S['R'], S['off'], S['y3']
    idx = R[rs]; m = idx >= 0; ii = np.where(m, idx, 0); o = off[ii]
    if res:
        m = m & ~np.isnan(o)
    return (torch.from_numpy(hist[ii]), torch.from_numpy(ctx[ii]), torch.from_numpy(m), torch.from_numpy(np.where(m, y3[ii], 0)),
            torch.from_numpy(np.nan_to_num(o)))


def seq_fit(hist, ctx, S, lo, log=print):
    """lo より前の行で、種ごとに 単独 → 外した分 を学ぶ。返す = 種ごとの重み(state_dict)。"""
    import torch
    torch.set_num_threads(NT)
    rdate = S['rdate']

    def batch(rs, res):
        return _batch(hist, ctx, S, rs, res)

    def train(M, tr, va, res, lr, eps):
        opt = torch.optim.AdamW([p for p in M.parameters() if p.requires_grad], lr=lr, weight_decay=1e-4)
        rng = np.random.default_rng(len(tr))
        best, bstate, bad = 1e9, {k: v.clone() for k, v in M.state_dict().items()}, 0
        for ep in range(eps):
            M.train()
            q = rng.permutation(tr)
            for b in range(0, len(q), 128):
                h, c, m, y, o = batch(q[b:b + 128], res)
                if not bool(m.any()):
                    continue
                z = M(h, c, m) + (o if res else 0)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(z[m], y[m])
                opt.zero_grad(); loss.backward(); opt.step()
            M.eval()
            with torch.no_grad():
                vl, vn = 0.0, 0
                for b in range(0, len(va), 512):
                    h, c, m, y, o = batch(va[b:b + 512], res)
                    z = M(h, c, m) + (o if res else 0)
                    vl += float(torch.nn.functional.binary_cross_entropy_with_logits(z[m], y[m], reduction='sum')); vn += int(m.sum())
            vl /= vn
            if vl < best - 1e-6:
                best, bstate, bad = vl, {k: v.clone() for k, v in M.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= 2:
                    break
        M.load_state_dict(bstate)
        return best, ep

    pre_tr = np.where((rdate >= START) & (rdate < lo))[0]
    pre_tr = pre_tr[np.argsort(rdate[pre_tr], kind='stable')]
    cut = int(len(pre_tr) * 0.9)
    res_tr = np.where(S['has_off'] & (rdate >= RES_START) & (rdate < lo))[0]
    p = np.random.default_rng(100).permutation(res_tr); cut2 = int(len(p) * 0.9)
    states = []
    for s in SEEDS:
        torch.manual_seed(s)
        M = model(hist.shape[2], ctx.shape[1])
        b1, e1 = train(M, pre_tr[:cut], pre_tr[cut:], False, 1e-3, 15)
        torch.nn.init.zeros_(M.out.weight); torch.nn.init.zeros_(M.out.bias)
        b2, e2 = train(M, p[:cut2], p[cut2:], True, 3e-4, 15)
        log('並び読み', lo, '種', s, '単独', round(b1, 5), e1, '外した分', round(b2, 5), e2)
        states.append({k: v.clone() for k, v in M.state_dict().items()})
    return states


def seq_apply(states, hist, ctx, S, lo, hi):
    """[lo, hi) の行に当てる = 外した分のロジット(種の平均)。外した分の初期値が空の行は空。"""
    import torch
    torch.set_num_threads(NT)
    R, rdate = S['R'], S['rdate']
    te = np.where((rdate >= lo) & (rdate < hi))[0]
    outs = []
    for st in states:
        M = model(hist.shape[2], ctx.shape[1])
        M.load_state_dict(st)
        out = np.full(S['n'], np.nan)
        M.eval()
        with torch.no_grad():
            for b in range(0, len(te), 512):
                rs = te[b:b + 512]
                h, c, m, _, _ = _batch(hist, ctx, S, rs, True)
                z = M(h, c, m).numpy(); idx = R[rs]
                out[idx[m.numpy()]] = z[m.numpy()]
        outs.append(out)
    return np.mean(outs, axis=0)


def save_states(states, path):
    import torch
    torch.save(states, path)


def load_states(path):
    import torch
    return torch.load(path, weights_only=True)


def _flat_X(hist, ctx):
    return np.concatenate([hist[:, -5:, :].reshape(len(hist), -1), ctx], 1)


def flat_fit(hist, ctx, S, lo, seed=0):
    """平らな模型(過去 5 走を横に並べた木)を lo より前の行(2014-04〜)で学ぶ。"""
    import lightgbm as lgb
    X = _flat_X(hist, ctx)
    d = S['date']
    tr = (d >= START) & (d < lo)
    return lgb.train(dict(objective='binary', learning_rate=0.03, num_leaves=31, min_data_in_leaf=300, feature_fraction=0.5, verbose=-1,
                          seed=seed, num_threads=NT), lgb.Dataset(X[tr], S['y3'][tr]), num_boost_round=800)


def flat_apply(m, hist, ctx, S, lo, hi):
    X = _flat_X(hist, ctx)
    d = S['date']
    cur = (d >= lo) & (d < hi)
    out = np.full(S['n'], np.nan); out[cur] = lg(m.predict(X[cur]))
    return out


def booster_from(text):
    import lightgbm as lgb
    return lgb.Booster(model_str=text)

