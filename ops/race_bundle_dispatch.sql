-- 2026-11-24 ログ削減 A: レースの置きファイルの便(.github/workflows/race-bundle.yml)を本番 DB の pg_cron から起こす。
-- ⛔本番 DB の変更= ユーザーが「手動」に切り替えて流す。時刻は UTC: 22:40= JST 7:40・03:10= JST 12:10(今日の分)・09:00= JST 18:00(翌日分)
-- 止める= select cron.unschedule('nar-race-bundle-am'); select cron.unschedule('nar-race-bundle-noon'); select cron.unschedule('nar-race-bundle-eve');
do $$
declare
  j record;
begin
  for j in select * from (values
    ('nar-race-bundle-am', '40 22 * * *', '{"which":"today"}'),
    ('nar-race-bundle-noon', '10 3 * * *', '{"which":"today"}'),
    ('nar-race-bundle-eve', '0 9 * * *', '{"which":"tomorrow"}')
  ) as t(name, sched, inputs) loop
    perform cron.schedule(j.name, j.sched, format($c$
      select net.http_post(
        url := 'https://api.github.com/repos/maguronagareboshi-arch/nar-jobs/actions/workflows/race-bundle.yml/dispatches',
        headers := jsonb_build_object(
          'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
          'Accept', 'application/vnd.github+json',
          'X-GitHub-Api-Version', '2022-11-28',
          'User-Agent', 'nar-pg-cron'),
        body := jsonb_build_object('ref', 'master', 'inputs', %L::jsonb))
    $c$, j.inputs));
  end loop;
end $$;
