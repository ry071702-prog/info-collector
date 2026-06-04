# Claude Code 向けプロジェクト案内

このファイルは Claude Code がこのリポジトリで作業する際の前提資料です。
既存の方針を尊重しつつ、現在のコード・設定・workflow から確認できる事実だけをまとめています。

---

## プロジェクト概要

**info-collector** は、X / YouTube / Twitch / RSS などからゲーム、esports、アニメ、漫画、Disney 関連の情報を収集し、Gemini で分類・要約して Notion / Google Sheets / Discord / Markdown / Astro サイト向けデータへ流す Python 製パイプラインです。

GitHub Actions の cron 実行を前提に、生データを `data/raw/`、分類済みデータを `data/processed/`、レポートを `docs/` に保存します。

### 主要な技術スタック

- Python 3.12
- Gemini API: `google-generativeai`
- X 収集: `twscrape`
- RSS / HTTP: `feedparser`, `httpx`
- Google Sheets: `gspread`, `google-auth`
- Notion: `notion-client`
- 設定・モデル: `tomli`, `python-dotenv`, `pydantic`
- リトライ・ログ: `tenacity`, `loguru`
- サイト: Astro 6, Tailwind CSS 4, Node 20
- HTML/OG 画像解析: `selectolax`
- 自動化: GitHub Actions cron

### 重要な前提

- Gemini API の無料枠運用が前提です。
- 有料 LLM サービスや新しい外部課金サービスを追加しないでください。
- `src/claude_client.py` は互換用で、実体は `src/llm_client.py` です。
- 個人運用向けで、複雑な認証・ロール管理はありません。
- 収集・分類・出力の一部失敗で全体を止めない設計が多いです。
- 外部書き込みを伴う確認は、まず `DRY_RUN=true` を使います。

---

## ディレクトリ構造

```text
.
├── .github/workflows/       # GitHub Actions workflow
├── config/                  # settings.toml と watchlist.csv
├── data/                    # raw / processed / cache / logs
├── docs/                    # digest / weekly / monthly Markdown
├── scripts/                 # 補助スクリプト
├── site/                    # Astro ニュースサイト
├── src/                     # Python パイプライン本体
├── .env.example             # 環境変数サンプル
├── .gitignore
├── README.md
├── SETUP.md
└── requirements.txt
```

### `src/`

Python パイプライン本体です。`admin/`, `collectors/`, `jobs/`, `outputs/`, `processors/` の各パッケージと、`config.py`, `models.py`, `llm_client.py`, `storage.py`, `watchlist.py`, `taxonomy.py`, `prompts.py`, `dedup.py`, `circuit_breaker.py`, `logger.py` などの共有モジュールで構成されています。

### `src/collectors/`

- `x_twscrape.py`: X ユーザー投稿を `twscrape` で収集。
- `youtube_rss.py`: YouTube チャンネル RSS を収集。API キー不要。
- `youtube_search.py`: YouTube Data API v3 `search.list` で検索クエリ由来の動画を収集。
- `youtube_trending.py`: YouTube Data API v3 `videos.list(chart=mostPopular)` で急上昇動画を収集。
- `twitch_api.py`: Twitch Helix API でライブ配信と最近の VOD を収集。
- `rss_generic.py`: 汎用 RSS フィードを収集。

### `src/processors/`

- `classify.py`: `RawItem` をフィルタリングし、ジャンル判定、詳細分類、スコアリングをして `ProcessedItem` にする。
- `digest.py`: `ProcessedItem` 群から日次ダイジェストと週次レポート本文を生成する。

### `src/outputs/`

- `notion.py`: Notion DB にジャンル別でページ作成。
- `sheets.py`: Google Sheets に分類済み行を append。
- `discord.py`: Discord Webhook に優先通知・運用通知・アラートを送信。
- `markdown.py`: `docs/digests/`, `docs/weekly/`, `docs/monthly/` に Markdown を保存。

### `src/jobs/`

