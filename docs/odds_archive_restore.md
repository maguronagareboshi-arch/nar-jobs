# nar_odds_full_ticks の戻し方(監査 #28・cloud/odds_archive.py の書き出しから)

1. Storage の非公開バケット odds-archive から `nar_odds_full_ticks/YYYY/YYYY-MM-DD.jsonl.gz` を service key で落とし、`gzip -dc x.jsonl.gz > d.jsonl`。
2. psql で一時表へ: `create temp table t(j jsonb); \copy t(j) from 'd.jsonl' with (format csv, quote e'\x01', delimiter e'\x02')`
3. 戻す: `insert into public.nar_odds_full_ticks select (jsonb_populate_record(null::public.nar_odds_full_ticks, j)).* from t on conflict (id) do nothing;`
4. 確かめ: `select count(*) from public.nar_odds_full_ticks where race_date='YYYY-MM-DD'` が nar_meta `odds_archive:v1` のその日の rows と一致。
5. 戻した日は 60 日超なので次の朝便でまた書き出し対象になる= 既にあるファイルと sha256 照合して一致すれば再び消える(残したいなら便を止めてから)。
