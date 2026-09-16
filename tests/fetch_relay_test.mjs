// §195c 取るだけの Worker(workers/fetch-relay)。⛔外への通信なし= 純関数と、偽の fetch で回すだけ。
// 実行: node tests/fetch_relay_test.mjs(このPCは Adobe 同梱 node)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import worker, {
  GAP_MS, MAX_BYTES, SOURCES, TABLE, UPSERT_PATH,
  byteLength, logLine, rawRow, runOnce, targets, upsertHeaders,
} from '../workers/fetch-relay/src/index.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = readFileSync(join(ROOT, 'workers', 'fetch-relay', 'src', 'index.js'), 'utf8');
const TOML = readFileSync(join(ROOT, 'workers', 'fetch-relay', 'wrangler.toml'), 'utf8');

// 1) 一覧 → 取りに行く 8 本(⛔動かせるのは頁の数字だけ)
{
  const list = targets();
  assert.equal(list.length, 8);
  assert.deepEqual(list.map((t) => t.key), [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `paged=${n}`));
  for (const [i, t] of list.entries()) {
    assert.equal(t.source, 'ooi_official');
    assert.equal(t.ua, 'nar-jobs-health/1.0', '便と同じ名乗りでない');
    assert.equal(t.url,
      `https://www.tokyocitykeiba.com/news/feed/?s=%E5%87%BA%E6%9D%A5%E4%BA%8B&paged=${i + 1}`);
    assert.equal(new URL(t.url).origin, 'https://www.tokyocitykeiba.com');
    assert.equal(new URL(t.url).pathname, '/news/feed/');
  }
  assert.equal(new Set(list.map((t) => t.url)).size, 8);
  // 出どころが増えても同じ形で増える(将来ほかのサイトが拒んだとき)
  const more = targets([{ source: 'x_official', ua: 'u', pages: 2, url: (n) => `https://x.test/${n}` }]);
  assert.deepEqual(more, [
    { source: 'x_official', key: 'paged=1', url: 'https://x.test/1', ua: 'u' },
    { source: 'x_official', key: 'paged=2', url: 'https://x.test/2', ua: 'u' },
  ]);
  console.log('1) 一覧 → 8 本の URL: OK');
}

// 2) 表に入れる 1 行の形(⛔200 のときだけ本文・2MB 超は status -1)
{
  const t = targets()[0];
  const now = '2026-09-16T21:00:00.000Z';
  const ok = rawRow(t, { status: 200, contentType: 'application/rss+xml; charset=UTF-8', body: '<rss/>' }, now);
  assert.deepEqual(ok, {
    source: 'ooi_official', key: 'paged=1', url: t.url, status: 200,
    content_type: 'application/rss+xml; charset=UTF-8', body: '<rss/>', fetched_at: now,
  });
  // 403 は本文を入れない(status と content_type は残す)
  const ng = rawRow(t, { status: 403, contentType: 'text/html', body: 'Just a moment...' }, now);
  assert.equal(ng.status, 403);
  assert.equal(ng.body, null, '200 以外の本文を入れた');
  assert.equal(ng.content_type, 'text/html');
  // 通信が切れた= status 0
  assert.equal(rawRow(t, { status: 0, contentType: null, body: null }, now).status, 0);
  // 2MB 超= 入れずに -1 の印
  const big = rawRow(t, { status: 200, contentType: 'text/xml', body: 'a'.repeat(MAX_BYTES + 1) }, now);
  assert.equal(big.status, -1);
  assert.equal(big.body, null, '2MB 超を表に入れた');
  // ちょうど 2MB は入る・日本語は字数でなくバイトで数える
  assert.equal(rawRow(t, { status: 200, body: 'a'.repeat(MAX_BYTES) }, now).status, 200);
  assert.equal(byteLength('出来事'), 9);
  console.log('2) 表に入れる 1 行の形: OK');
}

// 3) ログに URL を出さない(⛔置き場を書かない)
{
  const t = targets()[2];
  const line = logLine(rawRow(t, { status: 200, contentType: 'text/xml', body: '出来事' }, 'now'));
  assert.equal(line, 'ooi_official paged=3 status=200 bytes=9');
  assert.equal(line.includes('tokyocitykeiba'), false, '⛔ログに URL が出た');
  assert.equal(line.includes('http'), false);
  assert.equal(logLine(rawRow(t, { status: 403, body: 'x' }, 'now')), 'ooi_official paged=3 status=403 bytes=0');
  // 字の上でも、ログに url を混ぜていない
  assert.doesNotMatch(SRC, /log\([^)]*\.url/, '⛔ログに URL を渡している');
  console.log('3) ログに URL を出さない: OK');
}

