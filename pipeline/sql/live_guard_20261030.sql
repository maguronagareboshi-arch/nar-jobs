-- 2026-10-30 直前の便の自動の回し直し(nankan-ai-v3 out/incident_20261029_last.md の案 A)
-- 10/29 12:29 JST、nar-ai-last(他場の直前)と v3-gap-live(南関の直前)が GitHub 側の内部エラーで消え、
--   fail も書けないまま午後の便まで 2.5 時間抜けた(15 R)。
-- 5 分おきに nar_job_heartbeat の生存(ai_last = 1 周ごと・v3_gap_live = 5 分ごと)を見て、開催中に、
--   まだ発走前(15 分より先)のレースがあるのに生存が 15 分より古ければ、その便を guard=yes で起こす。
--   起こされた便は入口で同じ便が動いていないかを見る(ops/live_guard_check.sh)= 生きていれば何もしない。
-- 見る時間(JST)と引き継ぎの時間は cloud/live_watch.py の LIVE と同じ。変えるときは両方を直す。
--   ai_last 09:40〜(朝の便 09:08 起動)・引き継ぎ 14:50〜15:35(朝の便は 14:55 まで・午後の便 15:08 起動)
--   v3_gap_live 10:45〜(10:15 起動)・引き継ぎ 15:45〜16:20(午後 15:50 起動・朝は 16:05 まで)・15:45 より前は am、後は pm を起こす
-- 同じ便は 20 分あけ、1 日 4 回まで。回したら nar_beat('live_guard') に書く = 見張り(nar-watchdog ⑧)が 1 日 1 通知らせる。
-- ⛔nar-jobs に guard の入力を足した版(ops/live_guard_check.sh のある master)を push してから流す。
--   先に流すと GitHub が知らない入力(guard)として起動を断る(422)。
-- 試し(何もしない・決めたことだけ返す): select private.nar_live_guard(now(), true);
-- 止める: select cron.unschedule('nar-live-guard');

create table if not exists private.nar_live_guard_log (
  id      bigserial primary key,
  at      timestamptz not null default now(),
  job     text not null,
  part    text,
  last_ok timestamptz,
  req_id  bigint
);

create or replace function private.nar_live_guard(p_now timestamptz default now(), p_dry boolean default false)
returns text
language plpgsql
security definer
set search_path to 'public', 'net'
as $function$
declare
  jst     timestamp := p_now at time zone 'Asia/Tokyo';
  d       date := (p_now at time zone 'Asia/Tokyo')::date;
  hm      int := extract(hour from (p_now at time zone 'Asia/Tokyo'))::int * 100 + extract(minute from (p_now at time zone 'Asia/Tokyo'))::int;
  j       record;
  lo      timestamptz;
  left_n  int;
  recent  int;
  today_n int;
  part    text;
  rid     bigint;
  msg     text := '';
begin
  for j in select * from (values
      ('ai_last',     'nar-ai-last.yml', 940,  1450, 1535, false),
      ('v3_gap_live', 'v3-gap-live.yml', 1045, 1545, 1620, true)
    ) v(job, wf, h0, hf, ht, nankan)
  loop
    continue when hm < j.h0 or (hm >= j.hf and hm < j.ht);
    -- その便が受け持つ、まだ発走前のレース(取消・発走時刻の無いレース・帯広は数えない)
    select count(*) into left_n
      from public.nar_races r
     where r.race_date = d
       and coalesce(btrim(r.cancelled::text), '') = ''
       and r.post_time ~ '^\d{4}$'
       and r.track <> '帯広'
       and (r.track in ('大井', '川崎', '船橋', '浦和')) = j.nankan
       and d + make_time(substr(r.post_time, 1, 2)::int, substr(r.post_time, 3, 2)::int, 0) > jst + interval '15 minutes';
    continue when left_n = 0;
    lo := (select h.last_ok from public.nar_job_heartbeat h where h.job = j.job);
    continue when lo is not null and lo > p_now - interval '15 minutes';
    select count(*) filter (where g.at > p_now - interval '20 minutes'),
           count(*) filter (where (g.at at time zone 'Asia/Tokyo')::date = d)
      into recent, today_n
      from private.nar_live_guard_log g
     where g.job = j.job and g.at > p_now - interval '1 day' and g.at <= p_now;
    continue when recent > 0 or today_n >= 4;
    part := case when j.nankan then case when hm < 1545 then 'am' else 'pm' end end;
    msg := msg || format('%s%s を回し直す(最後の生存 %s・発走前 %s R)・', j.job, coalesce(' ' || part, ''),
                         coalesce(to_char(lo at time zone 'Asia/Tokyo', 'MM-DD HH24:MI'), 'なし'), left_n);
    continue when p_dry;
    select net.http_post(
      url := 'https://api.github.com/repos/maguronagareboshi-arch/nar-jobs/actions/workflows/' || j.wf || '/dispatches',
      headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
                                    'Accept', 'application/vnd.github+json', 'User-Agent', 'nar-dispatcher'),
      body := jsonb_build_object('ref', 'master', 'inputs',
                case when j.nankan then jsonb_build_object('part', part, 'write', 'yes', 'guard', 'yes')
                     else jsonb_build_object('write', 'yes', 'once', 'no', 'guard', 'yes') end)) into rid;
    insert into private.nar_live_guard_log (at, job, part, last_ok, req_id) values (p_now, j.job, part, lo, rid);
  end loop;
  if msg <> '' and not p_dry then
    perform public.nar_beat('live_guard', true, msg);
  end if;
  return nullif(msg, '');
end
$function$;

revoke all on function private.nar_live_guard(timestamptz, boolean) from public;

-- 5 分おき・JST 09:00〜21:55(UTC 0〜12 時)。同じ名前なら差し替わる
select cron.schedule('nar-live-guard', '*/5 0-12 * * *', $$select private.nar_live_guard()$$);
