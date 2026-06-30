# info-collector 設計仕様書

> 対象読者: このリポジトリを引き継ぐ/改修するエンジニア。
> 本書はコード・設定・workflow から確認できる事実をまとめた **正確な設計仕様** です。
> 概要だけ知りたい人は [OVERVIEW.md](OVERVIEW.md)、ゼロから作りたい人は [REBUILD_PROMPT.md](REBUILD_PROMPT.md) を参照。

---

## 1. システム概要

X / YouTube / Twitch / RSS から **ゲーム・esports・アニメ・漫画・Disney** 関連の情報を収集し、
Gemini で分類・要約・スコアリングして、**Notion / Google Sheets / Discord / Markdown / Astro サイト** へ配信する Python パイプライン。

- 実行基盤: **GitHub Actions cron**（サーバー常駐なし）
- コスト方針: **Gemini API 無料枠 + GitHub Actions 無料枠 = 月額ほぼ0円**
  - 唯一の例外: 新聞風画像生成のみ有料モデル `gemini-3-pro-image-preview`（1日1枚 ≒ 月¥600〜1,100）を意図的に許容
- 公開フロントエンド: Astro サイト（Cloudflare Pages + D1）。閲覧は誰でも可、「保存→AI要約」機能のみパスコード本人限定

### 技術スタック

| 領域 | 技術 |
|---|---|
| 言語 | Python 3.12 |
| LLM | Gemini API (`google-generativeai`) |
| X 収集 | `twscrape` |
| RSS/HTTP | `feedparser`, `httpx`, `selectolax` |
| Google Sheets | `gspread`, `google-auth` |
| Notion | `notion-client`（API バージョン `2022-06-28` 固定） |
| 設定/モデル | `tomli`, `python-dotenv`, `pydantic` |
| リトライ/ログ | `tenacity`, `loguru` |
| サイト | Astro 6 / Tailwind CSS 4 / Node 20 |
| バックエンド | Cloudflare Pages Functions + D1 |
| 自動化 | GitHub Actions cron |

---

## 2. アーキテクチャ

```
[GitHub Actions cron]
   │
   ├─ collect (realtime/hourly/6h/daily)
   │     └─ collectors/ → data/raw/<date>/<source_id>.jsonl  (RawItem, git commit)
   │
   ├─ notify_priority (30分ごと)
   │     └─ 直近 raw を簡易分類 → S/A のみ Discord #priority
   │
   ├─ process_digest (毎日 22:00 UTC)
   │     ├─ classify.py で RawItem → ProcessedItem
   │     ├─ dedup → data/processed/<date>/items.jsonl
   │     └─ outputs/ → Notion / Sheets / Discord / docs/digests/
   │
   ├─ report_weekly (日 23:00 UTC)  → docs/weekly/
   ├─ maintenance_monthly (毎月1日)  → docs/monthly/ + 古い raw/log 削除
   └─ publish_site → Astro build → Cloudflare Pages (Functions + D1 同梱)
```

データは 3 段で流れる:

1. **収集レイヤー** (`collectors/`) … 各プラットフォームを叩いて `RawItem` に正規化
2. **処理レイヤー** (`processors/`) … フィルタ → ジャンル判定 → 詳細分類 → スコアリング → `ProcessedItem`
3. **出力レイヤー** (`outputs/`) … Notion / Sheets / Discord / Markdown へ配信

各レイヤーは **部分失敗で全体を止めない（graceful degradation）** 設計。
外部書き込みを伴う検証は `DRY_RUN=true` で抑制する。

---

## 3. ディレクトリ構成

