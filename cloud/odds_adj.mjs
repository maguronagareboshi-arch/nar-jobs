// §259 最終オッズの見込みの券種補正(§257)を月 1 回作り直す便。
// ⛔行の作り方・係数の作り方・採点は画面と同じ部品(本番の /viewer-data/odds-forecast/odds-final.mjs の
//   adjRowsOf / fitAdj / adjMae / adjFor)を取って呼ぶだけ。ここで式を書き直さない。
// 手順: 基準日の前日までの 60 日の行を作る → T ごとに 作る= [基準日−60, 基準日−14)・採点= 直近 14 日。
//   採点で「新しい係数」が「今使っている係数(基準日に使う 1 件)」と「補正なし」の両方より平均 |log(最終/見込み)| が
//   小さい T だけ採る。1 つも採れなければ何もしない。採れたら 60 日全部で作り直した係数を since= 基準日の翌日 で一覧の末尾に足す。
//   採らなかった T は今使っている 1 件の係数をそのまま写す(新しい 1 件だけが使われるため)。
// ⛔一覧の古い項目は消さない・書き換えない。since が同じか新しい項目が既にあれば何もしない。
// 使い方: node cloud/odds_adj.mjs [--date YYYY-MM-DD(基準日・既定= JST の今日)] [--lib URL|path] [--model URL|path]
//         [--adj path(一覧の value の手元ファイル・試験用)] [--dry-run] [--out file.md]
// env: SUPABASE_URL / SUPABASE_SERVICE_KEY(書く)。読むだけの試験は NAR_ANON_KEY でもよい。
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 && i + 1 < args.length ? args[i + 1] : def; };
const flag = (name) => args.includes(name);

const ymd = (d) => d.toISOString().slice(0, 10);
const addDays = (s, n) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return ymd(d); };
const today = ymd(new Date(Date.now() + 9 * 3600e3));
const stamp = Date.now();
const BASE_DATE = opt('--date', today);
const LIB = opt('--lib', `https://nar.yukochi.com/viewer-data/odds-forecast/odds-final.mjs?v=${stamp}`);
const MODEL = opt('--model', `https://nar.yukochi.com/viewer-data/odds-forecast/model.json?v=${stamp}`);
const ADJ = opt('--adj', null);
const DRY = flag('--dry-run');
const OUT = opt('--out', null);
const META_KEY = 'odds_forecast_adj';
const DAYS = 60;      // 材料の日数(基準日の前日まで)
const TEST = 14;      // 採点に使う直近の日数

const die = (msg) => { console.error('停止: ' + msg); process.exit(1); };
if (!/^\d{4}-\d{2}-\d{2}$/.test(BASE_DATE)) die('基準日が不正 ' + BASE_DATE);
const FROM = addDays(BASE_DATE, -DAYS);
const TO = addDays(BASE_DATE, -1);
const SPLIT = addDays(BASE_DATE, -TEST);   // これより前= 作る・以後= 採点
const SINCE = addDays(BASE_DATE, 1);

