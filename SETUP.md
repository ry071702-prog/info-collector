# セットアップガイド

ゼロから本番稼働まで。順番通りに進めれば30〜60分で動き始めます。

## チェックリスト

- [x] 1. GitHubリポジトリ作成
- [ ] 2. Google Gemini APIキー取得（無料・カード不要）
- [ ] 3. X (Twitter) 捨てアカウント作成
- [ ] 4. Discord サーバー＆Webhook作成
- [ ] 5. Google Cloud サービスアカウント作成
- [ ] 6. Google Sheets作成・サービスアカウントに共有
- [ ] 7. Notion DB 2つ作成
- [ ] 8. Twitch アプリ登録
- [ ] 9. GitHub Secrets / Variables 設定
- [ ] 10. `Actions` タブで手動キック → 動作確認
- [ ] 11. cron が回り始めるのを待つ

---

## 1. GitHubリポジトリ作成

プライベートリポを推奨。

```bash
git init
git add .
git commit -m "initial scaffold"
git branch -M main
git remote add origin git@github.com:YOUR/info-collector.git
git push -u origin main
```

リポジトリ Settings → Actions → General → Workflow permissions を **Read and write permissions** に設定。

## 2. Google Gemini APIキー（無料）

完全無料で使えます。クレジットカード登録不要、課金事故も発生しません。

1. https://aistudio.google.com/apikey にアクセス（Googleアカウントでログイン）
2. 「Create API key」をクリック
3. 新規プロジェクトを作成 or 既存プロジェクトを選択
4. 表示された `AIzaSy...` で始まるキーをコピー
5. 後で `GEMINI_API_KEY` として GitHub Secrets に登録

**無料枠（このプロジェクトでの想定使用率）**

| モデル | 1日のリクエスト上限 | このプロジェクトの想定使用 |
|---|---|---|
| Gemini 2.0 Flash | 1,500回 | 〜30%（150〜450回程度） |
| Gemini 1.5 Pro | 50回 | 〜2%（週次・月次のみ） |

**注意点**
- 無料枠ではGoogleが入力データを学習に使う可能性があります（公開情報のみ扱うので個人的には問題なしと想定）
- 気になる場合は AI Studio から課金枠に切り替え可能（カード登録時に学習対象から外れる）
- このプロジェクトは無料枠前提で設計されています

## 3. X (Twitter) 捨てアカウント

twscrape は X アカウントの認証情報が必要。普段使いと分離する。

1. 新規メアド（捨て or +付き）でアカウント2〜3個作成
2. SMS認証を済ませる（電話番号は使い回し不可）
3. ログイン状態にしておく

`X_ACCOUNTS` 環境変数の形式（JSON配列）:

```json
[
  {"username":"acc1","password":"pw1","email":"acc1@example.com","email_password":"emailpw1"},
  {"username":"acc2","password":"pw2","email":"acc2@example.com","email_password":"emailpw2"}
]
```

## 4. Discord セットアップ

新規サーバーを作成し、3チャンネル＋Webhookを作る。

| チャンネル名 | 用途 | Webhook URL を Secrets に保存する変数名 |
|---|---|---|
| `#priority` | S/A 重要度の即時通知 | `DISCORD_WEBHOOK_PRIORITY` |
| `#ops` | 日次ダイジェスト・heartbeat | `DISCORD_WEBHOOK_OPS` |
| `#alerts` | 障害・予算警告 | `DISCORD_WEBHOOK_ALERTS` |

各チャンネル → 設定 → 連携サービス → Webhook → 新しいWebhook → URL をコピー

## 5. Google Cloud サービスアカウント

1. https://console.cloud.google.com で新規プロジェクト作成
2. APIs & Services → Library で **Google Sheets API** と **Google Drive API** を有効化
3. APIs & Services → Credentials → Create Credentials → Service Account
4. サービスアカウントのメールアドレスをメモ（`xxx@yyy.iam.gserviceaccount.com`）
5. 作成後の鍵タブで Add Key → JSON → ダウンロード
6. JSONの中身を**1行に圧縮**（オンラインツール or `jq -c .`）して `GOOGLE_SHEETS_CREDENTIALS` に登録予定

## 6. Google Sheets作成

1. https://sheets.google.com で新規シート作成
2. シート名 `info-collector-watchlist` 等
3. URL から ID を取得（`/d/SHEET_ID/edit`）
4. シートを上のサービスアカウントメールアドレスに**編集者として共有**
5. 1枚目のシート名を `watchlist` に変更
6. `config/watchlist.csv` の内容をペースト（ファイル → インポート → 置換）
7. 必要に応じて2枚目以降に `keywords`, `mute`, `priority_boost` シートを追加

