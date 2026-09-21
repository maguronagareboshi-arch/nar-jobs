// §238a 検算 (c)= 画面の `js/data.js cornerRanks()` を **node でそのまま呼ぶ**ための小さな器。
//
// ⛔data.js を import しない= 画面用の他の読み込み(fetch・他のモジュール)が付いてくるため。
//   代わりに `export function cornerRanks(order) { … }` の**本文を字面のまま切り出して**評価する
//   (切り出しに失敗したら 1 で落ちる= 黙って別物を測らない)。
//
//   node tests/run_facts_corner_node.mjs <data.js のパス> <入力 JSON> <出力 JSON>
//   入力 JSON= ["7,9,(2,10)-11", …]   出力 JSON= [{"order":…, "ranks":{"7":1,…}|null}, …]
import fs from 'node:fs';

const [, , dataJsPath, inPath, outPath] = process.argv;
if (!dataJsPath || !inPath || !outPath) {
  console.error('usage: node run_facts_corner_node.mjs <data.js> <in.json> <out.json>');
  process.exit(2);
}

const src = fs.readFileSync(dataJsPath, 'utf8');
const head = src.indexOf('export function cornerRanks(');
if (head < 0) {
  console.error('cornerRanks() が見つからない: ' + dataJsPath);
  process.exit(1);
}
// 関数の本文を波括弧の対応で切り出す(文字列リテラルの中の括弧は数えない)
let i = src.indexOf('{', head);
let depth = 0;
let end = -1;
let quote = null;
for (let k = i; k < src.length; k += 1) {
  const c = src[k];
  if (quote) {
    if (c === '\\') { k += 1; continue; }
    if (c === quote) quote = null;
    continue;
  }
  if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
  if (c === '/' && src[k + 1] === '/') { k = src.indexOf('\n', k); if (k < 0) break; continue; }
  if (c === '{') depth += 1;
  else if (c === '}') { depth -= 1; if (depth === 0) { end = k + 1; break; } }
}
if (end < 0) {
  console.error('cornerRanks() の本文が閉じない');
  process.exit(1);
}
const body = src.slice(head, end).replace(/^export\s+/, '');
// eslint-disable-next-line no-new-func
const cornerRanks = new Function(body + '; return cornerRanks;')();

const orders = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const out = orders.map((order) => {
  const m = cornerRanks(order);
  if (!m) return { order, ranks: null };
  const ranks = {};
  for (const [u, r] of m.entries()) ranks[String(u)] = r;
  return { order, ranks };
});
fs.writeFileSync(outPath, JSON.stringify(out), 'utf8');
console.log(`cornerRanks: ${out.length} 件`);
