-- ばんえい 第 3 版(model='banei-3')の便の準備(2026-10-28)。⛔このファイルは「作っただけ」= 流すのはユーザー。
-- ① 表 nar_kb_banei(競馬ブック帯広の成績の区間タイム・通過順・発走時刻。書くのは便 banei-v3 の bn_kb.py だけ)
-- ② pg_cron の起こし手 3 本(07:20 fit / 11:40 loop / 17:15 loop・JST)。鍵は Vault の github_dispatch_token(監査 #27 と同じ参照)。
--    ⛔鍵の値はこのファイルに書かない。② は試しの便が通った後に流す(①だけ先に流してよい)。
-- 流し方: Supabase の SQL Editor に ① を貼って Run → 試しの便の後に ② を貼って Run → ③ で確かめる。冪等(2 回流しても同じ)。

-- ① 表 ------------------------------------------------------------------
create table if not exists public.nar_kb_banei (
  race_date   date    not null,
  race_no     integer not null,
  umaban      integer not null,
  horse_name  text,
  finish      numeric,
  finish_note text,
  time_sec    numeric,
  seg_front   numeric,
  seg_obst    numeric,
  seg_back    numeric,
  pass1       numeric,
  pass2       numeric,
  pass3       numeric,
  hasso_time  text,
  kb_race_id  text,
  fetched_at  timestamptz not null default now(),
  primary key (race_date, race_no, umaban)
);
alter table public.nar_kb_banei enable row level security;   -- 読み書きは便の管理用の鍵だけ(公開の鍵には見せない)
comment on table public.nar_kb_banei is 'ばんえい 第 3 版: 競馬ブック帯広(場 58)の成績の区間タイム・通過順・発走時刻(2026-10-27〜・それより前は暗号化リリースの固めた表)';

-- ② 起こし手(UTC で書く: 22:20 = 07:20 JST・02:40 = 11:40 JST・08:15 = 17:15 JST) -------------------------
do $$
declare
  j record;
begin
  for j in select * from (values
      ('nar-banei3-fit',    '20 22 * * *', '{"mode":"fit","write":"yes"}'),
      ('nar-banei3-loop-a', '40 2 * * *',  '{"mode":"loop","write":"yes","until":"17:10"}'),
      ('nar-banei3-loop-b', '15 8 * * *',  '{"mode":"loop","write":"yes","until":"21:00"}')) as t(name, sched, inputs)
  loop
    perform cron.schedule(j.name, j.sched, format($c$
      select net.http_post(
        url := 'https://api.github.com/repos/maguronagareboshi-arch/nar-jobs/actions/workflows/banei-v3.yml/dispatches',
        headers := jsonb_build_object(
          'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
          'Accept', 'application/vnd.github+json',
          'X-GitHub-Api-Version', '2022-11-28',
          'User-Agent', 'nar-pg-cron'),
        body := jsonb_build_object('ref', 'master', 'inputs', %L::jsonb))
    $c$, j.inputs));
  end loop;
end $$;

-- ③ 確かめ(読むだけ)。期待: 表 1・起こし手 3 本(active = true)
select (select count(*) from information_schema.tables where table_schema = 'public' and table_name = 'nar_kb_banei') as kb_table,
       (select count(*) from cron.job where jobname like 'nar-banei3-%' and active) as cron_jobs;
-- 次の日の 07:20 JST の 1〜2 分後: GitHub が 204 を返していれば起きている(401/403/404 は鍵か権限の誤り)
-- select id, created, status_code from net._http_response where created > now() - interval '10 minutes' order by id desc limit 5;
