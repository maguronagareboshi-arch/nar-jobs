// §256 最終オッズの見込み「これまでの答え合わせ」= nar_meta 'odds_final_record' を日×場の行で作り直す夜の便。
// ⛔判定は画面と同じ部品(本番の /viewer-data/odds-forecast/odds-final.mjs と model.json)を取って呼ぶだけ。
//   ここで判定を書き直さない(画面の確定後の答え合わせと数字がずれるため)。
// 使い方: node cloud/odds_record.mjs [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--lib URL|path] [--model URL|path]
//         [--adj path] [--dry-run] [--out file] [--force]
// §259 券種補正の一覧は nar_meta 'odds_forecast_adj'(--adj= 同じ value の手元ファイル・試験用)。読めなければ何も書かずに 1
// 並走(2026-10-20)= 組の 6 特徴を足した 24 特徴の模型(cloud/odds_combo_model.json・公開しない)も同じ答え合わせをして
//   value.shadow = { models, cols, rows, popCols, pop } に書く。⛔既存の行・列・数字は 1 つも変えない(画面は shadow を読まない)。
//   並走が失敗した・期間が 7 日を超える・--no-shadow のときは前の shadow をそのまま残す。--combo-model で模型を差し替え
// env: SUPABASE_URL / SUPABASE_SERVICE_KEY(書く)。読むだけの試験は NAR_ANON_KEY でもよい。
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { comboDay, judgeRace24 } from './odds_combo.mjs';

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 && i + 1 < args.length ? args[i + 1] : def; };
const flag = (name) => args.includes(name);

const jstNow = () => new Date(Date.now() + 9 * 3600e3);
const ymd = (d) => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return ymd(d); };
const today = ymd(jstNow());
const stamp = Date.now();
const FROM = opt('--from', addDays(today, -2));
const TO = opt('--to', today);
const LIB = opt('--lib', `https://yukochi.com/viewer-data/odds-forecast/odds-final.mjs?v=${stamp}`);
const MODEL = opt('--model', `https://yukochi.com/viewer-data/odds-forecast/model.json?v=${stamp}`);
const ADJ = opt('--adj', null);
const DRY = flag('--dry-run');
const OUT = opt('--out', null);
const FORCE = flag('--force');
const META_KEY = 'odds_final_record';
const COMBO_MODEL = opt('--combo-model', join(dirname(fileURLToPath(import.meta.url)), 'odds_combo_model.json'));
const SHADOW_MAX_DAYS = 7;

const die = (msg) => { console.error('停止: ' + msg); process.exit(1); };
if (!/^\d{4}-\d{2}-\d{2}$/.test(FROM) || !/^\d{4}-\d{2}-\d{2}$/.test(TO) || FROM > TO) die(`日付が不正 from=${FROM} to=${TO}`);
// 60 日を過ぎた刻みは間引かれ同じ答えが出ない= 古い日は --force なしでは作り直さない
if (FROM < addDays(today, -50) && !FORCE) die(`from=${FROM} は今日(${today})から 50 日より前。作り直すなら --force`);

const BASE = (process.env.SUPABASE_URL || 'https://qgsnsdjvzzeazbazjlwa.supabase.co').replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY || process.env.NAR_ANON_KEY;
if (!KEY) die('SUPABASE_SERVICE_KEY(または NAR_ANON_KEY)が無い');
if (!DRY && !process.env.SUPABASE_SERVICE_KEY) die('書くには SUPABASE_SERVICE_KEY が要る(試験は --dry-run)');
const H = { apikey: KEY, Authorization: 'Bearer ' + KEY };
const get = async (p) => {
  const r = await fetch(BASE + p, { headers: H });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + p);
  return r.json();
};

