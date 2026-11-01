-- ばんえい 第 4 版(model='banei-3')の前日版の起こし手(2026-11-02)。⛔このファイルは「作っただけ」= 流すのはユーザー。
-- 23:30 JST(UTC 14:30)に date=next・mode=fit で banei-v3.yml を起こす = 次の日の模型を学び、朝の形の印(timing='morning'・凍結)を書く。
--   前の開催日の公式の結果は最終レース(〜20:45 発走)の後 22 時すぎに入る(2026-11-01 は 22:11)。
--   書けなかった夜(前の開催日の競馬ブックがまだ無い等)は、次の朝 07:20 の便(nar-banei3-fit)が今までどおり朝に書く。
--   次の日に帯広の開催が無ければ最初の段で終わる。
-- 戻すとき: select cron.unschedule('nar-banei3-eve');
select cron.schedule('nar-banei3-eve', '30 14 * * *', format($c$
  select net.http_post(
    url := 'https://api.github.com/repos/maguronagareboshi-arch/nar-jobs/actions/workflows/banei-v3.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'github_dispatch_token'),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'nar-pg-cron'),
    body := jsonb_build_object('ref', 'master', 'inputs', %L::jsonb))
$c$, '{"mode":"fit","write":"yes","date":"next"}'));

-- 確かめ(読むだけ)。期待: 起こし手 4 本(active = true)
select jobname, schedule, active from cron.job where jobname like 'nar-banei3-%' order by jobname;
