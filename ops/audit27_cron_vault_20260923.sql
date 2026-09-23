-- 監査 #27: cron.job 14 本(nar-jobs 12・nar-odds-collector 2)の GitHub 鍵を平文から Vault 参照へ(2026-09-23 Opus 5.5)
-- 前提: ユーザーが新しい鍵(fine-grained・対象 nar-jobs と nar-odds-collector だけ・権限 Actions: Read and write だけ)を作り、
--       Supabase の Vault に名前 github_dispatch_token で保存済み(Dashboard の Vault 画面から。SQL 履歴に鍵を残さない)。
-- ⛔鍵の値はこのファイル・画面・ログに出さない。置き換えはサーバー内の regexp_replace だけで行い、古い鍵も表示しない。
-- 流し方: ①だけ流して期待どおりか見る → ②を流す → ③で確認 → ④で次の dispatch が 204 か見る → GitHub で古い鍵を無効に。

-- ① 事前確認(読むだけ)。期待: vault_rows=1・token_ok=true・jobs_with_literal=14・occurrences=14
select (select count(*) from vault.decrypted_secrets where name = 'github_dispatch_token') as vault_rows,
       (select length(decrypted_secret) >= 40 from vault.decrypted_secrets where name = 'github_dispatch_token') as token_ok,
       count(*) filter (where command ~ '''Bearer (ghp_|github_pat_)[A-Za-z0-9_]+''') as jobs_with_literal,
       sum((select count(*) from regexp_matches(command, '(ghp_|github_pat_)[A-Za-z0-9_]+', 'g'))) as occurrences
from cron.job;

-- ② 置き換え(条件がそろわなければ何も変えずに止まる)
do $$
declare
  n_vault int; n_lit int; n_occ int; r record;
begin
  select count(*) into n_vault from vault.decrypted_secrets
   where name = 'github_dispatch_token' and length(decrypted_secret) >= 40;
  select count(*) filter (where command ~ '''Bearer (ghp_|github_pat_)[A-Za-z0-9_]+'''),
         coalesce(sum((select count(*) from regexp_matches(command, '(ghp_|github_pat_)[A-Za-z0-9_]+', 'g'))), 0)
    into n_lit, n_occ from cron.job;
  if n_vault <> 1 or n_lit <> 14 or n_occ <> 14 then
    raise exception '中止: vault=% jobs=% occurrences=%(期待 1/14/14)', n_vault, n_lit, n_occ;
  end if;
  for r in select jobid, command from cron.job
            where command ~ '''Bearer (ghp_|github_pat_)[A-Za-z0-9_]+''' loop
    perform cron.alter_job(r.jobid, command := regexp_replace(r.command,
      '''Bearer (ghp_|github_pat_)[A-Za-z0-9_]+''',
      '''Bearer '' || (select decrypted_secret from vault.decrypted_secrets where name = ''github_dispatch_token'')',
      'g'));
  end loop;
end $$;

-- ③ 確認(読むだけ)。期待: plain_left=0・vault_ref=14
select count(*) filter (where command ~ '(ghp_|github_pat_)[A-Za-z0-9_]+') as plain_left,
       count(*) filter (where command like '%vault.decrypted_secrets where name = ''github_dispatch_token''%') as vault_ref
from cron.job;

-- ④ 動いたかの確認(読むだけ・②の 30 分後)。GitHub が 204 を返していれば成功(401/403/404 は鍵か権限の誤り)
select r.id, r.created, r.status_code
from net._http_response r
where r.created > now() - interval '40 minutes'
order by r.id desc limit 20;
