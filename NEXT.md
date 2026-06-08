# 情報収集 (info-collector) — 進捗ボード
<!-- statusline / session-start / /board がこのファイルを読みます。自由に編集してOK。 -->

## 状態
完了  <!-- 進行中 | レビュー待ち | 完了 | 停滞 のいずれか -->

## いま
新聞風ページの本実装+pro画像生成を main にマージ済み (PR #39, #40)。pro で実生成し日本語の正確さを確認済み。次回 process_digest から毎日1枚 pro で自動生成される。

## 次にやること
- [ ] 次回 process_digest 自動実行 (JST 07:00/19:00) で本番生成された画像の品質を最終確認
- [ ] 数日運用してコスト実績を確認 (想定: pro 月¥600〜1,100)

## 完了 (直近)
- [x] 新聞画像を pro (gemini-3-pro-image-preview) で生成成功・品質確認 → 本番既定に採用 (PR #40)。flash-image は日本語が崩れたため不採用
- [x] 新聞風ページを本実装に昇格: process_digest.yml に画像生成ステップ追加 (当日分があればスキップ=1日1枚)、site/public/newspaper-img を commit 対象化、google-genai 依存追加、[date].astro を紙面レイアウトへ刷新
- [x] watchlist 更新フロー確認: ローカル CSV (config/watchlist.csv) が canonical、SYNC_SHEETS_FROM_CSV=true で GSheets へ上書き同期。CSV 編集→commit→Actions 実行で反映、GSheets 直編集は上書きされる
- [x] 1日1枚の新聞風ページを追加 (デモ版)