- `collect.py`: frequency tier に応じて watchlist を絞り、全 collector を呼ぶ。
- `process_digest.py`: 当日または前日の raw を分類し、重複排除後に output へ書く。
- `notify_priority.py`: 直近 raw を簡易分類し、S/A を Discord priority に通知。
- `report_weekly.py`: 直近 7 日分の週次レポートを生成。
- `maintenance_monthly.py`: 直近 30 日統計、月次レポート、古い raw/log 削除。

### `src/admin/`

- `health.py`: watchlist、直近 processed 件数、silent source、容量、Gemini 使用量を表示。
- `init_notion_schema.py`: Notion DB に β スコアリング用プロパティを追加。

### `config/`

- `settings.toml`: モデル、バッチサイズ、リトライ、collector、保持期間、スコアリング。
- `watchlist.csv`: watchlist の唯一の canonical(正本)。collector はここだけを読む。

### `data/`

- `data/raw/<YYYY-MM-DD>/<source_id>.jsonl`: collector が書く `RawItem`。
- `data/processed/<YYYY-MM-DD>/items.jsonl`: `process_digest` が書く `ProcessedItem`。
- `data/cache/dedup_keys.json`: 直近 7 日の重複排除キー。
- `data/cache/discord_sent.json`: Discord priority 通知の 24 時間重複抑制。
- `data/cache/api_usage.jsonl`: Gemini API リクエスト数。
- `data/cache/circuit_breakers.json`: circuit breaker 状態。
- `data/logs/<YYYY-MM-DD>.jsonl`: loguru の JSONL ログ。

### `docs/`

- `docs/digests/`: 日次ダイジェスト。
- `docs/weekly/`: 週次レポート。
- `docs/monthly/`: 月次メンテナンスレポート。

### `site/`

Astro 製の静的ニュースサイトです。主なページは `index.astro`, `games/index.astro`, `anime/index.astro`, `disney/index.astro`, `digest/[date].astro` です。生成物の `site/src/data/articles.json` と `site/public/og-cache/` は `.gitignore` 対象です。

---

## よく使うコマンド

### セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` はコミット禁止です。

### 収集

```bash
DRY_RUN=true python -m src.jobs.collect realtime
DRY_RUN=true python -m src.jobs.collect hourly
DRY_RUN=true python -m src.jobs.collect 6h
DRY_RUN=true python -m src.jobs.collect daily
```

`collect.py` の tier:

- `realtime`: lookback 1 時間。
- `hourly`: lookback 4 時間。
- `6h`: lookback 8 時間。
- `daily`: lookback 30 時間。

### 分類・通知・レポート

```bash
DRY_RUN=true python -m src.jobs.process_digest
DRY_RUN=true python -m src.jobs.notify_priority
DRY_RUN=true python -m src.jobs.report_weekly
DRY_RUN=true python -m src.jobs.maintenance_monthly
```

`process_digest` は今日 UTC の raw を読み、なければ昨日 UTC の raw にフォールバックします。
`notify_priority` は直近 45 分の raw を分類し、S/A のみ Discord priority に通知します。

### 管理

```bash
python -m src.admin.health
python -m src.admin.init_notion_schema
```

`init_notion_schema` は Notion DB を更新します。
実行には `NOTION_TOKEN` と少なくとも 1 つの `NOTION_DATABASE_ID_*` が必要です。

### Gemini 使用量確認

```bash
python -c "from src.llm_client import quota_status; import json; print(json.dumps(quota_status(), indent=2, ensure_ascii=False))"
```

### テスト・簡易確認

現時点で pytest テストや専用テストディレクトリは見当たりません。
変更後の最低限の確認には compileall を使います。

```bash
python -m compileall src scripts
```

外部 API キーがない環境では、一部 collector や output がスキップまたは失敗ログを出します。

### サイト

```bash
python scripts/build_site_data.py
cd site
npm install
npm run dev
```

CI と同じ依存解決に寄せる場合:

```bash
python scripts/build_site_data.py
cd site
npm ci
npm run build
```

### 依存関係管理

- Python 依存は `requirements.txt`。
- Node 依存は `site/package.json` と `site/package-lock.json`。
- 新しい依存は必要性を確認してから追加してください。