// 4) upsert の形(PK (source,key) に重ねる)
{
  assert.equal(TABLE, 'nar_fetch_raw');
  assert.equal(UPSERT_PATH, 'nar_fetch_raw?on_conflict=source,key');
  const h = upsertHeaders('KEY');
  assert.equal(h.apikey, 'KEY');
  assert.equal(h.Authorization, 'Bearer KEY');
  assert.equal(h.Prefer, 'resolution=merge-duplicates,return=minimal');
  assert.equal(h['Content-Type'], 'application/json');
  console.log('4) upsert の形: OK');
}

// 5) ⛔鍵を repo に書いていない・inbound は受けない・3 秒あける・cron は 1 本
{
  assert.doesNotMatch(SRC, /eyJ[A-Za-z0-9_-]{10,}/, '⛔JWT らしき字が入っている');
  assert.doesNotMatch(SRC, /supabase\.co/, '⛔置き場の URL が入っている');
  assert.doesNotMatch(TOML, /eyJ[A-Za-z0-9_-]{10,}|supabase\.co/, '⛔wrangler.toml に鍵や置き場が入っている');
  assert.match(SRC, /env\.SUPABASE_URL/);
  assert.match(SRC, /env\.SUPABASE_SERVICE_KEY/);
  assert.doesNotMatch(SRC, /Mozilla|Chrome|Safari|AppleWebKit/, '⛔ブラウザの名乗りを騙っている');
  assert.equal(GAP_MS, 3000);
  assert.equal(SOURCES.length, 1);
  assert.match(TOML, /^crons = \["0 21 \* \* \*"\]/m, 'cron が 06:00 JST の 1 本でない');
  assert.match(TOML, /^workers_dev = false/m, '⛔公開の入口(workers.dev)が生える');
  assert.doesNotMatch(TOML, /^\s*routes?\s*=/m, '⛔route を作っている');
  assert.equal((await worker.fetch(new Request('https://x.test/'))).status, 404, 'inbound を受けてしまう');
  console.log('5) 鍵なし・入口なし・3 秒・cron 1 本: OK');
}

// 6) 実際に回す(fetch を偽物に差し替え・⛔外へは 1 本も出ない・⛔待ちは飛ばす)
{
  const seen = [];
  const posts = [];
  const realSleep = globalThis.setTimeout;
  globalThis.setTimeout = (fn) => realSleep(fn, 0);      // 3 秒 × 8 を待たない
  globalThis.fetch = async (url, init) => {
    if (String(url).includes('/rest/v1/')) {
      posts.push({ url: String(url), headers: init.headers, rows: JSON.parse(init.body) });
      return new Response(null, { status: 201 });
    }
    seen.push({ url: String(url), ua: init.headers['User-Agent'], lang: init.headers['Accept-Language'] });
    const n = Number(new URL(String(url)).searchParams.get('paged'));
    return n === 5
      ? new Response('Just a moment...', { status: 403, headers: { 'content-type': 'text/html' } })
      : new Response(`<rss>${n}</rss>`, { status: 200, headers: { 'content-type': 'application/rss+xml' } });
  };
  const lines = [];
  const rows = await runOnce({ SUPABASE_URL: 'https://db.test/', SUPABASE_SERVICE_KEY: 'K' }, (s) => lines.push(s));
  globalThis.setTimeout = realSleep;

  assert.equal(seen.length, 8, '先方への要求が 8 本でない');
  assert.deepEqual([...new Set(seen.map((s) => s.ua))], ['nar-jobs-health/1.0']);
  assert.deepEqual([...new Set(seen.map((s) => s.lang))], ['ja']);
  assert.equal(rows.length, 8);
  assert.equal(rows.filter((r) => r.status === 200 && r.body).length, 7);
  assert.equal(rows[4].status, 403);
  assert.equal(rows[4].body, null, '403 の本文を表に入れた');
  // 表へは 1 回だけ・鍵は env から・末尾の / は重ねない
  assert.equal(posts.length, 1, '表へ何回も投げている');
  assert.equal(posts[0].url, 'https://db.test/rest/v1/nar_fetch_raw?on_conflict=source,key');
  assert.equal(posts[0].headers.apikey, 'K');
  assert.equal(posts[0].rows.length, 8);
  assert.equal(posts[0].rows[0].key, 'paged=1');
  assert.ok(posts[0].rows[0].fetched_at.endsWith('Z'), 'fetched_at が ISO でない');
  // ログに URL は 1 本も出ていない
  assert.equal(lines.some((s) => s.includes('tokyocitykeiba') || s.includes('db.test')), false);
  assert.equal(lines[lines.length - 1], 'upsert rows=8 status=201');
  // 鍵が無ければ表へは行かない(⛔黙って外に投げない)
  posts.length = 0;
  const none = [];
  await runOnce({}, (s) => none.push(s));
  assert.equal(posts.length, 0);
  assert.equal(none[none.length - 1].includes('が無いので表に置けない'), true);
  console.log('6) 実際に回す(8 本・403 は本文なし・表へ 1 回・鍵なしは投げない): OK');
}

console.log('fetch_relay_test: ALL PASS');
