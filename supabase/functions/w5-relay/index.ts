// オッズパークの 5重勝の一覧の中継(2026-11-23・cloud/w5_mail.py 用)
// オッズパークは海外の接続を断る(GitHub の便は米国 = 403)。この関数を東京(ap-northeast-1)で動かし、一覧の頁 1 枚を読んで返す。
// ⛔ 読むのは https://www.oddspark.com/loto/JResultList.do?kaisaiBi=YYYYMMDD だけ・GET だけ。呼べるのは service_role の鍵だけ。
// 東京以外で動いたら 421 で断る(また 403 になるため)。
const ALLOWED = /^https:\/\/www\.oddspark\.com\/loto\/JResultList\.do\?kaisaiBi=\d{8}$/;

function role(req: Request): string {
  try {
    const tok = (req.headers.get('authorization') ?? '').replace(/^Bearer\s+/i, '');
    const p = tok.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(p + '='.repeat((4 - p.length % 4) % 4))).role ?? '';
  } catch { return ''; }
}
const b64 = (u: Uint8Array) => { let s = ''; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000)); return btoa(s); };
const json = (o: unknown, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json' } });

Deno.serve(async (req) => {
  const region = Deno.env.get('SB_REGION') ?? '?';
  if (role(req) !== 'service_role') return json({ error: 'service_role only' }, 401);
  if (region !== 'ap-northeast-1') return json({ error: `region ${region} (x-region: ap-northeast-1 を付ける)` }, 421);
  let q: { url?: string };
  try { q = await req.json(); } catch { return json({ error: 'bad json' }, 400); }
  if (!q.url || !ALLOWED.test(q.url)) return json({ error: 'url not allowed' }, 400);
  try {
    const r = await fetch(q.url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    const body = new Uint8Array(await r.arrayBuffer());
    return json({ status: r.status, body_b64: b64(body), region });
  } catch (e) {
    return json({ error: String(e) }, 502);
  }
});