```text
.
├── .github/workflows/   # GitHub Actions（収集/処理/レポート/公開）
├── config/
│   ├── settings.toml    # モデル選択・バッチ・リトライ・保持期間・スコアリング
│   ├── watchlist.csv    # 監視対象の唯一の正本（canonical）
│   └── watchlist_org.csv
├── data/
│   ├── raw/<date>/<source_id>.jsonl   # RawItem（collector 出力）
│   ├── processed/<date>/items.jsonl   # ProcessedItem（process_digest 出力）
│   ├── cache/           # dedup_keys / discord_sent / api_usage / circuit_breakers
│   └── logs/<date>.jsonl
├── docs/
│   ├── digests/         # 日次ダイジェスト
│   ├── weekly/          # 週次レポート
│   ├── monthly/         # 月次メンテレポート
│   └── spec/            # 本仕様書群
├── scripts/             # build_site_data / generate_newspaper_image / 他
├── site/                # Astro ニュースサイト（functions/ に Pages Functions）
└── src/                 # パイプライン本体
```

### `src/` モジュール一覧

| 区分 | ファイル | 役割 |
|---|---|---|
| 共有 | `config.py` | env / settings アクセサ（`env`, `env_json`, `env_bool`, `is_dry_run`, `settings`） |
| 共有 | `models.py` | Pydantic モデル群（後述） |
| 共有 | `llm_client.py` | Gemini ラッパー（`call_json` / `call_text` / throttle / `quota_status`） |
| 共有 | `storage.py` | JSONL I/O |
| 共有 | `watchlist.py` | `config/watchlist.csv` の読み込み（正本） |
| 共有 | `taxonomy.py` | サブカテゴリ定義（GAMES / ANIME / DISNEY） |
| 共有 | `prompts.py` | 全プロンプト本文 |
| 共有 | `dedup.py` | 重複検知（7日保持） |
| 共有 | `circuit_breaker.py` | サーキットブレーカー |
| 共有 | `logger.py` | loguru ベースの構造化ログ |
| collectors | `x_twscrape.py` | X ユーザー投稿（twscrape） |
| collectors | `x_search.py` | X 検索クエリ収集 |
| collectors | `youtube_rss.py` | YouTube チャンネル RSS（APIキー不要） |
| collectors | `youtube_search.py` | YouTube Data API `search.list` |
| collectors | `youtube_trending.py` | YouTube Data API `videos.list(chart=mostPopular)` |
| collectors | `twitch_api.py` | Twitch Helix（live + 最近の VOD） |
| collectors | `rss_generic.py` | 汎用 RSS |
| collectors | `web_browseruse.py` | Web 収集（補助） |
| processors | `classify.py` | フィルタ→ジャンル判定→詳細分類→スコアリング |
| processors | `digest.py` | 日次/週次レポート本文生成 |
| processors | `change_detect.py` | 変化検知 |
| outputs | `notion.py` | Notion DB へジャンル別ページ作成 |
| outputs | `sheets.py` | Google Sheets へ append |
| outputs | `discord.py` | Discord Webhook（priority / ops / alerts） |
| outputs | `markdown.py` | docs/ へ Markdown 保存 |
| outputs | `slack_digest.py`, `email_digest.py` | Slack / メール配信 |
| jobs | `collect.py` | tier に応じて watchlist 絞り込み→全 collector 実行 |
| jobs | `process_digest.py` | raw 分類→dedup→output 書き込み |
| jobs | `notify_priority.py` | 直近 raw を簡易分類→S/A 通知 |
| jobs | `report_weekly.py` | 直近7日の週次レポート |
| jobs | `maintenance_monthly.py` | 月次統計 + 古いデータ削除 |
| jobs | `send_catchup.py` | キャッチアップメール |
| jobs | `org_intel.py` | 組織インテリジェンス（補助） |
| admin | `health.py` | watchlist / silent source / 容量 / Gemini 使用量表示 |
| admin | `init_notion_schema.py` | Notion DB に β スコアリング用プロパティ追加 |
| admin | `prune_notion_schema.py` | 旧 `Tags`(multi_select) 削除 |
| admin | `refilter_processed.py`, `purge_by_source.py` | 再分類 / ソース単位パージ |

