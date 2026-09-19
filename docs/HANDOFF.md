commit: fb68745 枝 s224e-first3f-survey(origin/master 437c6a6 の上)。設計 viewer-master docs/opus_s224e_first3f_estimate_survey_20260919.md= 下調べだけ。新規 tools/first3f_survey.py(読むだけ)。画面・yml・本番への書き込みなし・push なし
検品: 手元で py -3.12 で 1 回流した(本番 DB は REST の読むだけ・場ごと・30 日の窓・一意な並び)。実測= 高知 nar_own_runs・専門紙 nar_kb_runs・紙面 nar_paper_runs、走破タイム・上り3F= nar_runs、距離= nar_races
通信: 本番へは読むだけ(件数と所要は docs/notes_s224e.md の末尾)/書き込み 0 本
回帰: unittest discover 緑(既存のテストは触っていない)・画面と yml の差分なし
結論: 場×距離の中央値で補正した推定で、0.5 秒以内 80% 以上に届くのは 1400m 前後と一部の 1300m だけ。1600m 以上はどの場も届かない。表と件数は docs/notes_s224e.md(公開リポのため commit していない)
⚠: 1200m は推定でなく恒等式(前半 3F+上り 3F= 1200m)で、そのまま出せる。高知 1300m は計測撤退済みの距離で、値の出どころの確認が要る
要判断: notes_s224e.md(数字入り)を公開リポに commit するか・推定を出す場×距離を ✓ の組にするか、後ろ向きでも届く組に絞るか
