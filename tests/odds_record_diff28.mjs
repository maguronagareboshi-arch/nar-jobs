// 並走 2 本目の dry-run 照合: odds_record.mjs --dry-run --out の value と今の nar_meta odds_final_record を比べる。
// ⛔既存の鍵(built と shadow 以外)が全部同じ・shadow の N24(combo24)の行・pop・k が今と全部同じ・N28 の行が from〜to に出ること。
// 使い方: node tests/odds_record_diff28.mjs out/rec.json 2026-10-19 2026-10-21   env: SUPABASE_URL / SUPABASE_SERVICE_KEY
import { readFileSync } from 'node:fs';

const [file, from, to] = process.argv.slice(2);
const BASE = process.env.SUPABASE_URL.replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY;
const r = await fetch(BASE + 'nar_meta?select=value&key=eq.odds_final_record', { headers: { apikey: KEY, Authorization: 'Bearer ' + KEY } });
const cur = (await r.json())[0].value;
const neu = JSON.parse(readFileSync(file, 'utf8'));
let diff = 0;
for (const k of new Set([...Object.keys(cur), ...Object.keys(neu)])) {
  if (k === 'built' || k === 'shadow') continue;
  if (JSON.stringify(cur[k]) !== JSON.stringify(neu[k])) { diff += 1; console.log('差: ' + k); }
}
const cs = cur.shadow || {};
const ns = neu.shadow || {};
const lab = (s, a) => (s.models || [])[a[a.length - 1]];
const fam = (s, a) => (String(lab(s, a) || '').startsWith('combo28:') ? 28 : 24);
const only24 = (s) => (s.rows || []).filter((a) => fam(s, a) === 24);
const a24 = only24(cs).map((a) => JSON.stringify(a));
const b24 = only24(ns).map((a) => JSON.stringify(a));
const sameRows = JSON.stringify(a24) === JSON.stringify(b24);
const samePop = JSON.stringify(cs.pop) === JSON.stringify(ns.pop);
const sameK = cs.k === ns.k;
const pre = JSON.stringify(cs.models || []) === JSON.stringify((ns.models || []).slice(0, (cs.models || []).length));
let sdiff = 0;
const diffDays = new Set();
for (let i = 0; i < Math.max(a24.length, b24.length); i += 1) if (a24[i] !== b24[i]) { sdiff += 1; diffDays.add(JSON.parse(a24[i] || b24[i])[0]); }
console.log(`既存の鍵の差 ${diff}・全行 今 ${(cur.rows || []).length} 新 ${(neu.rows || []).length}・pop 今 ${(cur.pop || []).length} 新 ${(neu.pop || []).length}`);
console.log(`N24 の shadow 行 今 ${a24.length} 新 ${b24.length} 同じ ${sameRows} 差 ${sdiff} ${[...diffDays].join(' ')}・pop 同じ ${samePop}・k 同じ ${sameK}(${cs.k})・models の頭が同じ ${pre} ${JSON.stringify(ns.models)}`);
const days = [];
for (let d = from; d <= to;) { days.push(d); const x = new Date(d + 'T00:00:00Z'); x.setUTCDate(x.getUTCDate() + 1); d = x.toISOString().slice(0, 10); }
const sum = (l) => { let rc = 0, n = 0, hit = 0, nd = 0, sf = 0, sr = 0; for (const a of l) { rc += a[2]; n += a[3]; hit += a[4]; nd += a[5]; sf += a[6]; sr += a[7]; } return { rc, n, hit, nd, sf, sr }; };
const f = (o) => `レース ${o.rc}・幅 ${o.n ? (o.hit / o.n * 100).toFixed(1) : '-'}%(${o.hit}/${o.n})・平均のずれ ${o.nd ? (o.sf / o.nd).toFixed(2) : '-'}%・単勝のまま ${o.nd ? (o.sr / o.nd).toFixed(2) : '-'}%`;
let n28 = 0;
for (const d of days) {
  const s28 = (ns.rows || []).filter((a) => a[0] === d && fam(ns, a) === 28);
  n28 += s28.length;
  console.log(`${d} 本番 ${f(sum((neu.rows || []).filter((a) => a[0] === d)))}`);
  console.log(`${d} N24  ${f(sum((ns.rows || []).filter((a) => a[0] === d && fam(ns, a) === 24)))}`);
  console.log(`${d} N28  ${f(sum(s28))}(行 ${s28.length}・k28 ${ns.k28}・pop28 ${(ns.pop28 || []).filter((a) => a[0] === d).length})`);
}
const okAll = diff === 0 && sameRows && samePop && sameK && pre && n28 > 0;
console.log(okAll ? '全部 ok' : '失敗');
process.exit(okAll ? 0 : 1);