---

## 4. データモデル（`src/models.py`）

```python
Genre      = Literal["games", "anime", "disney", "both", "neither"]
Importance = Literal["S", "A", "B", "C"]
SourceRole = Literal["公式", "メディア", "個人", "リーカー", "大会", "VTuber"]
```

### WatchSource（監視対象 1 件）
`id, name, handle, url, platform, genre, source_type, subcategory_hints[], priority, enabled, check_frequency, language, notes`
- `platform`: `X / YouTube / Twitch / RSS / Web / YouTubeSearch / YouTubeTrending / XSearch`
- `check_frequency`: `realtime / hourly / 6h / daily`

### RawItem（収集レイヤー出力）
`source_id, platform, author, account_type, text, url, timestamp, extra{}`
- `fingerprint` プロパティ = `url`、無ければ `author|timestamp.isoformat()`

### FilterResult（Step1+2 出力）
`spam: bool, genre, confidence: float, reason`

### Flags（記事メタ）
`source_role, speed(速報/通常/アーカイブ), spoiler(なし/軽微/重大), language, content_type(text/image/video/live), source_reliability(公式確定/公式予告中/信頼リーカー/噂/二次), cross_genre`

### ProcessedItem（Step3 出力 = 配信単位）
基本: `source_id, raw_fingerprint, timestamp, url, author, genre, subcategory_id, category_name, importance, summary, title_tags[], entity_tags[], flags, dedup_key, raw_text`

β スコアリング:
`risk_level(low/middle/high), streamer_influence_score, clip_virality_score, game_trend_from_streamers_score, live_trend_score, video_trend_score, freshness_score`（各 0-100）, `final_priority(S/A/B/C)`

配信者・切り抜き文脈メタ:
`streamer_name, streamer_group, is_clip, related_game_title, related_anime_title`

---

## 5. 処理パイプライン詳細

### 5.1 収集（`jobs/collect.py`）

tier ごとに lookback と対象ソースを変える:

| tier | lookback | 対象 source |
|---|---|---|
| `realtime` | 1h | `check_frequency == realtime` |
| `hourly` | 4h | `realtime` または `hourly` |
| `6h` | 8h | `realtime / hourly / 6h` |
| `daily` | 30h | 全 source |

各 collector は概ね `collect(sources, since) -> list[RawItem]` を公開。
自分の platform のソースだけを選び、**ソース単位の失敗はログに残して次へ進む**。

### 5.2 分類（`processors/classify.py`）2 段階

1. `filter_and_genre`（`filter` + `classify` モデル）… スパム判定 + ジャンル判定
2. `classify_full` … taxonomy に基づく詳細分類 + スコアリング

- `genre == both` … games 側を先に分類、anime 側も分類して**重要度が高い方**を採用
- `genre == disney` … `DISNEY_TAXONOMY` を使用
- スコアリングは `config/settings.toml [scoring]` のみで調整可能（再デプロイ不要）

### 5.3 スコアリング（`config/settings.toml [scoring]`）

`final_priority` は重み付き合成（合計 1.0 推奨）:

| 重み | 既定 | 意味 |
|---|---|---|
| `weight_importance` | 0.5 | Gemini の S/A/B/C |
| `weight_freshness` | 0.2 | 鮮度（経過時間） |
| `weight_streamer` | 0.15 | 配信者界隈の話題量 |
| `weight_virality` | 0.10 | 切り抜き拡散 |
| `weight_trend` | 0.05 | 配信者起点ゲームトレンド |
| `weight_live` | 0.10 | Twitch 同接 |
| `weight_video` | 0.10 | YouTube views/hour |

閾値: `final_S_threshold=80 / final_A_threshold=60 / final_B_threshold=35`（0-100）
鮮度: 24h=100 / 72h=70 / 1週=40 / それ以降=10（線形補間）

### 5.4 重複排除（`dedup.py`）

