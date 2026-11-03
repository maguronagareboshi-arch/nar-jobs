-- 2026-11-03 南関公式(nankankeiba.com)が 10/31 ごろから GitHub ランナー(国外)を 403 で拒む(朝の便で 1 回 約 480 件)。
-- 本番 DB(東京)の pg_net からは 200(§195d 大井と同じ形)。便は RPC で「取って」と頼み、返事を base64 で受け取る(cloud/jp_fetch.py)。
-- 取れる先は南関公式だけ(正規表現で固定)・呼べるのは service_role だけ。中身は Shift_JIS のまま(textsend で元のバイト)。
create or replace function public.jp_fetch_start(p_urls text[]) returns bigint[]
language plpgsql security definer set search_path = public, net as $$
declare u text; ids bigint[] := '{}';
begin
  if coalesce(array_length(p_urls, 1), 0) > 20 then
    raise exception 'jp_fetch_start: 1 回 20 件まで';
  end if;
  foreach u in array p_urls loop
    if u !~ '^https://www\.nankankeiba\.com/[A-Za-z0-9_./?=&%-]*$' then
      raise exception 'jp_fetch_start: 取れない先 %', u;
    end if;
    ids := ids || net.http_get(u,
      '{"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36","Accept-Language":"ja"}'::jsonb,
      '{}'::jsonb, 30000);
  end loop;
  return ids;
end $$;

create or replace function public.jp_fetch_result(p_ids bigint[])
returns table (id bigint, status int, err text, body_b64 text)
language sql security definer set search_path = public, net as $$
  select h.id, h.status_code, h.error_msg, encode(textsend(h.content), 'base64')
    from net._http_response h
   where h.id = any(p_ids)
$$;

revoke all on function public.jp_fetch_start(text[]) from public, anon, authenticated;
revoke all on function public.jp_fetch_result(bigint[]) from public, anon, authenticated;
grant execute on function public.jp_fetch_start(text[]) to service_role;
grant execute on function public.jp_fetch_result(bigint[]) to service_role;
