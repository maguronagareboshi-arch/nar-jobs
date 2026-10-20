// 並走の dry-run 照合: odds_record.mjs --dry-run --out の value と今の nar_meta odds_final_record を比べる。
// ⛔既存の鍵(built と shadow 以外)が全部同じ・shadow の行が出ていることを確かめる。
// 使い方: node tests/odds_record_diff.mjs out/rec.json 2026-10-19   env: SUPABASE_URL / SUPABASE_SERVICE_KEY
import { readFileSync } from 'node:fs';
const [file, day] = process.argv.slice(2);
const BASE = process.env.SUPABASE_URL.replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY;
const r = await fetch(BASE + 'nar_meta?select=value&key=eq.odds_final_record', { headers: { apikey: KEY, Authorization: 'Bearer ' + KEY } });
const cur = (await r.json())[0].value;
const neu = JSON.parse(readFileSync(file, 'utf8'));
let diff = 0;
const keys = new Set([...Object.keys(cur), ...Object.keys(neu)]);
for (const k of keys) {
  if (k === 'built' || k === 'shadow') continue;
  const a = JSON.stringify(cur[k]); const b = JSON.stringify(neu[k]);
  if (a !== b) { diff += 1; console.log('差: ' + k); }
}
const dayRows = (v) => (v.rows || []).filter((x) => x[0] === day);
const dc = JSON.stringify(dayRows(cur)); const dn = JSON.stringify(dayRows(neu));
console.log(`既存の鍵の差 ${diff}・${day} の行 今 ${dayRows(cur).length} 新 ${dayRows(neu).length} 同じ ${dc === dn}・全行 今 ${(cur.rows || []).length} 新 ${(neu.rows || []).length}・pop 今 ${(cur.pop || []).length} 新 ${(neu.pop || []).length}`);
const s = neu.shadow;
const sd = s ? dayRows(s) : [];
let rc = 0, n = 0, hit = 0, nd = 0, sf = 0, sr = 0;
for (const a of sd) { rc += a[2]; n += a[3]; hit += a[4]; nd += a[5]; sf += a[6]; sr += a[7]; }
let rc0 = 0, n0 = 0, hit0 = 0, nd0 = 0, sf0 = 0;
for (const a of dayRows(neu)) { rc0 += a[2]; n0 += a[3]; hit0 += a[4]; nd0 += a[5]; sf0 += a[6]; }
console.log(`shadow ${s ? 'あり' : 'なし'} models ${JSON.stringify(s && s.models)}・${day} の行 ${sd.length}・レース ${rc}(本番 ${rc0})・幅 ${n ? (hit / n * 100).toFixed(1) : '-'}%(本番 ${n0 ? (hit0 / n0 * 100).toFixed(1) : '-'}%)・平均のずれ ${nd ? (sf / nd).toFixed(2) : '-'}%(本番 ${nd0 ? (sf0 / nd0).toFixed(2) : '-'}%・単勝のまま ${nd ? (sr / nd).toFixed(2) : '-'}%)`);
process.exit(diff === 0 && dc === dn && s && sd.length ? 0 : 1);
