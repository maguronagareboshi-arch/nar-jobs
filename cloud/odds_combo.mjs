// 最終予測の並走用(2026-10-20)= 馬連・ワイド・3連複の売れ方 6 特徴を足した 24 特徴の模型(cloud/odds_combo_model.json)。
// ⛔組の 6 特徴の作り方は研究の台本 research/odds_combo/rows.mjs(枝 wip/odds-final-combo-20261020)と**同じ**。
//   試験 tests/odds_combo_test.mjs が本物の 10/19 の刻みで rows.csv の値と照合する。
// ⛔18 特徴・木の引き方・幅・答え合わせは本番の odds-final.mjs(lib)を呼ぶだけ(ここで書き直さない)。
// ⛔画面には出さない(公開しない)。夜の便 odds_record.mjs が nar_meta odds_final_record の shadow に記録するだけ。
export const KINDS = ['umaren', 'wide', 'sanrenpuku'];
export const CGAP = 10;   // 組の刻みは lim 以前で最新・lim−10 分より古ければ欠け

const num = (x) => { const n = Number(x); return x === null || x === undefined || x === '' || !Number.isFinite(n) ? null : n; };
const pos = (x) => { const o = num(x); return o !== null && o > 0 ? o : null; };
const oddsOf = (x) => {
  if (Array.isArray(x)) return oddsOf(x[0]);
  if (typeof x === 'string') { const m = /[\d.]+/.exec(x); return m ? pos(m[0]) : null; }
  return pos(x);
};
const ymd = (d) => d.toISOString().slice(0, 10);
// observed_at(UTC)→ JST の分(0 時から)と JST の日付
export const jstMin = (s) => { const t = Date.parse(s); if (!Number.isFinite(t)) return null; const d = new Date(t + 9 * 3600e3); return { d: ymd(d), m: d.getUTCHours() * 60 + d.getUTCMinutes() }; };

// 組 → 馬ごとの 1/オッズ の和(組の中の馬に同じだけ割り振る)
export function horseSum(combos) {
  const s = new Map();
  for (const c of Array.isArray(combos) ? combos : []) {
    if (!Array.isArray(c) || c.length < 4) continue;
    const nums = c.slice(0, c.length - 2).map(Number);
    const o = oddsOf(c[c.length - 2]);
    if (!o || nums.some((u) => !Number.isFinite(u))) continue;
    for (const u of nums) s.set(u, (s.get(u) || 0) + 1 / o);
  }
  return s;
}
// 単勝の取り分 ÷ 組の取り分 の log(cur の全馬がそろうときだけ)
export function devOf(cur, hs) {
  if (!hs || cur.size < 2 || [...cur.keys()].some((u) => !(hs.get(u) > 0))) return null;
  let sw = 0; let se = 0;
  for (const [u, v] of cur) { sw += 1 / v; se += hs.get(u); }
  return new Map([...cur].map(([u, v]) => [u, Math.log((1 / v / sw) / (hs.get(u) / se))]));
}

// 組の刻みの見出し(id,track,race_no,kind,observed_at,f)→ 候補 Map(track|no|kind → [{id, m}])。
// 確定・別の日・発走後(pmOf(k) より後)は外す
export function comboCands(heads, d, pmOf) {
  const fb = new Map();
  for (const r of heads) {
    if (r.f === true) continue;
    const k = r.track + '|' + r.race_no;
    const j = jstMin(r.observed_at);
    const pm = pmOf(k);
    if (!j || j.d !== d) continue;
    if (pm === null || pm === undefined || j.m > pm) continue;
    const kk = k + '|' + r.kind;
    if (!fb.has(kk)) fb.set(kk, []);
    fb.get(kk).push({ id: r.id, m: j.m });
  }
  return fb;
}
export function pickC(fb, k, kind, lim) {
  let best = null;
  for (const o of fb.get(k + '|' + kind) || []) if (o.m <= lim && o.m >= lim - CGAP && (!best || o.m > best.m || (o.m === best.m && o.id > best.id))) best = o;
  return best;
}
// 発走 pm・T 分前の 3 券種の [今, 10 分前] の刻み
export function comboSel(fb, k, pm, T) {
  const sel = {};
  for (const kind of KINDS) sel[kind] = [pickC(fb, k, kind, pm - T), pickC(fb, k, kind, pm - T - 10)];
  return sel;
}
// cur= 馬番 → 今の単勝(featuresAt の W)。→ 馬番 → [lu, lw, ls, cu, cw, cs](欠けは NaN)
export function comboFeats(cur, sel, sums) {
  const dv = {};
  for (const kind of KINDS) {
    const [a, b] = sel[kind];
    dv[kind] = [a ? devOf(cur, sums.get(a.id)) : null, b ? devOf(cur, sums.get(b.id)) : null];
  }
  const out = new Map();
  for (const u of cur.keys()) {
    const lv = KINDS.map((kd) => (dv[kd][0] ? dv[kd][0].get(u) : NaN));
    const cv = KINDS.map((kd) => (dv[kd][0] && dv[kd][1] ? dv[kd][0].get(u) - dv[kd][1].get(u) : NaN));
    out.set(u, [...lv, ...cv]);
  }
  return out;
}