## 7. Notion DB作成

ジャンル別に2つDBを作る。スキーマは以下に従ってプロパティを作成。

### 共通プロパティ（両DB）

| プロパティ名 | 型 | 設定 |
|---|---|---|
| Title | Title (デフォルト) | — |
| Importance | Select | S, A, B, C |
| Category | Select | （後で自動追加されるので空でOK） |
| Genre | Select | games, anime, both |
| URL | URL | — |
| Author | Text | — |
| Timestamp | Date | — |
| Tags | Multi-select | （後で自動追加） |
| Spoiler | Select | なし, 軽微, 重大 |
| Source | Select | 公式, メディア, 個人, リーカー, 大会, VTuber |
| DedupKey | Text | — |

### Notion API 連携

1. https://www.notion.so/profile/integrations で **新規Integration作成**
2. シークレット（`secret_...` の文字列）を `NOTION_TOKEN` として登録予定
3. 各DBページを開いて右上 `...` → Add connections → 作成したIntegrationを追加
4. 各DBのURLからID取得（`notion.so/xxx/DB_ID?v=...` の DB_ID部分）
5. ゲーム用DB ID → `NOTION_DATABASE_ID_GAMES`、アニメ用 → `NOTION_DATABASE_ID_ANIME`

## 8. Twitch アプリ登録

1. https://dev.twitch.tv/console/apps → Register Your Application
2. OAuth Redirect URLs に `http://localhost` 等を入れる（実際は使わない）
3. Category: Application Integration
4. 作成後、Client ID と Client Secret を取得

## 9. GitHub Secrets / Variables

リポ Settings → Secrets and variables → Actions

### Secrets

| 名前 | 値 |
|---|---|
| `GEMINI_API_KEY` | AIzaSy... |
| `X_ACCOUNTS` | (Step 3 のJSON) |
| `TWITCH_CLIENT_ID` | (Step 8) |
| `TWITCH_CLIENT_SECRET` | (Step 8) |
| `GOOGLE_SHEETS_CREDENTIALS` | (Step 5 のJSON、1行) |
| `GOOGLE_SHEETS_ID` | (Step 6 のID) |
| `NOTION_TOKEN` | secret_... |
| `NOTION_DATABASE_ID_GAMES` | (Step 7) |
| `NOTION_DATABASE_ID_ANIME` | (Step 7) |
| `DISCORD_WEBHOOK_PRIORITY` | (Step 4) |
| `DISCORD_WEBHOOK_OPS` | (Step 4) |
| `DISCORD_WEBHOOK_ALERTS` | (Step 4) |

### Variables

| 名前 | 値 |
|---|---|
| `BREAKER_RESET` | (空。緊急時に `x_twscrape` 等を入れて1回実行) |

## 10. 動作確認

GitHub の `Actions` タブから各ワークフローを手動キック:

1. `Collect Realtime` → workflow_dispatch → Run
2. ログを確認。X認証ログ・取得件数を確認
3. 次に `Process & Daily Digest` → Run
4. data/processed と docs/digests に変更が commit されることを確認
5. Discord #ops に「✅ Daily digest OK」が来れば成功

## 11. cron稼働開始

手動テストが成功したら、何もしなくても cron が回り始めます。

| ワークフロー | スケジュール（UTC → JST） |
|---|---|
| Collect Realtime | 30分ごと |
| Notify Priority | 30分ごと |
| Collect Regular | 3時間ごと |
| Collect Daily | 22:00 UTC = 07:00 JST |
| Process Digest | 22:00 UTC = 07:00 JST |
| Weekly Report | 日 23:00 UTC = 月 08:00 JST |
| Monthly Maintenance | 1日 00:00 UTC |

最初の数日はDiscord #alerts を見て、エラーを潰していく運用です。

---

## トラブル時のコマンド集

ローカルで再現テスト:
```bash
DRY_RUN=true python -m src.jobs.collect hourly
DRY_RUN=true python -m src.jobs.process_digest
DRY_RUN=true python -m src.jobs.notify_priority
```

サーキットブレーカー解除:
```
GitHub Variables の BREAKER_RESET に "x_twscrape" を設定 → ワークフロー1回実行 → 空に戻す
```

本日のGemini API使用量を確認:
```bash
python -c "from src.llm_client import quota_status; import json; print(json.dumps(quota_status(), indent=2))"
```
