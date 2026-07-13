# 情報収集 (info-collector) — 進捗ボード
<!-- statusline / session-start / /board がこのファイルを読みます。自由に編集してOK。 -->

## 状態
進行中  <!-- 進行中 | レビュー待ち | 完了 | 停滞 のいずれか -->

## いま
**分類が全滅していた致命バグを修正** (2026-07-13)。`google-genai` の `APIError` は `.code` が HTTPステータス(int) / `.status` は文字列なのに、`llm_client` が `.status >= 500` と数値比較していた → Gemini が 5xx/429 を返すとリトライ判定自体が TypeError で爆発し、classify がそれを握り潰して記事を捨てていた。7/12 は raw 626件 → **processed 0件**、なのに workflow は緑。詳細は Obsidian `Troubleshooting/2026-07-13-genai-apierror-status-code.md`。

## 次にやること
- [ ] 7/12 の raw 626件を掘り起こす (process_digest が当日/前日 UTC しか見ないので日付指定の口が要る)
- [ ] Codex レビューの Medium: 依存の lock 化 / 状態ファイルの atomic 書き込み / 出力先ごとの outbox (Notion・Sheets の一時障害が永久欠損になる)
- [x] 本番生成画像の品質を最終確認 (2026-06-12 / 06-13 を目視: 日本語の文字化け・崩れ字ゼロ、紙面レイアウト良好 → pro 本番品質 合格)
- [ ] 数日運用してコスト実績を確認 (想定: pro 月¥600〜1,100。06-08〜06-13 の6日分 稼働中)
- [x] GitHub Actions secret GEMINI_API_KEY は 2026-06-14 04:18Z 更新済み (新鍵) を確認 → 分類&画像生成は新鍵で稼働
- [ ] Cloudflare Pages secret GEMINI_API_KEY (production = info-collector-a5y.pages.dev) = /collection 保存→AI要約用。 #今週
      実態調査 (2026-06-15): /api/collection は公開GETだが saved_items は **0件** → 劣化判定する保存物が無い。save は passcode 必須 (SAVE_PASSCODE) で私からは実テスト不可。
      失敗モードは graceful (gemini.ts:80-96): 旧鍵でも保存は 201 成功し summary/tags が空になるだけ。ハードエラーではない & 現状 0件なので実害なし。
      対処: アプリで1件テスト保存 → summary/tags が付けば鍵OK。空なら新鍵で再設定 (wrangler 認証済、反映に redeploy 要の場合あり):
      echo "<新鍵>" | npx --prefix ~/情報収集/site wrangler pages secret put GEMINI_API_KEY --project-name info-collector
- [ ] (任意) 記事2/記事3 が「続報を待つトピック」プレースホルダのまま (実コンテンツは記事1のみ) — digest 側で副記事を埋めるか検討

## 完了 (直近)
- [x] **分類全滅バグを根治** (2026-07-13): 例外体系を google-genai に一本化 (api_core への詰め替え廃止)、429 を「日次枯渇=キー切替」と「一時レート制限=再試行」に分離。テスト 60→73 (バグ再注入で9件落ちることまで確認)
- [x] notify_priority の dedup 汚染を除去: `dedup.filter_new` の副作用で全記事キーが dedup_keys.json に登録され commit/push され、後続の process_digest が重複として捨てていた (通知の重複抑制は discord_sent.json の役割)
- [x] CI が失敗を隠す穴を塞ぐ: push リトライが3回失敗しても `sleep` 成功で exit 0 になっていた (11 workflow)、collector 全滅・「raw があるのに分類0件」を失敗扱いに
- [x] Cloudflare デプロイの耐障害性: timeout (job 20分/step 12分) + 3回リトライ + wrangler 4.110.0 固定 (7/3〜09 に 45分ハング×6回で失敗していた)
- [x] Python 3.12 固定 (`.python-version`)。venv が 3.9 だと twscrape が入らず `pip install -r` が丸ごと失敗する
- [x] 新聞画像を pro (gemini-3-pro-image-preview) で生成成功・品質確認 → 本番既定に採用 (PR #40)。flash-image は日本語が崩れたため不採用
- [x] 新聞風ページを本実装に昇格: process_digest.yml に画像生成ステップ追加 (当日分があればスキップ=1日1枚)、site/public/newspaper-img を commit 対象化、google-genai 依存追加、[date].astro を紙面レイアウトへ刷新
- [x] watchlist 更新フロー確認: ローカル CSV (config/watchlist.csv) が canonical、SYNC_SHEETS_FROM_CSV=true で GSheets へ上書き同期。CSV 編集→commit→Actions 実行で反映、GSheets 直編集は上書きされる
- [x] 1日1枚の新聞風ページを追加 (デモ版)
