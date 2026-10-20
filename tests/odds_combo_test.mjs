// 並走の 24 特徴の試験(本物のデータ)。⛔作り物の fixture は使わない。
// 1) 模型の引き方: tests/fixtures/odds_combo_fixture.json(10/19 の本物の 300 行・LightGBM の予測)を本番の lib.predictQ で再現。
//    ずれる行は全部「値が木の閾値(7 桁に丸め)と 2e-6 以内」= rows.csv が 6 桁に丸めた値のせいであること。
// 2) 組の 6 特徴: cloud/odds_combo.mjs の式で 1 日分(既定 2026-10-19)を本番 DB から作り、研究の rows.csv(rows.mjs の出力)と照合。
// 使い方: node tests/odds_combo_test.mjs --csv out/rows.csv [--day 2026-10-19]   env: SUPABASE_URL / SUPABASE_SERVICE_KEY
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { comboDay, comboFeats } from '../cloud/odds_combo.mjs';

const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 && i + 1 < args.length ? args[i + 1] : d; };
const CSV = opt('--csv', 'out/rows.csv');
const DAY = opt('--day', '2026-10-19');
const HERE = dirname(fileURLToPath(import.meta.url));
let fail = 0;
const ok = (c, msg) => { console.log((c ? 'ok   ' : 'FAIL ') + msg); if (!c) fail += 1; };

const f = join(mkdtempSync(join(tmpdir(), 'odds-combo-test-')), 'odds-final.mjs');
writeFileSync(f, await (await fetch(`https://yukochi.com/viewer-data/odds-forecast/odds-final.mjs?v=${Date.now()}`, { cache: 'no-store' })).text());
const lib = await import(pathToFileURL(f).href);
const model = JSON.parse(readFileSync(join(HERE, '../cloud/odds_combo_model.json'), 'utf8'));

// ---- 1) 模型の引き方
const fx = JSON.parse(readFileSync(join(HERE, 'fixtures/odds_combo_fixture.json'), 'utf8'));
const near = (x) => model.models.some((trees) => trees.some((T) => (T.f || []).some((fi, i) => T.c[i] === 0 && Number.isFinite(x[fi]) && Math.abs(x[fi] - T.t[i]) <= 2e-6 * Math.max(1, Math.abs(x[fi])))));
let same = 0; let diffNear = 0; let diffFar = 0;
for (const r of fx.rows) {
  const x = r.x.map((v) => (v === null ? NaN : v));
  const q = lib.predictQ(model, x);
  const d = Math.max(...q.map((v, i) => Math.abs(v - r.q_log[i])));
  if (d <= 1e-6) same += 1; else if (near(x)) diffNear += 1; else diffFar += 1;
}
ok(diffFar === 0 && same >= 250, `模型の引き方 一致 ${same}/${fx.rows.length}・閾値際でずれ ${diffNear}・それ以外でずれ ${diffFar}`);
ok(model.feats.length === 24 && model.k === fx.k, `feats ${model.feats.length}・k ${model.k}`);

// ---- 2) 組の 6 特徴
const BASE = process.env.SUPABASE_URL.replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY;
const H = { apikey: KEY, Authorization: 'Bearer ' + KEY };
const get = async (p) => { const r = await fetch(BASE + p, { headers: H }); if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + p.slice(0, 200)); return r.json(); };
const toMap = (o, pick) => { const m = new Map(); for (const [k, v] of Object.entries(o && typeof o === 'object' ? o : {})) { const u = Number(k); if (Number.isFinite(u)) m.set(u, pick(v)); } return m; };
const num = (x) => { const n = Number(x); return x === null || x === undefined || x === '' || !Number.isFinite(n) ? null : n; };
const pos = (x) => { const o = num(x); return o !== null && o > 0 ? o : null; };

const lines = readFileSync(CSV, 'utf8').split('\n').filter(Boolean);
const hdr = lines[0].split(',');
const ci = Object.fromEntries(hdr.map((h, i) => [h, i]));
const want = new Map();
for (const ln of lines.slice(1)) {
  const a = ln.split(',');
  if (a[0] !== DAY) continue;
  want.set([a[1], a[2], a[3], a[5]].join('|'), a);
}
const races = await get(`nar_races?select=track,race_no,post_time&race_date=eq.${DAY}&limit=1000`);
const post = new Map(races.map((r) => [r.track + '|' + r.race_no, r.post_time]));
let rows = [];
for (let off = 0; ; off += 1000) {
  const j = await get(`nar_odds_ticks?select=id,track,race_no,t,f,w,p,u1,s1&race_date=eq.${DAY}&order=id.asc&limit=1000&offset=${off}`);
  rows = rows.concat(j);
  if (j.length < 1000) break;
}
const by = new Map();
for (const r of rows) {
  const k = r.track + '|' + r.race_no;
  if (!by.has(k)) by.set(k, []);
  if (!r.t) continue;
  by.get(k).push({ t: String(r.t), f: r.f === true, w: toMap(r.w, pos), p: r.p ? toMap(r.p, (x) => (Array.isArray(x) ? x.map(num) : null)) : null });
}
const pmBy = new Map();
for (const k of by.keys()) {
  const pt = post.get(k);
  pmBy.set(k, lib.postMinOf(pt && /^\d{4}$/.test(String(pt)) ? String(pt).slice(0, 2) + ':' + String(pt).slice(2) : null));
}
const TS = [5, 10, 20, 30];
const cf = await comboDay(get, DAY, [...pmBy].map(([k, pm]) => ({ k, pm })), TS);
const NEW = ['lu', 'lw', 'ls', 'cu', 'cw', 'cs'];
const close = (a, s) => { const b = s === '' ? NaN : Number(s); return (Number.isNaN(a) && Number.isNaN(b)) || Math.abs(a - b) <= 2e-6; };
let match = 0; let bad = 0; let seen = 0; let nonNaN = 0; const badEx = [];
for (const [k, ticks] of by) {
  const [track, no] = k.split('|');
  const pm = pmBy.get(k);
  if (pm === null) continue;
  const ti = model.cats.indexOf(track);
  const obs = lib.obsOf(ticks);
  const hobs = lib.hobsOf(ticks);
  for (const T of TS) {
    const idx = lib.pickAt(obs, pm, T);
    if (idx < 0 || pm - obs[idx].m > T + 4) continue;
    const base = lib.featuresAt(obs, hobs, idx, pm, ti, Number(no));
    if (!base.length) continue;
    const cur = new Map(base.map((r) => [r.u, r.cur]));
    const sel = cf.sel(k, T);
    const cx = sel ? comboFeats(cur, sel, cf.sums) : null;
    for (const r of base) {
      const a = want.get([track, no, T, r.u].join('|'));
      if (!a) continue;
      seen += 1;
      const v = cx ? cx.get(r.u) : NEW.map(() => NaN);
      const good = NEW.every((n, i) => close(v[i], a[ci[n]])) && r.x.every((xv, i) => close(xv, a[ci['x' + i]]));
      if (good) { match += 1; if (v.some((z) => !Number.isNaN(z))) nonNaN += 1; } else { bad += 1; if (badEx.length < 5) badEx.push([k, T, r.u, v, NEW.map((n) => a[ci[n]])]); }
    }
  }
}
ok(match >= 100 && bad === 0 && seen === want.size, `組の 6 特徴(${DAY})rows.csv ${want.size} 行・照合 ${seen}・一致 ${match}(組の値あり ${nonNaN})・不一致 ${bad}`);
if (badEx.length) console.log(JSON.stringify(badEx));
console.log(fail ? `失敗 ${fail}` : '全部 ok');
process.exit(fail ? 1 : 0);
