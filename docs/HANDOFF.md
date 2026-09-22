commit: 7dd7e0e(枝 s224s2・1 コミット・push なし)
検品: `--from 2025-09 --to 2026-09 --dry` を公開の読み取り鍵で実測= 所要 27 秒・枡 471(20 走未満 30 枡= 6.4%)・場×距離帯 40・51,554 バイト(200KB 未満なので鍵は 1 行のまま)。答え合わせ= kochi|1400|逃げ|速い を**サーバ側で脚質・ペース・着順を絞る別の道**で数え直し n=363 top3=143 が完全一致。`py -3.12 -m unittest discover -s tests -p "test_pace_lift*.py"` 9 本 OK。
通信: +0(本番 DB への書きは無し。読みは REST を月ごと 4 本 × 13 か月)
回帰: 追加だけ= 既存の便・表・yml は 1 行も触っていない
変えた点: `cloud/pace_lift.py`= 過去 12 か月を月ごとに REST で読み**手元で**数えて nar_meta `pace_lift:v1` に upsert(場 × 距離帯 200m 刻み × 脚質 4 × ペース 3・分母は「走った」= 着順あり/競走中止/失格・1200m 未満と表に無い場とペース行の無いレースは入れない・20 走未満は rate と lift を null・base_rate= その場×距離帯の全体・200KB 超なら場ごとの鍵+索引 1 行・`--out` で JSON にも書ける)。`.github/workflows/pace-lift.yml`= 手で回す(dry/apply・from/to)+ 毎月 2 日 04:40 JST。`tests/test_pace_lift.py`。
⚠: 列名は `pace`(`pace_word` は cloud/tenkai.py の**関数名**で列ではない)。距離帯の丸めは**半分は上**(1300→1400)= Python の round() は偶数丸めで画面の Math.round とずれるため使っていない。
要判断: 本番へ書くのはユーザー(pace-lift.yml を mode=apply で 1 回・以後は月 1 の cron)。書くまで画面(統合ビューア 枝 s224s2)は「この表はまだ作られていません」と出る。