---

## コーディング規約・慣習

### 全体

- 多くの Python ファイルで `from __future__ import annotations` を使っています。
- 型ヒントを付けるスタイルです。
- データ構造は `src/models.py` の Pydantic モデル中心です。
- JSONL の読み書きは `src/storage.py` に寄せます。
- 環境変数は `src/config.py` の `env`, `env_json`, `env_bool`, `is_dry_run` を使います。
- 設定値は `config/settings.toml` を読む `settings()` を使います。
- ログは `logger.get(__name__)` で取得します。
- 外部 I/O は局所的に例外を捕まえ、可能な範囲で後続処理を続けます。
- コメントは日本語も使われています。

### 主なモデル

`src/models.py` の中心は `WatchSource`, `RawItem`, `FilterResult`, `Flags`, `ProcessedItem` です。`Genre` は `games/anime/disney/both/neither`、`Importance` は `S/A/B/C`、`SourceRole` は `公式/メディア/個人/リーカー/大会/VTuber` です。

### Collector の構成パターン

collector は `src/collectors/*.py` に置き、概ね `collect(sources, since) -> list[RawItem]` を公開します。対象 platform の source だけを選び、source 単位の失敗はログに残して次へ進む実装が多いです。

新 collector 追加時の確認先:

- `WatchSource.platform` の Literal。
- `config/watchlist.csv` の `platform`。
- `src/jobs/collect.py` の collector 一覧。
- 必要なら `config/settings.toml`。
- 出力は `RawItem` に正規化します。

### Processor の構成パターン

`src/processors/classify.py` は 2 段階です。

1. `filter_and_genre`: スパム判定とジャンル判定。
2. `classify_full`: taxonomy に基づく詳細分類。

`both` は games 側を先に分類し、anime 側も分類して重要度が高い方を採用します。
`disney` は `DISNEY_TAXONOMY` を使います。

スコアリングは `config/settings.toml` の `[scoring]` で調整します。

- `freshness_score`
- `streamer_influence_score`
- `clip_virality_score`
- `game_trend_from_streamers_score`
- `final_priority`
- `risk_level`

### Output の構成パターン

- output は `src/outputs/*.py` に置きます。
- 外部書き込みは `DRY_RUN` を尊重してください。
- Notion は DB に存在しないプロパティを `_filter_existing` で落とします。
- Sheets は `ゲーム&esports` と `アニメ&漫画` worksheet に append します。
- Discord priority 通知は `data/cache/discord_sent.json` で重複抑制します。

### LLM 呼び出し

- Gemini 呼び出しは `src/llm_client.py` を通します。
- JSON 返却は `call_json`、テキスト返却は `call_text` を使います。
- プロンプト本文は `src/prompts.py` に集約します。
- モデル選択は `config/settings.toml` の `[models]` で行います。
- 使用量は `data/cache/api_usage.jsonl` に記録されます。

### 重複排除

- `RawItem.fingerprint` は URL があれば URL、なければ `author|timestamp`。
- `process_digest` は処理済み `raw_fingerprint` をスキップします。
- `dedup.filter_new` は `dedup_key` を 7 日間保持します。
- Discord priority 通知は `dedup_key` を 24 時間保持します。

---

## 重要なファイル

- エントリポイント: `src/jobs/collect.py`, `src/jobs/process_digest.py`, `src/jobs/notify_priority.py`, `src/jobs/report_weekly.py`, `src/jobs/maintenance_monthly.py`, `src/admin/health.py`, `src/admin/init_notion_schema.py`, `scripts/build_site_data.py`
- 設定: `config/settings.toml`, `config/watchlist.csv`, `.env.example`, `.github/workflows/*.yml`
- データ: `data/raw/`, `data/processed/`, `data/cache/`, `data/logs/`
- 分類: `src/taxonomy.py`, `src/prompts.py`, `src/processors/classify.py`, `src/processors/digest.py`
- 出力: `src/outputs/notion.py`, `src/outputs/sheets.py`, `src/outputs/discord.py`, `src/outputs/markdown.py`
- サイト: `site/package.json`, `site/astro.config.mjs`, `site/src/pages/`, `site/src/components/`, `site/src/lib/articles.ts`, `site/src/styles/global.css`

