// §129d 予想AI 段階1 の**置き場**の検査。⛔通信も DB も無し= ファイルの字だけを見る。
// 実行: node tests/ai_feat_workflow_test.mjs(このPCは Adobe 同梱 node)
//
// ⛔守りたいこと(9/7 夜に本番 DB が 30 分止まった反省)=
//   **本番のホストに向けて流してよいのは `\copy (select * …) to` だけ**。
//   特徴量の組み立て(refresh_nar_ai_feat)は Actions の中の Postgres でしか呼ばない。
// 確かめるのは 6 つ=
//   ① `refresh_nar_ai_feat` と `pooler.supabase.com` が**同じ step に無い**
//   ② 本番に繋ぐ step の中身は `\copy … to` だけ(insert/update/delete/truncate/create が無い)
//   ③ cron は 06:30 JST の 1 本・本番へ書く step は predict(REST upsert)だけ ④ `timeout-minutes` と `concurrency` がある
//   ⑤ 材料 9 表の名前が全部ある ⑥ SQL の grant/revoke/RLS が `pg_roles` の存在確認で囲まれている
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (...p) => readFileSync(join(ROOT, ...p), 'utf8');
const YML = read('.github', 'workflows', 'nar-ai-feat.yml');
const SQL = read('pipeline', 'sql', 'ai_feat_20260908.sql');
const SCHEMA = read('pipeline', 'sql', 'ai_feat_local_schema.sql');
const PROD_HOST = 'pooler.supabase.com';

// yml の注釈(# …)を落とす。⛔文字列の中の # は今のところ無いが、行頭か空白の後の # だけを落とす。
function stripYamlComments(src) {
  return src.split('\n').map((line) => {
    const m = /(^|\s)#/.exec(line);
    return m ? line.slice(0, m.index + (m[1] ? 1 : 0)) : line;
  }).join('\n');
}
const BODY = stripYamlComments(YML);

// step ごとに切る(`      - name:` / `      - uses:` の行が境目)
function steps(src) {
  const out = [];
  let cur = null;
  for (const line of src.split('\n')) {
    if (/^ {6}- (name|uses):/.test(line)) {
      if (cur) out.push(cur);
      cur = { head: line.trim(), lines: [line] };
    } else if (cur) {
      cur.lines.push(line);
    }
  }
  if (cur) out.push(cur);
  return out.map((s) => ({ head: s.head, text: s.lines.join('\n') }));
}
const STEPS = steps(BODY);

// ---- 1) 本番のホストと refresh_nar_ai_feat が同じ step に居ない
{
  assert.ok(STEPS.length >= 8, 'step が少なすぎる: ' + STEPS.length);
  const both = STEPS.filter((s) => s.text.includes(PROD_HOST) && s.text.includes('refresh_nar_ai_feat'));
  assert.equal(both.length, 0, '本番のホストと refresh_nar_ai_feat が同じ step にある: ' +
    both.map((s) => s.head).join(' / '));
  const prod = STEPS.filter((s) => s.text.includes(PROD_HOST));
  assert.equal(prod.length, 1, '本番に繋ぐ step は 1 つだけのはず: ' + prod.length);
  const local = STEPS.filter((s) => s.text.includes('refresh_nar_ai_feat'));
  assert.equal(local.length, 1, 'refresh_nar_ai_feat を呼ぶ step は 1 つだけのはず: ' + local.length);
  // 地元の Postgres は job の env(PGHOST: localhost)で引く= psql に -h を書いていないこと
  const remote = local[0].text.split('\n')
    .filter((l) => l.includes('psql') && / -h /.test(l));
  assert.deepEqual(remote, [], 'refresh を呼ぶ step が別のホストを向いている');
  assert.ok(!local[0].text.includes('supabase'), 'refresh の step に本番のホストの字がある');
  assert.match(BODY, /^\s+PGHOST:\s*localhost$/m, 'job の env に PGHOST: localhost が無い');
  console.log('1) 本番のホストと refresh が同じ step に無い(本番 1 / 地元 1): OK');
}

// ---- 2) 本番に繋ぐ step で流すのは `\copy … to` だけ
{
  const prod = STEPS.find((s) => s.text.includes(PROD_HOST));
  const sqlish = prod.text.split('\n').map((l) => l.trim())
    .filter((l) => l && !l.startsWith('-') && !/^[a-z_]+:$/.test(l));
  const NG = /\b(insert|update|delete|truncate|create|drop|alter|grant|revoke|vacuum|analyze)\b/i;
  const bad = sqlish.filter((l) => NG.test(l));
  assert.deepEqual(bad, [], '本番に繋ぐ step に書き込みの語がある: ' + JSON.stringify(bad));
  // \copy は全部「to」向き(from= 書き込みは 1 つも無い)
  const copies = sqlish.filter((l) => l.includes('\\copy'));
  assert.ok(copies.length >= 9, '本番からの \\copy が 9 本ない: ' + copies.length);
  for (const c of copies) {
    assert.match(c, /^\\copy \(select \* from public\.[a-z_]+( where [^)]*)?\)\s+to /,
      '本番の \\copy が「(select * from …) to」の形でない: ' + c);
  }
  assert.ok(!/\bfrom '/.test(prod.text), '本番に繋ぐ step に \\copy … from(書き込み)がある');
  console.log('2) 本番は read only(\\copy … to が ' + copies.length + ' 本・書き込みの語 0): OK');
}