const isUrl = (s) => /^https?:\/\//.test(s);
const fetchText = async (src) => {
  if (!isUrl(src)) return readFileSync(resolve(src), 'utf8');
  const r = await fetch(src, { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + src);
  return r.text();
};

// ---- 部品と模型(どちらか取れなければ何も書かずに 1)
let lib, model;
try {
  const code = await fetchText(LIB);
  const f = join(mkdtempSync(join(tmpdir(), 'odds-record-')), 'odds-final.mjs');
  writeFileSync(f, code);
  lib = await import(pathToFileURL(f).href);
  for (const n of ['judgeRace', 'recordRows', 'postMinOf', 'REC_COLS', 'modelLabel', 'recordPopRows', 'POP_COLS', 'adjFor']) if (!(n in lib)) throw new Error('lib に ' + n + ' が無い');
} catch (e) { die('lib が取れない: ' + e.message); }
try {
  model = JSON.parse(await fetchText(MODEL));
  if (!model || typeof model !== 'object') throw new Error('空');
} catch (e) { die('model が取れない: ' + e.message); }
const { judgeRace, recordRows, postMinOf, REC_COLS, modelLabel, recordPopRows, POP_COLS } = lib;
// 並走の模型(取れなければ並走だけ止める= 既存の記録は今まで通り)
let model24 = null;
let shadowOn = !flag('--no-shadow');
if (shadowOn) {
  try {
    for (const n of ['featuresAt', 'predictQ', 'obsOf', 'hobsOf', 'finOf', 'pickAt', 'checkHits', 'meanDev', 'REC_T', 'REC_MAX']) if (!(n in lib)) throw new Error('lib に ' + n + ' が無い');
    model24 = JSON.parse(readFileSync(resolve(COMBO_MODEL), 'utf8'));
    if (!model24 || !Array.isArray(model24.models) || !Array.isArray(model24.feats) || model24.feats.length !== 24) throw new Error('形が違う');
  } catch (e) { shadowOn = false; console.log('並走なし(模型が読めない): ' + e.message); }
}
// §259 券種補正の一覧(since ≤ 日付 の最新の 1 件をその日に使う= 判定は lib の中)
let adj;
try {
  const v = ADJ ? JSON.parse(readFileSync(resolve(ADJ), 'utf8')) : ((await get('nar_meta?select=value&key=eq.odds_forecast_adj'))[0] || {}).value;
  if (!v || v.v !== 1 || !Array.isArray(v.list)) throw new Error('形が違う(行が無い?)');
  adj = v.list;
} catch (e) { die('券種補正の一覧(nar_meta odds_forecast_adj)が読めない: ' + e.message); }

// ---- 今の記録
const cur = await get(`nar_meta?select=value&key=eq.${META_KEY}`);
const old = cur.length && cur[0].value && typeof cur[0].value === 'object' ? cur[0].value : null;
const models = Array.isArray(old?.models) ? [...old.models] : [];
const oldShadow = old && old.shadow && typeof old.shadow === 'object' ? old.shadow : null;
const sModels = Array.isArray(oldShadow?.models) ? [...oldShadow.models] : [];
const sMiOf = () => { const lb = 'combo24:' + model24.built_on; let i = sModels.indexOf(lb); if (i < 0) { sModels.push(lb); i = sModels.length - 1; } return i; };
// §257 mi= その日の見込みの名前(modelLabel= その日に使う補正があれば「built_on+券種(from〜to)」)の番号
const miOf = (d) => { const lb = modelLabel(model, d, adj); let i = models.indexOf(lb); if (i < 0) { models.push(lb); i = models.length - 1; } return i; };

// ---- 刻みの形の直し方= 画面の data.js getRaceTicks と同じ
const toMap = (o, pick) => { const m = new Map(); for (const [k, v] of Object.entries(o && typeof o === 'object' ? o : {})) { const u = Number(k); if (Number.isFinite(u)) m.set(u, pick(v)); } return m; };
const num = (x) => { const n = Number(x); return x === null || x === undefined || x === '' || !Number.isFinite(n) ? null : n; };
// §257 合成オッズ(u1/s1)= data.js の synthNum と同じ(0 以下・数でないものは null)
const synthNum = (x) => { const o = num(x); return o !== null && o > 0 ? o : null; };

const days = []; for (let d = FROM; d <= TO; d = addDays(d, 1)) days.push(d);
const newRows = []; const newPop = []; const keepDays = new Set();
if (shadowOn && days.length > SHADOW_MAX_DAYS) { shadowOn = false; console.log(`並走なし(${days.length} 日 > ${SHADOW_MAX_DAYS} 日)= 前の shadow を残す`); }
const sRows = []; const sPop = [];
for (const d of days) {
  const races = await get(`nar_races?select=track,race_no,post_time&race_date=eq.${d}&limit=1000`);
  const post = new Map(races.map((r) => [r.track + '|' + r.race_no, r.post_time]));
  let rows = [];
  for (let off = 0; ; off += 1000) {
    const j = await get(`nar_odds_ticks?select=id,track,race_no,t,f,w,p,u1,s1&race_date=eq.${d}&order=id.asc&limit=1000&offset=${off}`);
    rows = rows.concat(j);
    if (j.length < 1000) break;
  }
  if (!rows.length) { keepDays.add(d); console.log(`${d} 刻み 0 行 → 既存の行を残す`); continue; }
  const by = new Map();
  for (const r of rows) {
    const k = r.track + '|' + r.race_no;
    if (!by.has(k)) by.set(k, []);
    if (!r.t) continue;
    by.get(k).push({ t: String(r.t), f: r.f === true, w: toMap(r.w, (x) => { const o = num(x); return o !== null && o > 0 ? o : null; }), p: r.p ? toMap(r.p, (x) => (Array.isArray(x) ? x.map(num) : null)) : null, u1: r.u1 ? toMap(r.u1, synthNum) : null, s1: r.s1 ? toMap(r.s1, synthNum) : null });
  }
  const items = [];
  const mi = miOf(d);
  const pmBy = new Map();
  for (const [k, ticks] of by) {
    const [track, no] = k.split('|');
    const pt = post.get(k);
    const hhmm = pt && /^\d{4}$/.test(String(pt)) ? String(pt).slice(0, 2) + ':' + String(pt).slice(2) : null;
    const pm = postMinOf(hhmm);
    pmBy.set(k, pm);
    items.push({ d, tr: track, j: pm === null ? { st: 'no_post' } : judgeRace(model, ticks, pm, track, Number(no), d, adj), mi });
  }
  // 並走(24 特徴)。⛔失敗しても既存の行には触らない(並走だけ止めて前の shadow を残す)
  if (shadowOn) {
    try {
      const cf = await comboDay(get, d, [...pmBy].map(([k, pm]) => ({ k, pm })), [lib.REC_T]);
      const smi = sMiOf();
      const sItems = [];
      for (const [k, ticks] of by) {
        const [track, no] = k.split('|');
        const pm = pmBy.get(k);
        sItems.push({ d, tr: track, j: pm === null ? { st: 'no_post' } : judgeRace24(lib, model24, ticks, pm, track, Number(no), cf, k), mi: smi });
      }
      const sr = recordRows(sItems);
      sRows.push(...sr);
      sPop.push(...recordPopRows(sItems));
      let rc = 0, n = 0, hit = 0;
      for (const a of sr) { rc += a[2]; n += a[3]; hit += a[4]; }
      console.log(`${d} 並走 組の刻み ${cf.heads}(読んだ ${cf.need})レース ${rc} 幅 ${n ? ((hit / n) * 100).toFixed(1) : '-'}% (${hit}/${n})`);
    } catch (e) { shadowOn = false; console.log(`並走なし(${d} で失敗)= 前の shadow を残す: ` + e.message); }
  }
  const dr = recordRows(items);
  newRows.push(...dr);
  newPop.push(...recordPopRows(items));
  let rc = 0, n = 0, hit = 0;
  for (const a of dr) { rc += a[2]; n += a[3]; hit += a[4]; }
  console.log(`${d} レース ${rc} 幅 ${n ? ((hit / n) * 100).toFixed(1) : '-'}% (${hit}/${n}) 場 ${dr.length}`);
}

// ---- 合わせる: from〜to の日は入れ替え(刻み 0 行の日は既存を残す)・ほかの日は残す
const inRange = (d) => d >= FROM && d <= TO && !keepDays.has(d);
const kept = (Array.isArray(old?.rows) ? old.rows : []).filter((a) => Array.isArray(a) && !inRange(a[0]));
// §257 人気の順ごと(pop)も rows と同じ入れ替え方
const keptPop = (Array.isArray(old?.pop) ? old.pop : []).filter((a) => Array.isArray(a) && !inRange(a[0]));
const pop = keptPop.concat(newPop).sort((p, q) => (p[0] < q[0] ? -1 : p[0] > q[0] ? 1 : p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : 0));
const all = kept.concat(newRows).sort((p, q) => (p[0] < q[0] ? -1 : p[0] > q[0] ? 1 : p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : 0));
const built = new Date(Date.now() + 9 * 3600e3).toISOString().replace('Z', '+09:00');
const value = { v: 1, built, models, k: model.k, T: 10, max: 14, cols: REC_COLS, rows: all, popCols: POP_COLS, pop };
const srt = (p, q) => (p[0] < q[0] ? -1 : p[0] > q[0] ? 1 : p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : 0);
if (shadowOn) {
  const sk = (Array.isArray(oldShadow?.rows) ? oldShadow.rows : []).filter((a) => Array.isArray(a) && !inRange(a[0]));
  const skp = (Array.isArray(oldShadow?.pop) ? oldShadow.pop : []).filter((a) => Array.isArray(a) && !inRange(a[0]));
  const sp = skp.concat(sPop).sort(srt);
  value.shadow = { models: sModels, k: model24.k, cols: REC_COLS, rows: sk.concat(sRows).sort(srt), popCols: POP_COLS, pop: sp };
  console.log(`並走の行 ${value.shadow.rows.length}(新 ${sRows.length}・残し ${sk.length})人気の行 ${sp.length} models ${JSON.stringify(sModels)}`);
} else if (oldShadow) value.shadow = oldShadow;
if (OUT) writeFileSync(OUT, JSON.stringify(value));
console.log(`行 ${all.length}(新 ${newRows.length}・残し ${kept.length})人気の行 ${pop.length} models ${JSON.stringify(models)}`);

if (DRY) { console.log('dry-run: 書かない'); process.exit(0); }
const r = await fetch(BASE + 'nar_meta?on_conflict=key', {
  method: 'POST',
  headers: { ...H, 'Content-Type': 'application/json', Prefer: 'resolution=merge-duplicates,return=minimal' },
  body: JSON.stringify([{ key: META_KEY, value, updated_at: new Date().toISOString() }]),
});
if (!r.ok) die('書けない HTTP ' + r.status + ' ' + (await r.text()).slice(0, 300));
console.log('書いた: nar_meta ' + META_KEY);
