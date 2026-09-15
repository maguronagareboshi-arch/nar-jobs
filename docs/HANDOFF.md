commit: 枝 s179-paper= fd894a6(便・読み取りの関数・テスト・README)の上に yml だけ直す commit を 1 つ(⛔push なし)= .github/workflows/paper-first3f.yml の timeout-minutes 20→120 と、install の段の前に「system libs」の段(sudo apt-get install -y libgl1)
検品: fd894a6 は検品役の検品で 秘匿・ログ・3R 61 行の答え合わせ 合格。この commit は yml の 2 か所だけ= 手順名に「: 」なし(grep で確認)・差分と commit 文の禁止語 0 件・git diff --check 通過・yml は YAML として読める
通信: +0(便の中身は fd894a6 のまま。apt の取得が 1 回増えるだけ)
回帰: 他のファイルは触っていない(cloud/・tests/・README・他の便は fd894a6 のまま)
変えた点: ①timeout 120 分= PDF は開催の約 5 日前に 3 日分 10〜15 本まとめて出る・1 本 約 3 分で 45 分前後。20 分で切られると表に書く前に終わり、翌日も同じ本数を取り直していた ②libgl1= rapidocr-onnxruntime が使う opencv-python の import に libGL が要る(ubuntu-latest に無いと落ちる)
⚠: 便の上ではまだ流していない= 初回の dispatch で apt と pip の所要時間・1 本あたりの分数を実測する(公開リポなので Actions の分数は無料枠に入らない見込み)。cloud/paper_first3f.py が設計の 250 行を 43 行超えた件は fd894a6 のまま
次: ユーザーが Secrets(PAPER_BASE_URL)を確認して push → dispatch 1 回(dates=2026-09-13)→ REST で 9/13 の行数と 1 頭の値を紙面と目視
