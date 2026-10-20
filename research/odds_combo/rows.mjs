// 研究用・1 回きり(wip/odds-final-combo-20261020)。最終予測に 馬連・ワイド・3連複 の売れ方を足せるかの材料を作る。
// ⛔本番 DB は REST の単純 select だけ(日ごと)。書き込みなし。式は本番の odds-final.mjs を取って呼ぶ(書き直さない)。
// 出力: out/rows.csv(レース×T×馬)・out/meta.json(件数・cats・k)
// 使い方: node research/odds_combo/rows.mjs [--from 2026-09-08] [--to 2026-10-19]
import { writeFileSync, mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 && i + 1 < args.length ? args[i + 1] : d; };
const FROM = opt('--from', '2026-09-08');
const TO = opt('--to', '2026-10-19');
const ymd = (d) => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return ymd(d); };
const stamp = Date.now();
const LIB = `https://yukochi.com/viewer-data/odds-forecast/odds-final.mjs?v=${stamp}`;
const MODEL = `https://yukochi.com/viewer-data/odds-forecast/model.json?v=${stamp}`;
const KINDS = ['umaren', 'wide', 'sanrenpuku'];
const TS = [5, 10, 20, 30];
const GAP = 4;         // T 分前以前で最新の単勝の刻みが T+4 分以内(本番 ADJ_GAP と同じ)
const CGAP = 10;       // 組の刻みは T 分前以前で最新・T+10 分より古ければ欠け

const URL0 = (process.env.SUPABASE_URL || '').replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY;
if (!KEY || !process.env.SUPABASE_URL) { console.error('鍵が無い'); process.exit(1); }
const H = { apikey: KEY, Authorization: 'Bearer ' + KEY };
const get = async (p) => {
  for (let a = 0; ; a++) {
    try {
      const r = await fetch(URL0 + p, { headers: H });
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + p.slice(0, 200));
      return await r.json();
    } catch (e) { if (a >= 3) throw e; await new Promise((z) => setTimeout(z, 4000 * (a + 1))); }
  }
};
// id 昇順の続き取り(id=gt)
const byId = async (path) => {
  let out = []; let last = null;
  for (;;) {
    const j = await get(path + '&order=id.asc&limit=1000' + (last === null ? '' : '&id=gt.' + last));
    out = out.concat(j);
    if (j.length < 1000) return out;
    last = j[j.length - 1].id;
  }
};

const f = join(mkdtempSync(join(tmpdir(), 'odds-combo-')), 'odds-final.mjs');
writeFileSync(f, await (await fetch(LIB, { cache: 'no-store' })).text());
const lib = await import(pathToFileURL(f).href);
const model = await (await fetch(MODEL, { cache: 'no-store' })).json();
const adj = ((await get('nar_meta?select=value&key=eq.odds_forecast_adj'))[0] || {}).value;
const { obsOf, hobsOf, finOf, pickAt, forecast, exoticAt, postMinOf, adjFor } = lib;

const toMap = (o, pick) => { const m = new Map(); for (const [k, v] of Object.entries(o && typeof o === 'object' ? o : {})) { const u = Number(k); if (Number.isFinite(u)) m.set(u, pick(v)); } return m; };
const num = (x) => { const n = Number(x); return x === null || x === undefined || x === '' || !Number.isFinite(n) ? null : n; };
const pos = (x) => { const o = num(x); return o !== null && o > 0 ? o : null; };
const oddsOf = (x) => {
  if (Array.isArray(x)) return oddsOf(x[0]);
  if (typeof x === 'string') { const m = /[\d.]+/.exec(x); return m ? pos(m[0]) : null; }
  return pos(x);
};
// observed_at(UTC)→ JST の分(0 時から)と JST の日付
const jstMin = (s) => { const t = Date.parse(s); if (!Number.isFinite(t)) return null; const d = new Date(t + 9 * 3600e3); return { d: ymd(d), m: d.getUTCHours() * 60 + d.getUTCMinutes() }; };

