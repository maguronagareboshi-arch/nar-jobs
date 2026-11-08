// 競馬ブックの頁の中継(2026-11-08)
// 競馬ブックは 2026-11-07 夜から海外の接続を断る(GitHub の便は米国 = 403)。この関数を東京(ap-northeast-1)で動かし、
// GitHub の便の requests の 1 回の要求をそのまま 1 回だけ取り次ぐ。ログイン・Cookie・転送は呼ぶ側(cloud/kb/kb_relay.py)が持つ。
// ⛔ 取り次ぐのは *.keibabook.co.jp だけ。呼べるのは service_role の鍵だけ。東京以外で動いたら 421 で断る(また 403 になるため)。
const ALLOWED = /^https:\/\/([a-z0-9-]+\.)*keibabook\.co\.jp(\/|$)/;
const DROP = new Set(['content-encoding', 'content-length', 'transfer-encoding', 'connection']);

function role(req: Request): string {
  try {
    const tok = (req.headers.get('authorization') ?? '').replace(/^Bearer\s+/i, '');
    const p = tok.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(p + '='.repeat((4 - p.length % 4) % 4))).role ?? '';
  } catch { return ''; }
}
const b64 = (u: Uint8Array) => { let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000)); return btoa(s); };
const unb64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json' } });

Deno.serve(async (req) => {
  const region = Deno.env.get('SB_REGION') ?? '?';
  if (role(req) !== 'service_role') return json({ error: 'service_role only' }, 401);
  if (region !== 'ap-northeast-1') return json({ error: `region ${region} (x-region: ap-northeast-1 を付ける)` }, 421);
  let q: { method?: string; url?: string; headers?: Record<string, string>; body_b64?: string | null };
  try { q = await req.json(); } catch { return json({ error: 'bad json' }, 400); }
  if (!q.url || !ALLOWED.test(q.url)) return json({ error: 'url not allowed' }, 400);
  const method = (q.method ?? 'GET').toUpperCase();
  const h = new Headers();
  for (const [k, v] of Object.entries(q.headers ?? {})) {
    if (!['host', 'content-length', 'connection', 'accept-encoding'].includes(k.toLowerCase())) h.set(k, v);
  }
  try {
    const r = await fetch(q.url, {
      method, headers: h, redirect: 'manual',
      body: q.body_b64 && method !== 'GET' && method !== 'HEAD' ? unb64(q.body_b64) : undefined,
    });
    const body = new Uint8Array(await r.arrayBuffer());
    const out: [string, string][] = [];
    r.headers.forEach((v, k) => { if (k !== 'set-cookie' && !DROP.has(k)) out.push([k, v]); });
    for (const c of r.headers.getSetCookie()) out.push(['set-cookie', c]);
    return json({ status: r.status, url: q.url, headers: out, body_b64: b64(body), region });
  } catch (e) {
    return json({ error: String(e) }, 502);
  }
});
