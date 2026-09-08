# nar-jobs

地方競馬ウォッチ(https://nar.yukochi.com/)の集計便(GitHub Actions)を置くリポジトリ。

- 画面のコードは別リポジトリ。ここには定期実行の便と、便が使う集計スクリプト・SQL だけを置く。
- 鍵は Actions secrets のみ(コードに書かない)。ここに入っているキーは公開前提の anon キーだけ。
- 便の一覧は `.github/workflows/` を参照。