// 1 日分の組の刻みを読む。races= [{k, pm}]・Ts= 使う T。⛔REST の単純 select だけ(id の続き取り・必要な組だけ 40 件ずつ)
// → { sel(k, T), sums }(sel が無い= そのレースは組なし)
export async function comboDay(get, d, races, Ts) {
  const heads = [];
  let last = null;
  for (;;) {
    const j = await get(`nar_odds_full_ticks?select=id,track,race_no,kind,observed_at,f&race_date=eq.${d}&kind=in.(${KINDS.join(',')})&order=id.asc&limit=1000` + (last === null ? '' : '&id=gt.' + last));
    heads.push(...j);
    if (j.length < 1000) break;
    last = j[j.length - 1].id;
  }
  const pmBy = new Map(races.map((r) => [r.k, r.pm]));
  const fb = comboCands(heads, d, (k) => (pmBy.has(k) ? pmBy.get(k) : null));
  const selBy = new Map();
  const need = new Set();
  for (const r of races) {
    if (r.pm === null || r.pm === undefined) continue;
    for (const T of Ts) {
      const s = comboSel(fb, r.k, r.pm, T);
      selBy.set(r.k + '|' + T, s);
      for (const kind of KINDS) for (const o of s[kind]) if (o) need.add(o.id);
    }
  }
  const sums = new Map();
  const ids = [...need].sort((a, b) => a - b);
  for (let i = 0; i < ids.length; i += 40) {
    const j = await get(`nar_odds_full_ticks?select=id,kind,combos&id=in.(${ids.slice(i, i + 40).join(',')})`);
    for (const r of j) sums.set(r.id, horseSum(r.combos));
  }
  return { heads: heads.length, need: ids.length, sel: (k, T) => selBy.get(k + '|' + T) || null, sums };
}

// 24 特徴の見込み(lib.forecast と同じ形の行)。cf= comboDay の結果・k= レース・T= 組の時点(答え合わせは lib.REC_T)
export function forecast24(lib, model, obs, hobs, idx, post, track, raceNo, cf, k, T) {
  const ti = model && Array.isArray(model.cats) ? model.cats.indexOf(track) : -1;
  if (ti < 0) return null;
  const kk = Number.isFinite(Number(model.k)) ? Number(model.k) : 1;
  const m = idx >= 0 && idx < obs.length ? obs[idx].m : null;
  const base = lib.featuresAt(obs, hobs, idx, post, ti, raceNo);
  if (!base.length) return [];
  const cur = new Map(base.map((r) => [r.u, r.cur]));
  const sel = cf ? cf.sel(k, T) : null;
  const cx = sel ? comboFeats(cur, sel, cf.sums) : null;
  return base.map((r) => {
    const x = [...r.x, ...(cx ? cx.get(r.u) : [NaN, NaN, NaN, NaN, NaN, NaN])];
    const [q10, q50, q90] = lib.predictQ(model, x);
    return {
      ...r, x, m, q: [q10, q50, q90],
      mid: r.cur * Math.exp(q50),
      low: r.cur * Math.exp(q50 - kk * (q50 - q10)),
      high: r.cur * Math.exp(q50 + kk * (q90 - q50)),
    };
  });
}

// lib.judgeRace と同じ流れ(st の付け方・REC_T・REC_MAX も同じ)で 24 特徴の模型を引く。券種補正(adj)は使わない
export function judgeRace24(lib, model, ticks, post, track, raceNo, cf, k) {
  if (!Number.isFinite(post)) return { st: 'no_post' };
  const obs = lib.obsOf(ticks);
  const hobs = lib.hobsOf(ticks);
  const T = lib.REC_T;
  const run = (i) => (i < 0 ? [] : forecast24(lib, model, obs, hobs, i, post, track, raceNo, cf, k, T));
  if (run(obs.length - 1) === null) return { st: 'no_track' };
  const fin = lib.finOf(ticks);
  if (!fin) return { st: 'no_final' };
  const idx = lib.pickAt(obs, post, T);
  const rows = run(idx);
  if (!rows.length) return { st: 'no_10min' };
  const res = lib.checkHits(rows, fin);
  const mins = post - obs[idx].m;
  return { st: mins <= lib.REC_MAX ? 'ok' : 'gap', idx, m: obs[idx].m, mins, res, dev: lib.meanDev(res.rows) };
}
