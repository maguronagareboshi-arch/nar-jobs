-- 5重勝の買い目のメール(便 w5-mail.yml)の起こし手(2026-11-22)。⛔このファイルは「作っただけ」= 流すのはユーザー。
-- 毎朝 09:30 JST(= 00:30 UTC)。鍵は Vault の github_dispatch_token(ops/banei_v3_setup.sql と同じ参照)。冪等。
-- 流し方: 試しの便(dry=yes と本送り)が通った後に、Supabase の SQL Editor に ① を貼って Run → ② で確かめる。

-- ① 起こし手
select cron.schedule('nar-w5-mail', '30 0 * * *', $c$
  select net.http_post(
    url := 'https://api.github.com/repos/maguronagareboshi-arch/nar-jobs/actions/workflows/w5-mail.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'nar-pg-cron'),
    body := jsonb_build_object('ref', 'master', 'inputs', '{}'::jsonb))
$c$);

-- ② 確かめ(読むだけ)。期待: 1
select count(*) as cron_jobs from cron.job where jobname = 'nar-w5-mail' and active;
-- 止めるとき: select cron.unschedule('nar-w5-mail');
