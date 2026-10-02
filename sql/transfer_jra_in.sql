-- §移籍まとめ D1(2026-09-30)。⛔本番への適用は本体が手動モードで(下請けは流していない)。
-- ① 交流の除外に使う列: 競馬ブック公開頁 p.keibabook.co.jp/db/uma/{id} の「中央在籍 N戦」(表示なし= 0)。
--    書き手は nar-jobs cloud/kb/fetch_jra_career.py(kb-daily.yml の最後の手順で毎日 --pending 300 --push)。
--    null= まだ見ていない(cloud/horse_changes.py は null の馬を除外しない)。
alter table nar_jra_horses add column if not exists jra_career_runs integer;
comment on column nar_jra_horses.jra_career_runs is
  '競馬ブック公開頁の「中央在籍 N戦」。0= 地方所属のまま中央の交流に出ただけ(jra_in に数えない)。null= 未取得';

-- ② 2 重の片付け(cloud/horse_changes.py の jra_in を --apply で遡り(--since 2025-10-01)流した後に 1 回だけ)。
--    旧 transfer_in の from_value='JRA'(中央所属で地方の交流を走った馬の転入)は jra_in と同じ馬・同じ日に必ず出る
--    (9/30 ドライラン: 1 年 491 行 = 491 行とも jra_in と一致)。jra_in に寄せ、transfer_in 側を消す。
--    これ以降は horse_changes.py の DETECT_SQL が p_area='JRA' を transfer_in にしない。
delete from nar_horse_changes t
where t.kind = 'transfer_in' and t.from_value = 'JRA'
  and exists (select 1 from nar_horse_changes j
               where j.kind = 'jra_in' and j.horse_name = t.horse_name
                 and coalesce(j.birth_date, date '0001-01-01') = coalesce(t.birth_date, date '0001-01-01')
                 and j.race_date = t.race_date);
