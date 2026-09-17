-- §195d(2026-09-17・Fable・本番適用済み)。大井公式の「出来事」RSS は日本国外からの取得を拒む
-- (GitHub ランナー・当サイト Pages 中継(海外 PoP)・単体 Worker= 全部 403)。本番 DB(東京)の pg_net からは 200。
-- → 毎朝 06:00 JST に DB 自身が 8 頁を取り、表 nar_fetch_raw に置く。便(cloud/health_org_ooi.py §195c)は表を読むだけ。
alter table public.nar_fetch_raw add column if not exists req_id bigint;
create or replace function private.ooi_feed_fetch() returns integer
language plpgsql security definer set search_path = public, net as $$
declare n int; rid bigint; u text;
begin
  for n in 1..8 loop
    u := 'https://www.tokyocitykeiba.com/news/feed/?s=%E5%87%BA%E6%9D%A5%E4%BA%8B&paged=' || n;
    rid := net.http_get(u, '{"User-Agent":"nar-jobs-health/1.0","Accept-Language":"ja"}'::jsonb, '{}'::jsonb, 30000);
    insert into public.nar_fetch_raw (source, key, url, status, req_id) values ('ooi_official', 'paged=' || n, u, 0, rid)
      on conflict (source, key) do update set url = excluded.url, req_id = excluded.req_id;
    perform pg_sleep(3);                       -- 先方に優しく 3 秒
  end loop;
  return 8;
end $$;
create or replace function private.ooi_feed_harvest() returns integer
language plpgsql security definer set search_path = public, net as $$
declare c int;
begin
  update public.nar_fetch_raw r
     set status = h.status_code, content_type = h.headers->>'content-type', body = h.content, fetched_at = h.created
    from net._http_response h
   where r.req_id is not null and h.id = r.req_id and h.created > now() - interval '3 hours';
  get diagnostics c = row_count;
  return c;
end $$;
revoke all on function private.ooi_feed_fetch() from public, anon, authenticated;
revoke all on function private.ooi_feed_harvest() from public, anon, authenticated;
select cron.unschedule(jobid) from cron.job where jobname in ('nar-ooi-feed-fetch','nar-ooi-feed-harvest');
select cron.schedule('nar-ooi-feed-fetch',   '0 21 * * *', $$select private.ooi_feed_fetch()$$);   -- 06:00 JST
select cron.schedule('nar-ooi-feed-harvest', '5 21 * * *', $$select private.ooi_feed_harvest()$$); -- 06:05 JST
