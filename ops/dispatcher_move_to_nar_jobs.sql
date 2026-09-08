-- ops: pg_cron の起こし手が叩く GitHub API の宛先を nar-viewer から nar-jobs へ差し替える(#529)
--
-- ⛔このファイルは「作っただけ」= まだ本番で流していない。流すのはユーザーの判断で。
-- ⛔PAT の値は一切書かない。既存 job の command 文字列の中にある PAT はそのまま残り、
--   置き換えるのは URL の '/nar-viewer/' → '/nar-jobs/' の 1 か所だけ。
--
-- 前提(⛔流す前に確認すること)
--   1. 公開リポ maguronagareboshi-arch/nar-jobs が作られ、7 本の yml が master に入っていること
--      (workflow_dispatch は「既定枝に yml がある」ことが条件)。
--   2. Fine-grained PAT『nar-dispatch』の対象リポジトリに **nar-jobs を足す**こと
--      (Actions: Read and write)。足さないと 404 が返って便が起きない。
--   3. nar-odds-collector を叩く job(nar-odds-dispatch)は**触らない**= 別リポのまま。
--
-- 流し方: psql で -f このファイル(ON_ERROR_STOP=1)。冪等(2 回流しても同じ)。

\set ON_ERROR_STOP on

-- 変更前の確認(URL だけ見る。PAT は出さないので regexp で URL を抜く)
select jobid, jobname, schedule, active,
       substring(command from 'https://api\.github\.com/repos/[^'']+') as target_url
  from cron.job
 where jobname in (
   'nar-dispatch',
   'nar-monthly-dispatch',
   'nar-ai-feat-dispatch',
   'nar-health-dispatch',
   'nar-auction-daily',
   'nar-auction-rakuten-list',
   'nar-auction-rakuten-close-a',
   'nar-auction-rakuten-close-b',
   'nar-auction-sat-weekly',
   'nar-auction-items-weekly')
 order by jobname;

-- 差し替え本体(cron.alter_job で command だけ書き換える。schedule / active は触らない)
do $$
declare
  r record;
  n int := 0;
begin
  for r in
    select jobid, jobname, command
      from cron.job
     where jobname in (
       'nar-dispatch',
       'nar-monthly-dispatch',
       'nar-ai-feat-dispatch',
       'nar-health-dispatch',
       'nar-auction-daily',
       'nar-auction-rakuten-list',
       'nar-auction-rakuten-close-a',
       'nar-auction-rakuten-close-b',
       'nar-auction-sat-weekly',
       'nar-auction-items-weekly')
       and command like '%/nar-viewer/%'
  loop
    perform cron.alter_job(
      job_id  := r.jobid,
      command := replace(r.command, '/nar-viewer/', '/nar-jobs/'));
    n := n + 1;
    raise notice 'moved: % (jobid %)', r.jobname, r.jobid;
  end loop;
  raise notice '差し替えた job = % 本', n;
end $$;

-- 変更後の確認(⛔ここが全部 /nar-jobs/ になっていること。odds は別リポのままで正しい)
select jobid, jobname, schedule, active,
       substring(command from 'https://api\.github\.com/repos/[^'']+') as target_url
  from cron.job
 order by jobname;

-- 戻し方(必要なら): 上の do ブロックの replace を
--   replace(r.command, '/nar-jobs/', '/nar-viewer/') にして、where も '%/nar-jobs/%' にして流す。