const URL0 = (process.env.SUPABASE_URL || 'https://qgsnsdjvzzeazbazjlwa.supabase.co').replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY || process.env.NAR_ANON_KEY;
if (!KEY) die('SUPABASE_SERVICE_KEY(または NAR_ANON_KEY)が無い');
if (!DRY && !process.env.SUPABASE_SERVICE_KEY) die('書くには SUPABASE_SERVICE_KEY が要る(試験は --dry-run)');
const H = { apikey: KEY, Authorization: 'Bearer ' + KEY };
const get = async (p) => {
  for (let a = 0; ; a++) {
    try {
      const r = await fetch(URL0 + p, { headers: H });
      if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + p);
      return await r.json();
    } catch (e) { if (a >= 2) throw e; await new Promise((z) => setTimeout(z, 3000)); }
  }
};
const isUrl = (s) => /^https?:\/\//.test(s);
const fetchText = async (src) => {
  if (!isUrl(src)) return readFileSync(resolve(src), 'utf8');
  const r = await fetch(src, { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + src);
  return r.text();
};

// ---- 部品・模型・今の一覧(どれか取れなければ何も書かずに 1)
let lib, model, cur;
try {
  const f = join(mkdtempSync(join(tmpdir(), 'odds-adj-')), 'odds-final.mjs');
  writeFileSync(f, await fetchText(LIB));
  lib = await import(pathToFileURL(f).href);
  for (const n of ['adjRowsOf', 'fitAdj', 'adjMae', 'adjFor', 'adjListOf', 'postMinOf', 'ADJ_TS']) if (!(n in lib)) throw new Error('lib に ' + n + ' が無い');
} catch (e) { die('lib が取れない: ' + e.message); }
try {
  model = JSON.parse(await fetchText(MODEL));
  if (!model || !Array.isArray(model.models)) throw new Error('形が違う');
} catch (e) { die('model が取れない: ' + e.message); }
try {
  cur = ADJ ? JSON.parse(readFileSync(resolve(ADJ), 'utf8')) : ((await get(`nar_meta?select=value&key=eq.${META_KEY}`))[0] || {}).value;
  if (!cur || cur.v !== 1 || !Array.isArray(cur.list)) throw new Error('形が違う(行が無い?)');
} catch (e) { die('今の一覧(nar_meta ' + META_KEY + ')が読めない: ' + e.message); }
const { adjRowsOf, fitAdj, adjMae, adjFor, adjListOf, postMinOf, ADJ_TS } = lib;
if (cur.list.some((a) => a && typeof a.since === 'string' && a.since >= SINCE)) {
  console.log(`since ${SINCE} 以後の項目が既にある → 何もしない`);
  process.exit(0);
}
const inUse = adjFor(adjListOf(cur.list), BASE_DATE);   // 基準日に使っている 1 件(無ければ null)

// ---- 行(刻みの形の直し方= odds_record.mjs・画面の data.js getRaceTicks と同じ)
const toMap = (o, pick) => { const m = new Map(); for (const [k, v] of Object.entries(o && typeof o === 'object' ? o : {})) { const u = Number(k); if (Number.isFinite(u)) m.set(u, pick(v)); } return m; };
const num = (x) => { const n = Number(x); return x === null || x === undefined || x === '' || !Number.isFinite(n) ? null : n; };
const pos = (x) => { const o = num(x); return o !== null && o > 0 ? o : null; };
const rows = [];
const dayLog = [];
for (let d = FROM; d <= TO; d = addDays(d, 1)) {
  // 馬単1着の記録が 1 本も無い日は du/ds が作れない= 飛ばす(刻みを読まない)
  const hasEx = await get(`nar_odds_ticks?select=id&race_date=eq.${d}&u1=not.is.null&limit=1`);
  if (!hasEx.length) continue;
  const races = await get(`nar_races?select=track,race_no,post_time&race_date=eq.${d}&limit=1000`);
  const post = new Map(races.map((r) => [r.track + '|' + r.race_no, r.post_time]));
  let tk = [];
  for (let off = 0; ; off += 1000) {
    const j = await get(`nar_odds_ticks?select=id,track,race_no,t,f,w,p,u1,s1&race_date=eq.${d}&order=id.asc&limit=1000&offset=${off}`);
    tk = tk.concat(j);
    if (j.length < 1000) break;
  }
  const by = new Map();
  for (const r of tk) {
    const k = r.track + '|' + r.race_no;
    if (!by.has(k)) by.set(k, []);
    if (!r.t) continue;
    by.get(k).push({ t: String(r.t), f: r.f === true, w: toMap(r.w, pos), p: r.p ? toMap(r.p, (x) => (Array.isArray(x) ? x.map(num) : null)) : null, u1: r.u1 ? toMap(r.u1, pos) : null, s1: r.s1 ? toMap(r.s1, pos) : null });
  }
  let n = 0;
  for (const [k, ticks] of by) {
    const [track, no] = k.split('|');
    const pt = post.get(k);
    const hhmm = pt && /^\d{4}$/.test(String(pt)) ? String(pt).slice(0, 2) + ':' + String(pt).slice(2) : null;
    const pm = postMinOf(hhmm);
    if (pm === null) continue;
    const rs = adjRowsOf(model, ticks, pm, track, Number(no), d);
    rows.push(...rs); n += rs.length;
  }
  dayLog.push(d);
  console.log(`${d} 刻み ${tk.length} 行 ${n}`);
}
const both = (h) => h.du !== null && h.ds !== null;
const fitRows = rows.filter((h) => h.d < SPLIT);
const testRows = rows.filter((h) => h.d >= SPLIT);

// ---- 採否
const r4 = (x) => (x === null ? null : Math.round(x * 10000) / 10000);
const fitA = fitAdj(fitRows);
const table = [];
const take = [];
for (const T of ADJ_TS) {
  const key = String(T);
  const cNew = fitA[key] || null;
  const cCur = inUse && Array.isArray(inUse.T[key]) ? inUse.T[key] : null;
  const none = adjMae(testRows, T, null);
  const sCur = adjMae(testRows, T, cCur);
  const sNew = cNew ? adjMae(testRows, T, cNew) : { n: none.n, mae: null };
  const ok = cNew !== null && none.n > 0 && sNew.mae < none.mae && sNew.mae < sCur.mae;
  if (ok) take.push(T);
  table.push({ T, nFit: fitRows.filter((h) => h.T === T && both(h)).length, nTest: none.n, cNew, cCur, none: none.mae, cur: sCur.mae, neu: sNew.mae, ok });
}
const L = [];
const P = (s) => L.push(s);
P(`# §259 券種補正の作り直し 基準日 ${BASE_DATE}${DRY ? '(dry-run)' : ''}`);
P('');
P(`- 材料 ${FROM}〜${TO}(60 日)のうち馬単1着の記録がある日 ${dayLog.length} 日(${dayLog[0] || '-'}〜${dayLog[dayLog.length - 1] || '-'})`);
P(`- 作る= ${FROM}〜${addDays(SPLIT, -1)}・採点= ${SPLIT}〜${TO}・今使っている 1 件= ${inUse ? 'since ' + inUse.since + '(' + inUse.from + '〜' + inUse.to + ')' : 'なし'}`);
P('');
P('| T | 作る n | 採点 n | 新しい係数 | 今の係数 | 補正なし | 今の係数で | 新しい係数で | 採る |');
P('|---|---|---|---|---|---|---|---|---|');
for (const t of table) {
  P(`| ${t.T} | ${t.nFit} | ${t.nTest} | ${t.cNew ? t.cNew.join(', ') : '-'} | ${t.cCur ? t.cCur.join(', ') : '-'} | ${t.none === null ? '-' : t.none.toFixed(4)} | ${t.cur === null ? '-' : t.cur.toFixed(4)} | ${t.neu === null ? '-' : t.neu.toFixed(4)} | ${t.ok ? '採る' : '採らない'} |`);
}
P('');
let item = null;
if (!take.length) {
  P('採れる T が無い → 何もしない');
} else {
  const fitAll = fitAdj(rows);
  const T = {};
  const score = {};
  for (const t of table) {
    const key = String(t.T);
    const use = t.ok && fitAll[key];
    if (use) T[key] = fitAll[key];
    else if (t.cCur) T[key] = t.cCur;   // 採らなかった T は今の係数を写す
    score[key] = { take: !!use, nFit: t.nFit, nTest: t.nTest, none: r4(t.none), cur: r4(t.cur), new: r4(t.neu) };
  }
  item = { since: SINCE, from: dayLog[0] || FROM, to: TO, T, score, at: new Date(Date.now() + 9 * 3600e3).toISOString().replace('Z', '+09:00') };
  P('足す 1 件: `' + JSON.stringify(item) + '`');
}
const md = L.join('\n') + '\n';
console.log(md);
if (OUT) writeFileSync(OUT, md);
if (!item) process.exit(0);
if (DRY) { console.log('dry-run: 書かない'); process.exit(0); }

// ---- 書く(古い項目はそのまま・末尾に 1 件)。書く直前に読み直して、間に変わっていたら止める
const again = ((await get(`nar_meta?select=value&key=eq.${META_KEY}`))[0] || {}).value;
if (JSON.stringify(again) !== JSON.stringify(cur)) die('読んでから書くまでに一覧が変わった');
const value = { ...cur, v: 1, list: [...cur.list, item] };
const r = await fetch(URL0 + 'nar_meta?on_conflict=key', {
  method: 'POST',
  headers: { ...H, 'Content-Type': 'application/json', Prefer: 'resolution=merge-duplicates,return=minimal' },
  body: JSON.stringify([{ key: META_KEY, value, updated_at: new Date().toISOString() }]),
});
if (!r.ok) die('書けない HTTP ' + r.status + ' ' + (await r.text()).slice(0, 300));
console.log('書いた: nar_meta ' + META_KEY + ' 件数 ' + value.list.length);
