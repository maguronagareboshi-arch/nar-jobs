// 11/4 N28 を本番に切り替える前の照合: odds_record.mjs --dry-run --out(lib/model= N28 の新しい odds-final と model)で出た
//   **本番の行**の日ごとの「レース数・幅に入った数・ずれの合計」が、今の nar_meta odds_final_record の shadow の N28 行(combo28:)と同じか。
// 使い方: node tests/odds_record_n28_match.mjs out/rec.json 2026-10-28 2026-11-02   env: SUPABASE_URL / SUPABASE_SERVICE_KEY(または NAR_ANON_KEY)
import { readFileSync } from 'node:fs';

const [file, from, to] = process.argv.slice(2);
const BASE = (process.env.SUPABASE_URL || 'https://qgsnsdjvzzeazbazjlwa.supabase.co').replace(/\/+$/, '') + '/rest/v1/';
const KEY = process.env.SUPABASE_SERVICE_KEY || process.env.NAR_ANON_KEY;
const r = await fetch(BASE + 'nar_meta?select=value&key=eq.odds_final_record', { headers: { apikey: KEY, Authorization: 'Bearer ' + KEY } });
const cur = (await r.json())[0].value;
const neu = JSON.parse(readFileSync(file, 'utf8'));
const cs = cur.shadow || {};
const is28 = (a) => String((cs.models || [])[a[a.length - 1]] || '').startsWith('combo28:');
const sum = (l) => { let rc = 0, n = 0, hit = 0, nd = 0, sf = 0; for (const a of l) { rc += a[2]; n += a[3]; hit += a[4]; nd += a[5]; sf += a[6]; } return { rc, n, hit, nd, sf: Math.round(sf * 1e6) / 1e6 }; };
const days = [];
for (let d = from; d <= to;) { days.push(d); const x = new Date(d + 'T00:00:00Z'); x.setUTCDate(x.getUTCDate() + 1); d = x.toISOString().slice(0, 10); }
let bad = 0;
const tot = { a: [], b: [] };
console.log('日付 | 新しい本番 レース/幅に入った/頭/ずれの合計 | 今の並走 N28 | 同じ');
for (const d of days) {
  const la = (neu.rows || []).filter((a) => a[0] === d);
  const lb = (cs.rows || []).filter((a) => a[0] === d && is28(a));
  tot.a.push(...la); tot.b.push(...lb);
  const A = sum(la); const B = sum(lb);
  const same = A.rc === B.rc && A.hit === B.hit && A.n === B.n && A.nd === B.nd && Math.abs(A.sf - B.sf) < 1e-6;
  if (!same) bad += 1;
  console.log(`${d} | ${A.rc}/${A.hit}/${A.n}/${A.sf.toFixed(3)} | ${B.rc}/${B.hit}/${B.n}/${B.sf.toFixed(3)} | ${same}`);
}
const A = sum(tot.a); const B = sum(tot.b);
console.log(`計 | ${A.rc}/${A.hit}/${A.n}/${A.sf.toFixed(3)}(平均のずれ ${(A.sf / A.nd).toFixed(2)}%)| ${B.rc}/${B.hit}/${B.n}/${B.sf.toFixed(3)}(${(B.sf / B.nd).toFixed(2)}%)`);
console.log(`models ${JSON.stringify(neu.models)}`);
console.log(bad ? `失敗(${bad} 日ずれ)` : '全部 ok');
process.exit(bad ? 1 : 0);
