// §256 最終オッズの見込み「これまでの答え合わせ」= nar_meta 'odds_final_record' を日×場の行で作り直す夜の便。
// ⛔判定は画面と同じ部品(本番の /viewer-data/odds-forecast/odds-final.mjs と model.json)を取って呼ぶだけ。
//   ここで判定を書き直さない(画面の確定後の答え合わせと数字がずれるため)。
// 使い方: node cloud/odds_record.mjs [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--lib URL|path] [--model URL|path]
//         [--dry-run] [--out file] [--force]
// env: SUPABASE_URL / SUPABASE_SERVICE_KEY(書く)。読むだけの試験は NAR_ANON_KEY でもよい。
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

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
const LIB = opt('--lib', `https://nar.yukochi.com/viewer-data/odds-forecast/odds-final.mjs?v=${stamp}`);
const MODEL = opt('--model', `https://nar.yukochi.com/viewer-data/odds-forecast/model.json?v=${stamp}`);
const DRY = flag('--dry-run');
const OUT = opt('--out', null);
const FORCE = flag('--force');
const META_KEY = 'odds_final_record';

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
  for (const n of ['judgeRace', 'recordRows', 'postMinOf', 'REC_COLS']) if (!(n in lib)) throw new Error('lib に ' + n + ' が無い');
} catch (e) { die('lib が取れない: ' + e.message); }
try {
  model = JSON.parse(await fetchText(MODEL));
  if (!model || typeof model !== 'object') throw new Error('空');
} catch (e) { die('model が取れない: ' + e.message); }
const { judgeRace, recordRows, postMinOf, REC_COLS } = lib;

// ---- 今の記録
const cur = await get(`nar_meta?select=value&key=eq.${META_KEY}`);
const old = cur.length && cur[0].value && typeof cur[0].value === 'object' ? cur[0].value : null;
const models = Array.isArray(old?.models) ? [...old.models] : [];
const builtOn = model.built_on ?? null;
let mi = models.indexOf(builtOn);
if (mi < 0) { models.push(builtOn); mi = models.length - 1; }

// ---- 刻みの形の直し方= 画面の data.js getRaceTicks と同じ
const toMap = (o, pick) => { const m = new Map(); for (const [k, v] of Object.entries(o && typeof o === 'object' ? o : {})) { const u = Number(k); if (Number.isFinite(u)) m.set(u, pick(v)); } return m; };
const num = (x) => { const n = Number(x); return x === null || x === undefined || x === '' || !Number.isFinite(n) ? null : n; };

const days = []; for (let d = FROM; d <= TO; d = addDays(d, 1)) days.push(d);
const newRows = []; const keepDays = new Set();
for (const d of days) {
  const races = await get(`nar_races?select=track,race_no,post_time&race_date=eq.${d}&limit=1000`);
  const post = new Map(races.map((r) => [r.track + '|' + r.race_no, r.post_time]));
  let rows = [];
  for (let off = 0; ; off += 1000) {
    const j = await get(`nar_odds_ticks?select=id,track,race_no,t,f,w,p&race_date=eq.${d}&order=id.asc&limit=1000&offset=${off}`);
    rows = rows.concat(j);
    if (j.length < 1000) break;
  }
  if (!rows.length) { keepDays.add(d); console.log(`${d} 刻み 0 行 → 既存の行を残す`); continue; }
  const by = new Map();
  for (const r of rows) {
    const k = r.track + '|' + r.race_no;
    if (!by.has(k)) by.set(k, []);
    if (!r.t) continue;
    by.get(k).push({ t: String(r.t), f: r.f === true, w: toMap(r.w, (x) => { const o = num(x); return o !== null && o > 0 ? o : null; }), p: r.p ? toMap(r.p, (x) => (Array.isArray(x) ? x.map(num) : null)) : null });
  }
  const items = [];
  for (const [k, ticks] of by) {
    const [track, no] = k.split('|');
    const pt = post.get(k);
    const hhmm = pt && /^\d{4}$/.test(String(pt)) ? String(pt).slice(0, 2) + ':' + String(pt).slice(2) : null;
    const pm = postMinOf(hhmm);
    items.push({ d, tr: track, j: pm === null ? { st: 'no_post' } : judgeRace(model, ticks, pm, track, Number(no)), mi });
  }
  const dr = recordRows(items);
  newRows.push(...dr);
  let rc = 0, n = 0, hit = 0;
  for (const a of dr) { rc += a[2]; n += a[3]; hit += a[4]; }
  console.log(`${d} レース ${rc} 幅 ${n ? ((hit / n) * 100).toFixed(1) : '-'}% (${hit}/${n}) 場 ${dr.length}`);
}

// ---- 合わせる: from〜to の日は入れ替え(刻み 0 行の日は既存を残す)・ほかの日は残す
const inRange = (d) => d >= FROM && d <= TO && !keepDays.has(d);
const kept = (Array.isArray(old?.rows) ? old.rows : []).filter((a) => Array.isArray(a) && !inRange(a[0]));
const all = kept.concat(newRows).sort((p, q) => (p[0] < q[0] ? -1 : p[0] > q[0] ? 1 : p[1] < q[1] ? -1 : p[1] > q[1] ? 1 : 0));
const built = new Date(Date.now() + 9 * 3600e3).toISOString().replace('Z', '+09:00');
const value = { v: 1, built, models, k: model.k, T: 10, max: 14, cols: REC_COLS, rows: all };
if (OUT) writeFileSync(OUT, JSON.stringify(value));
console.log(`行 ${all.length}(新 ${newRows.length}・残し ${kept.length})models ${JSON.stringify(models)} mi ${mi}`);

if (DRY) { console.log('dry-run: 書かない'); process.exit(0); }
const r = await fetch(BASE + 'nar_meta?on_conflict=key', {
  method: 'POST',
  headers: { ...H, 'Content-Type': 'application/json', Prefer: 'resolution=merge-duplicates,return=minimal' },
  body: JSON.stringify([{ key: META_KEY, value, updated_at: new Date().toISOString() }]),
});
if (!r.ok) die('書けない HTTP ' + r.status + ' ' + (await r.text()).slice(0, 300));
console.log('書いた: nar_meta ' + META_KEY);
