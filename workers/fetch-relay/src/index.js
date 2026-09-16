// §195c nar-fetch-relay — 取るだけの小さな道具。
//
// なぜ要るか(§195 段 1)= 大井公式は **GitHub ランナーの IP に 403**(UA を替えても・curl でも・HTML 一覧でも)。
// Cloudflare 側からは便と同じ名乗り `nar-jobs-health/1.0` のままで 200(2026-09-16 実測)。
// robots は `/news/feed/` を禁じていない。⛔UA は偽らない・⛔関門(HTML の「Just a moment」)には触らない。
//
// 型= **計算と読み解きは GitHub の便、拒まれる取得だけここ**。ここは取って生のまま `nar_fetch_raw` に置く。
// 別のサイトが拒み始めたら SOURCES に 1 行足すだけ。⛔ここで中身を読まない・切らない・直さない。
//
// ⛔inbound は受けない(fetch は 404)。⛔ログに URL を出さない(source/key/status/長さだけ)。
// ⛔鍵は env の secret(SUPABASE_URL / SUPABASE_SERVICE_KEY)= repo には書かない。

export const MAX_BYTES = 2 * 1024 * 1024;   // 2MB 超は表に入れず status -1 で印
export const GAP_MS = 3000;                 // ⛔先方に優しく= 1 本ごとに 3 秒あける
export const TABLE = 'nar_fetch_raw';

// 取る先の一覧。⛔ここだけが行き先= 動かせるのは頁の数字だけ
export const SOURCES = [
  {
    source: 'ooi_official',                 // 大井 主催者公式の「出来事」RSS(§110)
    ua: 'nar-jobs-health/1.0',              // ⛔便(cloud/health_org.py の UA)と同じ名乗り
    pages: 8,                               // 1 頁 10 件。便の MAX_PAGES と同じ
    url: (n) => `https://www.tokyocitykeiba.com/news/feed/?s=${encodeURIComponent('出来事')}&paged=${n}`,
  },
];

// 一覧 → 取りに行く 1 本ずつ(純関数)
export function targets(sources = SOURCES) {
  const out = [];
  for (const s of sources) {
    for (let n = 1; n <= s.pages; n += 1) {
      out.push({ source: s.source, key: `paged=${n}`, url: s.url(n), ua: s.ua });
    }
  }
  return out;
}

export function byteLength(text) {
  return typeof text === 'string' ? new TextEncoder().encode(text).length : 0;
}

// 表に入れる 1 行(純関数)。⛔本文は 200 のときだけ・2MB 超は入れず status -1
export function rawRow(target, got, now) {
  const status = Number.isInteger(got && got.status) ? got.status : 0;
  const body = got && typeof got.body === 'string' ? got.body : null;
  const tooBig = body !== null && byteLength(body) > MAX_BYTES;
  return {
    source: target.source,
    key: target.key,
    url: target.url,
    status: tooBig ? -1 : status,
    content_type: (got && got.contentType) || null,
    body: status === 200 && !tooBig ? body : null,
    fetched_at: now,
  };
}

// ログの 1 行(純関数)。⛔URL は出さない
export function logLine(row) {
  return `${row.source} ${row.key} status=${row.status} bytes=${byteLength(row.body)}`;
}

export const UPSERT_PATH = `${TABLE}?on_conflict=source,key`;

export function upsertHeaders(key) {
  return {
    apikey: key,
    Authorization: `Bearer ${key}`,
    'Content-Type': 'application/json',
    Prefer: 'resolution=merge-duplicates,return=minimal',
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchOne(target) {
  try {
    const res = await fetch(target.url, {
      headers: { 'User-Agent': target.ua, 'Accept-Language': 'ja' },
    });
    // ⛔status に関わらず本文は読む(rawRow が 200 以外は捨てる)= 途中で例外にしない
    const body = await res.text();
    return { status: res.status, contentType: res.headers.get('content-type'), body };
  } catch {
    return { status: 0, contentType: null, body: null };   // 通信が切れた= status 0 で残す
  }
}

async function putRows(env, rows, log) {
  if (!env || !env.SUPABASE_URL || !env.SUPABASE_SERVICE_KEY) {
    log('⛔SUPABASE_URL / SUPABASE_SERVICE_KEY が無いので表に置けない');
    return 0;
  }
  const res = await fetch(`${String(env.SUPABASE_URL).replace(/\/+$/, '')}/rest/v1/${UPSERT_PATH}`, {
    method: 'POST',
    headers: upsertHeaders(env.SUPABASE_SERVICE_KEY),
    body: JSON.stringify(rows),
  });
  log(`upsert rows=${rows.length} status=${res.status}`);
  return res.ok ? rows.length : 0;
}

// 1 回ぶん。⛔1 本ずつ 3 秒あけて取り、最後に 1 回だけ表へ置く
export async function runOnce(env, log = console.log) {
  const list = targets();
  const rows = [];
  for (let i = 0; i < list.length; i += 1) {
    if (i > 0) await sleep(GAP_MS);
    const row = rawRow(list[i], await fetchOne(list[i]), new Date().toISOString());
    log(logLine(row));
    rows.push(row);
  }
  await putRows(env, rows, log);
  return rows;
}

export default {
  // ⛔入口は作らない(route も workers.dev も無い)。万一届いても何も返さない
  async fetch() {
    return new Response('Not Found', { status: 404 });
  },
  async scheduled(event, env) {
    await runOnce(env);
  },
};
