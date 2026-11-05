-- ops: pg_cron から odds-drop-today.yml / odds-drop.yml を workflow_dispatch で起こす(2026-11-05・組の急落)
--
-- ⛔このファイルは「作っただけ」= まだ本番で流していない。流すのはユーザー(手動モード)の判断で。
-- ⛔PAT の値は一切書かない。既存の起こし手 'nar-dispatch'(nar-jobs を叩く)の command をひな形にして、
--   宛先の yml 名だけ差し替える= PAT・ヘッダ・本文(ref)はひな形のまま(dispatcher_move_to_nar_jobs.sql と同じ取り方)。
--
-- 予定(UTC で書く)
--   nar-odds-drop-today-dispatch : '5,35 2-12 * * *'  = JST 11:05〜21:35 の 30 分おき → odds-drop-today.yml
--   nar-odds-drop-dispatch       : '10 14 * * *'      = JST 23:10                       → odds-drop.yml
--
-- 前提(⛔流す前に確認すること)
--   1. 下の「ひな形の確認」で 'nar-dispatch' の URL が /nar-jobs/.../dispatches であること。
--   2. ひな形の本文が {"ref":"master"} だけ(inputs 無し)であること。inputs があるなら流さずに相談
--      (odds-drop の yml の inputs は dry_run だけ・知らない inputs を送ると 422)。
--   3. 両 yml の on.schedule と二重に起きる(concurrency で順に走るだけ・送信量は 2 倍)。
--      pg_cron を正にするなら yml の schedule を消す(別 commit)。
-- 流し方: psql で -f このファイル(ON_ERROR_STOP=1)。冪等(cron.schedule は同名を上書き)。

\set ON_ERROR_STOP on

-- ひな形の確認(PAT は出さない)。2026-11-05 nar-dispatch は本文に inputs mode=daily があり 422 になるので、本文が {"ref":"master"} だけの nar-watchdog-dispatch をひな形にする
select jobid, jobname, schedule, active,
       substring(command from 'https://api\.github\.com/repos/[^'']+') as target_url,
       substring(command from '\{[^{}]*"ref"[^{}]*\}') as body
  from cron.job
 where jobname = 'nar-watchdog-dispatch';

do $$
declare
  tpl text;
  wf  text := '/actions/workflows/[^/'']+/dispatches';
begin
  select command into tpl from cron.job where jobname = 'nar-watchdog-dispatch';
  if tpl is null then
    raise exception 'ひな形 nar-watchdog-dispatch が無い';
  end if;
  if tpl !~ '/nar-jobs/' or tpl !~ wf then
    raise exception 'ひな形の宛先が nar-jobs の workflow_dispatch でない';
  end if;

  perform cron.schedule('nar-odds-drop-today-dispatch', '5,35 2-12 * * *',
    regexp_replace(tpl, wf, '/actions/workflows/odds-drop-today.yml/dispatches'));
  perform cron.schedule('nar-odds-drop-dispatch', '10 14 * * *',
    regexp_replace(tpl, wf, '/actions/workflows/odds-drop.yml/dispatches'));
  raise notice '登録した: nar-odds-drop-today-dispatch / nar-odds-drop-dispatch';
end $$;

-- 登録後の確認(⛔URL が odds-drop-today.yml / odds-drop.yml になっていること)
select jobid, jobname, schedule, active,
       substring(command from 'https://api\.github\.com/repos/[^'']+') as target_url
  from cron.job
 where jobname in ('nar-watchdog-dispatch', 'nar-odds-drop-today-dispatch', 'nar-odds-drop-dispatch')
 order by jobname;

-- 戻し方: select cron.unschedule('nar-odds-drop-today-dispatch'); select cron.unschedule('nar-odds-drop-dispatch');
