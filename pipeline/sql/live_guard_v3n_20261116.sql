-- 2026-11-16 他場版の朝の予想の抜けを見張りが自動で埋める(nankan-ai-v3 の会話 11/16)
-- 11/16 06:42 の nar-ai-v3n が予想の段の途中で GitHub の機械ごと落ち(The hosted runner lost communication・記録なし)、
--   09:15 の予備(schedule)は 11/6 から毎日 15:00〜16:25 にしか動いていない = 水沢・金沢の朝の予想が 12:03 の手の回し直しまで 0 件。
-- 足したこと: private.nar_live_guard に「他場版の朝の行」の見張りを 1 つ足す(前からの ai_last・v3_gap_live の見張りは 1 字も変えない)。
--   08:30 JST から、他場版の場(直近 30 日に v3n-1 の朝の行がある場)の今日のレースで、発走 20 分より先なのに
--   朝の行が無いレースが 1 つでもあれば nar-ai-v3n.yml を write=yes で起こす(date は空 = 便の側で JST 今日)。
--   ・材料表の便(ai_feat)が今日まだ済んでいなければ 09:30 までは待つ(09:30 を過ぎたら起こす・便の側が自分の表で作る)
--   ・ai_v3n の生存が 20 分より新しければ起こさない(書ける分は書いた直後)・同じ見張りは 30 分あけ・1 日 3 回まで
--   ・朝の行は凍結なので、二重に動いても書くのは抜けた行だけ(便は concurrency で並ぶ)
--   ・入力は write だけ(nar-ai-v3n.yml にある入力だけ = 422 にならない)
-- 過去 30 日(10/17〜11/15)の朝の行の書き終わりは一番遅くて 08:07 = 08:30 の線で普段の日に起こすことは無い。
-- 時計: cron の nar-live-guard を 08:00 JST(23 UTC)からに広げる。前からの見張りは 09:40・10:45 からなので変わらない。
-- 試し(何もしない・決めたことだけ返す): select private.nar_live_guard(now(), true);
--   例 今日の朝: select private.nar_live_guard('2026-11-16 08:30+09', true);  → v3n_morning を回し直す(抜け 24 R)
-- 戻す: pipeline/sql/live_guard_20261030.sql の関数を流し直し、select cron.alter_job(31, schedule := '*/5 0-12 * * *');

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
  miss_n  int;
  miss_t  text;
  feat_ok timestamptz;
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
       and r.track not like '帯広%'
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

  -- 2026-11-16 他場版の朝の行(nar-ai-v3n)の抜け
  if hm >= 830 then
    select count(*), string_agg(distinct r.track, '・')
      into miss_n, miss_t
      from public.nar_races r
     where r.race_date = d
       and coalesce(btrim(r.cancelled::text), '') = ''
       and r.post_time ~ '^\d{4}$'
       and r.track in (select distinct m.track from public.nar_ai_marks m
                        where m.model = 'v3n-1' and m.timing = 'morning' and m.race_date between d - 30 and d - 1)
       and d + make_time(substr(r.post_time, 1, 2)::int, substr(r.post_time, 3, 2)::int, 0) > jst + interval '20 minutes'
       and not exists (select 1 from public.nar_ai_marks m
                        where m.model = 'v3n-1' and m.timing = 'morning'
                          and m.track = r.track and m.race_date = r.race_date and m.race_no = r.race_no
                          and m.computed_at <= p_now);   -- 試しで過去の時刻を入れたときのため(本番では常に真)
    if miss_n > 0 then
      lo      := (select h.last_ok from public.nar_job_heartbeat h where h.job = 'ai_v3n');
      feat_ok := (select h.last_ok from public.nar_job_heartbeat h where h.job = 'ai_feat');
      select count(*) filter (where g.at > p_now - interval '30 minutes'),
             count(*) filter (where (g.at at time zone 'Asia/Tokyo')::date = d)
        into recent, today_n
        from private.nar_live_guard_log g
       where g.job = 'v3n_morning' and g.at > p_now - interval '1 day' and g.at <= p_now;
      if not (lo is not null and lo > p_now - interval '20 minutes' and lo <= p_now)
         and recent = 0 and today_n < 3
         and ((feat_ok is not null and feat_ok <= p_now and (feat_ok at time zone 'Asia/Tokyo')::date = d) or hm >= 930) then
        msg := msg || format('v3n_morning を回し直す(朝の行の抜け %s R・%s・最後の生存 %s)・', miss_n, miss_t,
                             coalesce(to_char(lo at time zone 'Asia/Tokyo', 'MM-DD HH24:MI'), 'なし'));
        if not p_dry then
          select net.http_post(
            url := 'https://api.github.com/repos/maguronagareboshi-arch/nar-jobs/actions/workflows/nar-ai-v3n.yml/dispatches',
            headers := jsonb_build_object('Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
                                          'Accept', 'application/vnd.github+json', 'User-Agent', 'nar-dispatcher'),
            body := jsonb_build_object('ref', 'master', 'inputs', jsonb_build_object('write', 'yes'))) into rid;
          insert into private.nar_live_guard_log (at, job, part, last_ok, req_id) values (p_now, 'v3n_morning', null, lo, rid);
        end if;
      end if;
    end if;
  end if;

  if msg <> '' and not p_dry then
    perform public.nar_beat('live_guard', true, msg);
  end if;
  return nullif(msg, '');
end
$function$;

select cron.alter_job(31, schedule := '*/5 23,0-12 * * *');
