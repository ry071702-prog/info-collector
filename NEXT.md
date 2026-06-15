# 情報収集 (info-collector) — 進捗ボード
<!-- statusline / session-start / /board がこのファイルを読みます。自由に編集してOK。 -->

## 状態
完了  <!-- 進行中 | レビュー待ち | 完了 | 停滞 のいずれか -->

## いま
新聞風ページの本実装+pro画像生成を main にマージ済み (PR #39, #40)。pro で実生成し日本語の正確さを確認済み。次回 process_digest から毎日1枚 pro で自動生成される。

## 次にやること
- [x] 本番生成画像の品質を最終確認 (2026-06-12 / 06-13 を目視: 日本語の文字化け・崩れ字ゼロ、紙面レイアウト良好 → pro 本番品質 合格)
- [ ] 数日運用してコスト実績を確認 (想定: pro 月¥600〜1,100。06-08〜06-13 の6日分 稼働中)
- [x] GitHub Actions secret GEMINI_API_KEY は 2026-06-14 04:18Z 更新済み (新鍵) を確認 → 分類&画像生成は新鍵で稼働
- [ ] Cloudflare Pages secret GEMINI_API_KEY (production = info-collector-a5y.pages.dev) = /collection 保存→AI要約用。
      実態調査 (2026-06-15): /api/collection は公開GETだが saved_items は **0件** → 劣化判定する保存物が無い。save は passcode 必須 (SAVE_PASSCODE) で私からは実テスト不可。
      失敗モードは graceful (gemini.ts:80-96): 旧鍵でも保存は 201 成功し summary/tags が空になるだけ。ハードエラーではない & 現状 0件なので実害なし。
      対処: アプリで1件テスト保存 → summary/tags が付けば鍵OK。空なら新鍵で再設定 (wrangler 認証済、反映に redeploy 要の場合あり):
      echo "<新鍵>" | npx --prefix ~/情報収集/site wrangler pages secret put GEMINI_API_KEY --project-name info-collector
- [ ] (任意) 記事2/記事3 が「続報を待つトピック」プレースホルダのまま (実コンテンツは記事1のみ) — digest 側で副記事を埋めるか検討

## 完了 (直近)
- [x] 新聞画像を pro (gemini-3-pro-image-preview) で生成成功・品質確認 → 本番既定に採用 (PR #40)。flash-image は日本語が崩れたため不採用
- [x] 新聞風ページを本実装に昇格: process_digest.yml に画像生成ステップ追加 (当日分があればスキップ=1日1枚)、site/public/newspaper-img を commit 対象化、google-genai 依存追加、[date].astro を紙面レイアウトへ刷新
- [x] watchlist 更新フロー確認: ローカル CSV (config/watchlist.csv) が canonical、SYNC_SHEETS_FROM_CSV=true で GSheets へ上書き同期。CSV 編集→commit→Actions 実行で反映、GSheets 直編集は上書きされる
- [x] 1日1枚の新聞風ページを追加 (デモ版)
