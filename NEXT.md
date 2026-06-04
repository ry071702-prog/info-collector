# 情報収集 (info-collector) — 進捗ボード
<!-- statusline / session-start / /board がこのファイルを読みます。自由に編集してOK。 -->

## 状態
レビュー待ち  <!-- 進行中 | レビュー待ち | 完了 | 停滞 のいずれか -->

## いま
新聞風ページを本実装に昇格。process_digest に画像生成を組み込み済み。次回 digest 実行で初の自動生成画像が出る。

## 次にやること
- [ ] 次回 process_digest 実行後、自動生成画像の品質を確認 (日本語テキストの正確さ)
- [ ] 品質次第で repo variable NEWSPAPER_IMAGE_MODEL を gemini-3-pro-image-preview に切替検討

## 完了 (直近)
- [x] 新聞風ページを本実装に昇格: process_digest.yml に画像生成ステップ追加 (当日分があればスキップ=1日1枚)、site/public/newspaper-img を commit 対象化、google-genai 依存追加、[date].astro を紙面レイアウトへ刷新
- [x] watchlist 更新フロー確認: ローカル CSV (config/watchlist.csv) が canonical、SYNC_SHEETS_FROM_CSV=true で GSheets へ上書き同期。CSV 編集→commit→Actions 実行で反映、GSheets 直編集は上書きされる
- [x] 1日1枚の新聞風ページを追加 (デモ版)