---

## GitHub Actions ワークフロー

`.github/workflows/` の内容:

- `_shared.yml`: 参照テンプレート。実運用ジョブではありません。
- `collect_realtime.yml`: 30 分ごとに `python -m src.jobs.collect realtime`。
- `notify_priority.yml`: 30 分ごとに `python -m src.jobs.notify_priority`。
- `collect_regular.yml`: 3 時間ごとに `python -m src.jobs.collect 6h`。
- `collect_daily.yml`: 毎日 22:00 UTC に `python -m src.jobs.collect daily`。
- `process_digest.yml`: 毎日 22:00 UTC に `python -m src.jobs.process_digest`。
- `report_weekly.yml`: 日曜 23:00 UTC に `python -m src.jobs.report_weekly`。
- `maintenance_monthly.yml`: 毎月 1 日 00:00 UTC に `python -m src.jobs.maintenance_monthly`。
- `health.yml`: 手動で `python -m src.admin.health`。
- `notion_schema_init.yml`: 手動で `python -m src.admin.init_notion_schema`。
- `publish_site.yml`: `Process & Daily Digest` 成功後、または手動で Astro サイトを GitHub Pages にデプロイ。

主な commit 対象:

- collect 系: `data/raw`, `data/cache`, `data/logs`
- notify priority: `data/cache`
- process digest: `data/processed`, `docs/digests`, `data/cache`, `data/logs`
- weekly report: `docs/weekly`
- monthly maintenance: `docs/monthly`, `data/logs`
- publish site: Pages artifact を deploy。`site/dist` は commit しません。

---

## 外部連携

### Gemini

- 使用箇所: `src/llm_client.py`, `src/processors/classify.py`, `src/processors/digest.py`, `src/jobs/maintenance_monthly.py`
- env: `GEMINI_API_KEY`
- モデルは `config/settings.toml` の `[models]` で指定。
- `llm_client.py` は RPM throttle と日次 request count を持ちます。

### X / Twitter

- 使用箇所: `src/collectors/x_twscrape.py`
- env: `X_ACCOUNTS`
- `X_ACCOUNTS` が空なら INFO ログでスキップします。
- circuit breaker 名は `x_twscrape`。
- 手動リセットは `BREAKER_RESET=x_twscrape`。

### YouTube

- `youtube_rss.py`: チャンネル RSS。API キー不要。
- `youtube_search.py`: YouTube Data API v3 `search.list`。env は `YOUTUBE_API_KEY`。
- `youtube_trending.py`: YouTube Data API v3 `videos.list(chart=mostPopular)`。env は `YOUTUBE_API_KEY`。
- `YOUTUBE_API_KEY` がなければ Search / Trending はスキップします。

### Twitch