// 組 → 馬ごとの 1/オッズ の和(組の中の馬に同じだけ割り振る)
function horseSum(combos) {
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
function devOf(cur, hs) {
  if (!hs || cur.size < 2 || [...cur.keys()].some((u) => !(hs.get(u) > 0))) return null;
  let sw = 0; let se = 0;
  for (const [u, v] of cur) { sw += 1 / v; se += hs.get(u); }
  return new Map([...cur].map(([u, v]) => [u, Math.log((1 / v / sw) / (hs.get(u) / se))]));
}

const C = { days: 0, races: 0, raceT: 0, raceT_skipGap: 0, rows: 0, full: {}, comboUse: {}, firstCombo: {} };
for (const k of KINDS) { C.full[k] = { all: 0, final: 0, afterPost: 0, otherDay: 0, cand: 0 }; C.comboUse[k] = { now: 0, prev: 0, miss: 0 }; }
const hdr = ['d', 'track', 'no', 'T', 'mins', 'u', 'cur', 'fin', 'midB', 'lowB', 'highB', 'midA', 'lowA', 'highA', 'adj',
  ...Array.from({ length: 18 }, (_, i) => 'x' + i), 'lu', 'lw', 'ls', 'cu', 'cw', 'cs'];
const out = [hdr.join(',')];
const fmt = (v) => (v === null || v === undefined || !Number.isFinite(v) ? '' : String(Math.round(v * 1e6) / 1e6));

for (let d = FROM; d <= TO; d = addDays(d, 1)) {
  const races = await get(`nar_races?select=track,race_no,post_time&race_date=eq.${d}&order=track.asc,race_no.asc&limit=1000`);
  if (!races.length) continue;
  const post = new Map(races.map((r) => [r.track + '|' + r.race_no, r.post_time]));
  const tk = await byId(`nar_odds_ticks?select=id,track,race_no,t,f,w,p,u1,s1&race_date=eq.${d}`);
  if (!tk.length) continue;
  const fm = await byId(`nar_odds_full_ticks?select=id,track,race_no,kind,observed_at,f&race_date=eq.${d}&kind=in.(${KINDS.join(',')})`);
  C.days += 1;
  const by = new Map();
  for (const r of tk) {
    const k = r.track + '|' + r.race_no;
    if (!by.has(k)) by.set(k, []);
    if (!r.t) continue;
    by.get(k).push({ t: String(r.t), f: r.f === true, w: toMap(r.w, pos), p: r.p ? toMap(r.p, (x) => (Array.isArray(x) ? x.map(num) : null)) : null, u1: r.u1 ? toMap(r.u1, pos) : null, s1: r.s1 ? toMap(r.s1, pos) : null });
  }
  // 組の刻み(確定・発走後・別の日を除く)
  const fb = new Map();
  for (const r of fm) {
    const k = r.track + '|' + r.race_no;
    const c = C.full[r.kind];
    c.all += 1;
    if (r.f === true) { c.final += 1; continue; }
    const j = jstMin(r.observed_at);
    const pm = postMinOf(post.get(k) ? String(post.get(k)).replace(/^(\d{2}):?(\d{2}).*$/, '$1$2') : null);
    if (!j || j.d !== d) { c.otherDay += 1; continue; }
    if (pm === null || j.m > pm) { c.afterPost += 1; continue; }
    c.cand += 1;
    const kk = k + '|' + r.kind;
    if (!fb.has(kk)) fb.set(kk, []);
    fb.get(kk).push({ id: r.id, m: j.m });
  }
  const pickC = (k, kind, lim) => { let best = null; for (const o of fb.get(k + '|' + kind) || []) if (o.m <= lim && o.m >= lim - CGAP && (!best || o.m > best.m || (o.m === best.m && o.id > best.id))) best = o; return best; };
  // 1 周目= 使う刻みを決める
  const plan = [];
  const need = new Set();
  for (const [k, ticks] of by) {
    const [track, no] = k.split('|');
    const pt = post.get(k);
    const pm = postMinOf(pt ? String(pt).replace(/^(\d{2}):?(\d{2}).*$/, '$1$2') : null);
    if (pm === null) continue;
    const obs = obsOf(ticks);
    const hobs = hobsOf(ticks);
    if (!obs.length || forecast(model, obs, hobs, obs.length - 1, pm, track, Number(no)) === null) continue;
    const fin = finOf(ticks);
    if (!fin) continue;
    C.races += 1;
    for (const T of TS) {
      const idx = pickAt(obs, pm, T);
      if (idx < 0) continue;
      const m = obs[idx].m;
      if (pm - m > T + GAP) { C.raceT_skipGap += 1; continue; }
      const sel = {};
      for (const kind of KINDS) {
        const a = pickC(k, kind, pm - T);
        const b = pickC(k, kind, pm - T - 10);
        sel[kind] = [a, b];
        if (a) need.add(a.id); if (b) need.add(b.id);
      }
      plan.push({ k, track, no: Number(no), pm, obs, hobs, idx, m, T, fin, ticks, sel });
    }
  }
  const combos = new Map();
  const ids = [...need].sort((a, b) => a - b);
  for (let i = 0; i < ids.length; i += 40) {
    const j = await get(`nar_odds_full_ticks?select=id,kind,combos&id=in.(${ids.slice(i, i + 40).join(',')})`);
    for (const r of j) {
      if (!C.firstCombo[r.kind] && Array.isArray(r.combos) && r.combos.length) C.firstCombo[r.kind] = r.combos.slice(0, 2);
      combos.set(r.id, horseSum(r.combos));
    }
  }
  let n = 0;
  for (const P of plan) {
    const rsB = forecast(model, P.obs, P.hobs, P.idx, P.pm, P.track, P.no);
    if (!rsB || !rsB.length) continue;
    const rsA = forecast(model, P.obs, P.hobs, P.idx, P.pm, P.track, P.no, { date: d, adj, ...exoticAt(P.ticks, P.m) });
    const cur = new Map(rsB.map((r) => [r.u, r.cur]));
    const dv = {};
    for (const kind of KINDS) {
      const [a, b] = P.sel[kind];
      const now = a ? devOf(cur, combos.get(a.id)) : null;
      const prev = b ? devOf(cur, combos.get(b.id)) : null;
      dv[kind] = [now, prev];
      if (now) C.comboUse[kind].now += 1; else C.comboUse[kind].miss += 1;
      if (now && prev) C.comboUse[kind].prev += 1;
    }
    const usedAdj = adjFor(adj, d) ? 1 : 0;
    C.raceT += 1;
    rsB.forEach((r, i) => {
      const fv = P.fin.get(r.u);
      if (!(fv > 0)) return;
      const ra = rsA[i];
      const lv = KINDS.map((kd) => (dv[kd][0] ? dv[kd][0].get(r.u) : null));
      const cv = KINDS.map((kd) => (dv[kd][0] && dv[kd][1] ? dv[kd][0].get(r.u) - dv[kd][1].get(r.u) : null));
      out.push([d, P.track, P.no, P.T, r.mins, r.u, r.cur, fv, r.mid, r.low, r.high, ra.mid, ra.low, ra.high, usedAdj,
        ...r.x.map((v) => (Number.isFinite(v) ? v : null)), ...lv, ...cv].map((v, j) => (j <= 1 ? v : fmt(v))).join(','));
      n += 1;
    });
  }
  C.rows += n;
  console.log(`${d} 刻み ${tk.length} 組の刻み ${fm.length} 組を読んだ ${ids.length} 行 ${n}`);
}
mkdirSync('out', { recursive: true });
writeFileSync('out/rows.csv', out.join('\n') + '\n');
writeFileSync('out/meta.json', JSON.stringify({ from: FROM, to: TO, cats: model.cats, k: model.k, built_on: model.built_on, adjSince: (adj && adj.list || []).map((a) => a.since), counts: C }, null, 1));
console.log(JSON.stringify(C));