- `RawItem.fingerprint` = URL or `author|timestamp`
- `process_digest` は処理済み `raw_fingerprint` をスキップ
- `dedup.filter_new` は `dedup_key` を **7 日間**保持（`data/cache/dedup_keys.json`）
- Discord priority 通知は `dedup_key` を **24 時間**保持（`data/cache/discord_sent.json`）

### 5.5 サブカテゴリ（`taxonomy.py`）

`GAMES_TAXONOMY` / `ANIME_TAXONOMY` / `DISNEY_TAXONOMY` の 3 体系を文字列で保持し、
プロンプトに注入する。カテゴリ追加は該当文字列に追記するだけ。

---

## 6. 出力（`src/outputs/`）

| 出力先 | 内容 | DRY_RUN 抑制 |
|---|---|---|
| Notion | ジャンル別 DB にページ作成（games / anime / disney） | ✅ |
| Sheets | `ゲーム&esports` / `アニメ&漫画` worksheet に append | ✅ |
| Discord | priority(S/A) / ops(運用) / alerts(障害) | ✅ |
| Markdown | `docs/digests` `docs/weekly` `docs/monthly` | （ローカル書き込み） |

### Notion DB スキーマ

基本プロパティ: `Title, Importance, Category, Genre, URL, Author, Timestamp, TagsText, Spoiler, Source, DedupKey`
β 任意プロパティ（`init_notion_schema` で追加）: `RiskLevel, FinalPriority, FreshnessScore, StreamerInfluence, ClipVirality, GameTrendFromStreamers`

**重要な制約:**
- タグは旧 `Tags`(multi_select) → `TagsText`(rich_text) へ移行済み。multi_select は書き込み毎に unique option を溜め込み、schema 上限(~489KB)到達で全書き込みが失敗する。**新規に multi_select のタグを増やさないこと。**
- Notion-Version は `2022-06-28` 固定（新 data source モデルだと `databases.retrieve` が `properties` を返さず schema 取得が壊れる）。
- プロパティ削除は notion-client の `databases.update({k: None})` が効かない → `prune_notion_schema` が raw httpx で `{"properties":{"Tags":null}}` を直送。

---

## 7. GitHub Actions ワークフロー

| workflow | スケジュール (UTC→JST) | 実行 | 主な commit 対象 |
|---|---|---|---|
| `collect_realtime.yml` | 30分ごと | `collect realtime` | data/raw, cache, logs |
| `notify_priority.yml` | 30分ごと | `notify_priority` | data/cache |
| `collect_regular.yml` | 3時間ごと | `collect 6h` | data/raw, cache, logs |
| `collect_daily.yml` | 22:00 UTC = 07:00 JST | `collect daily` | data/raw, cache, logs |
| `process_digest.yml` | 22:00 UTC = 07:00 JST | `process_digest` | data/processed, docs/digests, cache, logs |
| `report_weekly.yml` | 日 23:00 UTC = 月 08:00 JST | `report_weekly` | docs/weekly |
| `maintenance_monthly.yml` | 毎月1日 00:00 UTC | `maintenance_monthly` | docs/monthly, logs |
| `publish_site.yml` | Process 成功後 / 手動 | Astro build → Cloudflare Pages | （dist は commit しない） |
| `health.yml` ほか | 手動 | admin 系 | — |

- workflow は生成物を `git pull --rebase --autostash` 後に commit して push する。
- 一部 workflow は `concurrency` を設定。手元の未 commit 変更との衝突に注意。

---

## 8. 外部連携と環境変数