- 使用箇所: `src/collectors/twitch_api.py`
- env: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`
- OAuth client credentials flow で app access token を取得。
- Helix の `users`, `streams`, `videos` を使います。

### RSS

- 使用箇所: `src/collectors/rss_generic.py`
- `WatchSource.platform == "RSS"` が対象。
- `feedparser` と `httpx` を使います。

### Google Sheets

- 使用箇所: `src/watchlist.py`, `src/outputs/sheets.py`, `src/admin/health.py`
- env: `GOOGLE_SHEETS_CREDENTIALS`, `GOOGLE_SHEETS_ID`
- watchlist の正本は `config/watchlist.csv`(`watchlist.load()` は CSV だけを読む)。Sheets からは読まない。
- Sheets への同期は既定で無効。`SYNC_SHEETS_FROM_CSV=true` を明示した場合のみ `_sync_csv_to_sheets` が動く。
  - この同期は `ws.clear()` で Sheets を CSV 内容に全置換する破壊的処理。過去に Sheets 側のみに存在したソースを消した実績があるため(2026-05-21)、原則有効化しない。
- 出力 worksheet は `ゲーム&esports` と `アニメ&漫画`(watchlist とは別用途)。

### Notion

- 使用箇所: `src/outputs/notion.py`, `src/admin/init_notion_schema.py`
- env: `NOTION_TOKEN`, `NOTION_DATABASE_ID_GAMES`, `NOTION_DATABASE_ID_ANIME`, `NOTION_DATABASE_ID_DISNEY`
- `disney` は Disney DB、`anime` は Anime DB、それ以外は Games DB。
- DB ID は URL 全体でも `normalize_db_id` で UUID 形式に正規化。
- schema が取れた場合、DB に存在しないプロパティはスキップします。

### Discord

- 使用箇所: `src/outputs/discord.py`
- env: `DISCORD_WEBHOOK_PRIORITY`, `DISCORD_WEBHOOK_OPS`, `DISCORD_WEBHOOK_ALERTS`
- priority は S/A 通知、ops は運用通知、alerts は障害通知向けです。

### Astro / GitHub Pages

- 使用箇所: `site/`, `scripts/build_site_data.py`, `.github/workflows/publish_site.yml`
- `publish_site.yml` は Python でサイトデータを生成し、Node 20 で Astro を build して Pages に deploy します。

---

## Watchlist

`config/watchlist.csv` のカラム:

```text
id,name,handle,url,platform,genre,source_type,subcategory_hints,priority,enabled,check_frequency,language,notes
```

主な値:

- `platform`: `X`, `YouTube`, `Twitch`, `RSS`, `Web`, `YouTubeSearch`, `YouTubeTrending`
- `genre`: `games`, `anime`, `disney`, `both`, `neither`
- `source_type`: `公式`, `メディア`, `個人`, `リーカー`, `大会`, `VTuber`
- `priority`: `high`, `medium`, `low`
- `enabled`: `TRUE` / `FALSE`
- `check_frequency`: `realtime`, `hourly`, `6h`, `daily`
- `language`: `ja`, `en`, `multi`

frequency の絞り込み:

- `realtime`: `check_frequency == "realtime"`
- `hourly`: `realtime` または `hourly`
- `6h`: `realtime`, `hourly`, `6h`
- `daily`: 全 source

現時点の CSV は X / YouTube / RSS / YouTubeSearch / YouTubeTrending を含み、games / anime / disney をカバーします。

---

## Notion DB スキーマ

`src/outputs/notion.py` が書く基本プロパティは `Title`, `Importance`, `Category`, `Genre`, `URL`, `Author`, `Timestamp`, `Tags`, `Spoiler`, `Source`, `DedupKey` です。β スコアリング用の任意プロパティは `RiskLevel`, `FinalPriority`, `FreshnessScore`, `StreamerInfluence`, `ClipVirality`, `GameTrendFromStreamers` で、`python -m src.admin.init_notion_schema` により追加できます。

---

## 注意点

### 秘密情報

- `.env` は `.gitignore` 対象です。
- `config/secrets/*` は `.gitignore` 対象で、`.gitkeep` だけ例外です。
- API キー、Webhook URL、service account JSON、X credentials を commit しないでください。
- `GOOGLE_SHEETS_CREDENTIALS` は service account JSON を env に入れる設計です。
- `X_ACCOUNTS` には username/password/email/email_password が入ります。
- GitHub Actions では Secrets / Variables から注入します。

### DRY_RUN

`DRY_RUN=true` で抑制される外部書き込み:

- Notion 書き込み。
- Google Sheets append。
- Discord post / notify。

collector の外部読み取り、Gemini 呼び出し、ローカルファイル書き込みはコード上すべてが止まるわけではありません。

### Gemini 無料枠

- `llm_client.py` はモデル別 RPM 制限を持ちます。
- `process_digest.py` は分類 chunk が連続で空になった場合、quota 切れとみなして早期停止します。
- `maintenance_monthly.py` は直近 30 日の件数が 50 未満なら AI 分析をスキップします。
- 使用量確認は `quota_status()` で行います。

### GitHub Actions とデータ commit

- collect / process / report 系 workflow は生成物を commit して push します。
- 一部 workflow は `concurrency` を設定しています。
- workflow 内では `git pull --rebase --autostash` 後に push します。
- 手元の未 commit 変更と Actions 由来 commit の衝突に注意してください。

### data の保持期間

`config/settings.toml` の `[retention]`:

- `raw_days = 60`
- `logs_days = 30`
- `data/processed/` は archive 扱いで削除対象外。
- `data/cache/` は dedup や api_usage が自己管理する前提。

### サイトデータ生成

`src/storage.py` は processed を `data/processed/<YYYY-MM-DD>/items.jsonl` に書きます。
一方で `scripts/build_site_data.py` の `processed_files()` は `data/processed/*.jsonl` を glob しています。
サイト生成周りを直す場合は、この processed ファイル配置の差を確認してください。

### Disney 対応

`models.py`, `taxonomy.py`, `classify.py`, `notion.py`, `site/src/pages/disney/index.astro` には Disney 対応があります。
古い記述が games / anime のみでも、現在のコードを優先してください。

### X 収集

`X_ACCOUNTS` が空の場合、X 収集は INFO ログでスキップされます。
これはエラーではなく fallback として実装されています。

### Google Sheets watchlist

`watchlist.load()` は `config/watchlist.csv` を唯一の canonical として読みます(Sheets からは読みません)。
Sheets への同期は既定で無効です。`SYNC_SHEETS_FROM_CSV=true` を設定したときだけ `_sync_csv_to_sheets` が `ws.clear()` で Sheets を CSV 内容に全置換します。この破壊的同期は過去に Sheets 側のみのソースを消した実績があるため、原則有効化しないでください。
ソースの追加・編集は `config/watchlist.csv` を直接編集します。

### Notion 書き込み

Notion DB ID が 1 つも設定されていない場合はスキップします。
DB スキーマ取得に失敗した場合でも、書き込み処理自体は試行されます。
DB に存在しないプロパティは schema が取得できた場合のみ落とされます。

---

## 🤖 自動メンテナンスエージェント向け (claude.ai/code/routines)

このリポジトリには毎日 03:00 JST に動く自動メンテナンスエージェントが設定されている。エージェントが作業する際の **必読ルール**:

### ⛔ 絶対禁止
- **実 API 通信** — 以下はすべてモック化必須:
  - Gemini API (`llm_client`)
  - Notion API (`outputs/notion.py`)
  - Google Sheets API (`outputs/sheets.py`, `watchlist`)
  - Discord webhook
  - YouTube Data API
  - Twitch API
  - 外部 RSS フィード取得
- `.env` / GitHub Actions secrets の変更
- `data/raw/`, `data/processed/` 配下の実データ削除・上書き
- `.github/workflows/` の本番ジョブを破壊する変更 (collect_*, process_digest, publish_site, notify_priority など)
- `config/watchlist.csv` の機械的書き換え (収集対象を決める運用データ。人間が内容を判断して編集する。Sheets 同期は既定無効なので CSV が唯一の正本)
- main への直接 commit、force push、`git reset --hard`

### ✅ 推奨
- テストは `.env` なしで pass する作りに (`monkeypatch.setenv` で必要な env を注入)
- HTTP モックは `responses` / `requests-mock` / `pytest-mock`
- VCR.py で外部 API レスポンスを固定したい場合は `tests/cassettes/` 配下に
- 失敗を恐れず **draft PR** で人間レビューへ
- 1 PR = 1 テーマ (依存更新は1パッケージ1 PR)
- 大規模リファクタは分割

### モック対象の具体的なファイル
- `src/llm_client.py` — Gemini 呼び出し
- `src/outputs/notion.py`, `src/outputs/sheets.py`, `src/outputs/discord.py`
- `src/processors/*.py` — RSS/YouTube/Twitch 取得・正規化
- `src/jobs/*.py` — GitHub Actions ジョブ本体

### 環境制約
- 環境変数は無い前提で動かす
- ネットワーク経由の外部 API 呼び出しは禁止 (タイムアウトで bail する)
- secrets が必要なテストは `pytest.mark.skip` または `pytest.importorskip` で逃がす
