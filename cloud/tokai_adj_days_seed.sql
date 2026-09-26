-- §287 笠松の見直しの日を nar_meta 'tokai_adj_days' に先に入れておく(任意・本番には未実行)。
-- 入れなくても便(tokai_demotion.py --apply)が一覧から特定して自分で書く。9/25 は第11回の一覧で確かめてから便が入れる。
-- 12/31・3/20・6/26 は一覧から特定した日(ks_detect_adj・BACKTEST-demotion-tokai-20260926.md と一致)。
insert into nar_meta (key, value, updated_at) values (
  'tokai_adj_days',
  '{"KS": {"2025-12": "2025-12-31", "2026-03": "2026-03-20", "2026-06": "2026-06-26"},
    "src": {"2025-12": "一覧", "2026-03": "一覧", "2026-06": "一覧"}}'::jsonb,
  now())
on conflict (key) do nothing;