// ---- 3) 手で流すだけ(⛔cron はまだ付けない= 所要を実測してから Fable が決める)
{
  assert.match(BODY, /^on:\n(\s+.*\n)*?\s+workflow_dispatch:/m, 'workflow_dispatch が無い');
  // 9/8 所要を実測(10m55s)して cron を付けた= 06:30 JST の 1 本だけ(出馬表は前日朝に入っている)
  assert.ok(/^\s*schedule:/m.test(BODY), 'schedule: が無い');
  assert.equal((BODY.match(/- cron:/g) || []).length, 1, 'cron は 1 本');
  assert.match(BODY, /cron: '30 21 \* \* \*'/, 'cron は 06:30 JST(21:30 UTC)');
  // 本番へ書く step は 1 つだけ= REST の upsert(python)。service key を持つ step がそれ以外に無い
  const keySteps = (BODY.match(/NAR_SUPABASE_SERVICE_KEY/g) || []).length;
  assert.equal(keySteps, 1, 'service key を使う step が 1 つでない: ' + keySteps);
  assert.match(BODY, /base_v1\.py predict/, 'predict の step が無い');
  assert.match(BODY, /base_v1\.py fit/, 'fit の step が無い');
  console.log('3) cron 1 本(06:30 JST)・本番へ書く step は predict だけ: OK');
}

// ---- 4) 止まらないための 2 つ(時間切れ・二重起動よけ)
{
  const m = /timeout-minutes:\s*(\d+)/.exec(BODY);
  assert.ok(m, 'timeout-minutes が無い');
  assert.ok(Number(m[1]) > 0 && Number(m[1]) <= 60, 'timeout-minutes が 1〜60 でない: ' + m[1]);
  assert.match(BODY, /^concurrency:\n\s+group:\s*\S+/m, 'concurrency(二重起動よけ)が無い');
  assert.match(BODY, /cancel-in-progress:\s*false/, '走っている方を殺さない指定が無い');
  console.log('4) timeout-minutes ' + m[1] + ' 分・concurrency あり: OK');
}

// ---- 5) 材料の表が全部ある
{
  // ⚠nar_sales_daily は本番では **view**(中身は nar_sales の group by)。
  //   本番に group by を掛けないので、写すのは材料の nar_sales・view は地元の schema で作る。
  const COPIED = ['nar_runs', 'nar_races', 'auction_sales', 'nar_horses', 'nar_kb_runs',
    'nar_horse_health_events', 'nar_penalties', 'nar_sales', 'nar_meta'];
  for (const t of COPIED) {
    assert.ok(BODY.includes('public.' + t + ')') || BODY.includes('public.' + t + ' where'),
      'yml が ' + t + ' を写していない');
    assert.ok(SCHEMA.includes('create table if not exists public.' + t + ' ('),
      '地元の器に ' + t + ' が無い');
  }
  assert.match(SCHEMA, /create or replace view public\.nar_sales_daily as/,
    '地元の器に nar_sales_daily(view)が無い');
  assert.ok(SQL.includes('public.nar_sales_daily'), 'SQL が nar_sales_daily を読んでいない');
  // SQL が読む表は、写した 9 つと view で全部まかなえている(⛔取り残しが無い)
  const MADE = ['nar_ai_feat_run', 'nar_ai_feat_track', 'nar_ai_meta'];
  const used = [...new Set([...SQL.matchAll(/public\.(nar_[a-z_0-9]+|auction_sales)\b/g)].map((m) => m[1]))]
    .filter((t) => !MADE.includes(t) && !/^nar_(margin_len|corner_ranks|cnt5|avg5|std5|slope5)$/.test(t))
    .filter((t) => t !== 'nar_sales_daily');
  const missing = used.filter((t) => !COPIED.includes(t));
  assert.deepEqual(missing, [], 'SQL が読む表で写していないものがある: ' + JSON.stringify(missing));
  console.log('5) 材料 ' + COPIED.length + ' 表 + view nar_sales_daily(取り残し 0): OK');
}

// ---- 6) 本番だけの役(service_role / anon / authenticated)は pg_roles で囲まれている
{
  for (const w of ['enable row level security', 'to service_role', 'from public, anon, authenticated']) {
    assert.ok(SQL.includes(w), 'SQL から ' + w + ' が消えている(⛔本番での意味は変えない)');
  }
  // `do $…$` の塊を取り出し、囲みの外に裸の grant/revoke/RLS が無いことを見る
  const blocks = [...SQL.matchAll(/do \$(\w+)\$([\s\S]*?)\$\1\$;/g)];
  assert.ok(blocks.length >= 2, 'pg_roles の囲みが 2 つ以上ない: ' + blocks.length);
  for (const b of blocks) {
    assert.match(b[2], /if exists \(select 1 from pg_roles where rolname = 'service_role'\) then/,
      '囲みが pg_roles の存在確認になっていない: ' + b[1]);
  }
  const outside = SQL.replace(/do \$(\w+)\$[\s\S]*?\$\1\$;/g, '')
    .split('\n').filter((l) => !l.trimStart().startsWith('--'));
  for (const [w, why] of [['enable row level security', 'RLS'], ['to service_role', 'grant'],
    ['anon, authenticated', 'revoke']]) {
    const hit = outside.filter((l) => l.includes(w));
    assert.deepEqual(hit, [], why + ' が囲みの外にある: ' + JSON.stringify(hit));
  }
  console.log('6) RLS / grant / revoke は pg_roles の囲みの中(' + blocks.length + ' 塊): OK');
}

console.log('ai_feat_workflow_test: ALL PASS (6/6)');