| 連携先 | env | 備考 |
|---|---|---|
| Gemini | `GEMINI_API_KEY` | モデルは settings.toml `[models]`。RPM throttle + 日次カウント |
| X | `X_ACCOUNTS`(JSON配列) | 空ならスキップ（エラーではない）。breaker 名 `x_twscrape` |
| YouTube | `YOUTUBE_API_KEY` | RSS は不要、Search / Trending は必須 |
| Twitch | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | OAuth client credentials flow |
| Google Sheets | `GOOGLE_SHEETS_CREDENTIALS`(service account JSON), `GOOGLE_SHEETS_ID` | 読みは CSV。Sheets 同期は `SYNC_SHEETS_FROM_CSV=true` のときだけ（破壊的、原則無効） |
| Notion | `NOTION_TOKEN`, `NOTION_DATABASE_ID_GAMES/ANIME/DISNEY` | DB ID は URL でも可（`normalize_db_id`） |
| Discord | `DISCORD_WEBHOOK_PRIORITY/OPS/ALERTS` | — |
| Cloudflare（サイト） | Pages secret `GEMINI_API_KEY`, `SAVE_PASSCODE` | 保存時 runtime で Gemini 呼び出し（`site/functions/_lib/gemini.ts`） |

**秘密情報:** `.env` / `config/secrets/*` は gitignore。API キー・Webhook・service account JSON・X 認証を commit しない。

---

## 9. 運用・耐障害設計

- **サーキットブレーカー**（`circuit_breaker.py`）: X 連続失敗 3 回で遮断。手動リセットは Variables `BREAKER_RESET=x_twscrape` を入れて1回実行後に空へ戻す。
- **Gemini 無料枠保護**: `llm_client` がモデル別 RPM 制限。`process_digest` は分類 chunk が連続で空になると quota 切れとみなし早期停止。`maintenance_monthly` は直近30日が50件未満なら AI 分析スキップ。
- **データ保持**（settings.toml `[retention]`）: `raw_days=60` / `logs_days=30` / `processed_days=60`。`data/cache/` は自己プルーニング。
- **通知スロットル**: 同一エラーは30分窓、priority は24時間窓で重複抑制。

### 既知の注意点（落とし穴）

- `storage.py` は processed を `data/processed/<date>/items.jsonl` に書くが、`scripts/build_site_data.py` の `processed_files()` は `data/processed/*.jsonl` を glob している。サイト生成を直すときはこの配置差を確認。
- X 収集は DC（データセンター）IP だと 403 になるため、ローカル Mac 経路（`scripts/run_x_local.sh` 等）へ逃がす運用実績あり。
- `.venv`（メイン）と `.venv-x`（X 収集用）の 2 環境が存在。

---

## 10. ローカル実行コマンド

```bash
# セットアップ
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 値を埋める（コミット禁止）

# 収集（DRY_RUN で外部書き込み抑制）
DRY_RUN=true python -m src.jobs.collect realtime|hourly|6h|daily

# 処理・通知・レポート
DRY_RUN=true python -m src.jobs.process_digest
DRY_RUN=true python -m src.jobs.notify_priority
DRY_RUN=true python -m src.jobs.report_weekly
DRY_RUN=true python -m src.jobs.maintenance_monthly

# 管理
python -m src.admin.health
python -m src.admin.init_notion_schema
python -c "from src.llm_client import quota_status; import json; print(json.dumps(quota_status(), indent=2, ensure_ascii=False))"

# サイト
python scripts/build_site_data.py
cd site && npm ci && npm run build   # ローカルプレビューは npm run dev
```

---

## 11. カスタマイズ箇所

| やりたいこと | 触る場所（コード不要なものも多い） |
|---|---|
| 監視対象を増減 | `config/watchlist.csv`（正本） |
| 分類ルール変更 | `src/prompts.py` |
| カテゴリ追加 | `src/taxonomy.py` |
| モデル切替 | `config/settings.toml [models]` |
| スコア重み調整 | `config/settings.toml [scoring]` |
| スケジュール変更 | `.github/workflows/*.yml` の cron |

---

詳細なセットアップ手順は [../../SETUP.md](../../SETUP.md)、Claude Code 作業ルールは [../../CLAUDE.md](../../CLAUDE.md) を参照。
