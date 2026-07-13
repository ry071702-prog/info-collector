# AI 再構築プロンプト — info-collector をゼロから作らせる

このドキュメントは、**Claude Code / Codex / Cursor などのコーディングAIに丸ごと貼り付けて**、
info-collector 相当のシステムをゼロから作らせるためのマスタープロンプトです。

使い方:
1. 新しい空ディレクトリで AI コーディングエージェントを起動
2. 下の「===== ここから貼り付け =====」以降をそのまま貼る
3. AI が質問してきたら（API キーの有無など）答える
4. 段階ごとに動作確認（`DRY_RUN=true`）しながら進める

> 補足: 似て非なるものを作りたい場合は、末尾「カスタマイズ指示の例」を書き換えてください。

---

===== ここから貼り付け =====

あなたはシニア Python エンジニアです。以下の仕様で **個人用の情報収集・配信パイプライン** をゼロから実装してください。サーバー常駐なし・GitHub Actions cron 駆動・**Gemini API 無料枠だけで月額ほぼ0円**で回ることが絶対要件です。

## 作るもの（1行）
X / YouTube / Twitch / RSS から指定ジャンル（例: ゲーム・アニメ・Disney）の情報を収集し、Gemini で分類・要約・スコアリングして、Notion / Google Sheets / Discord / Markdown / 静的サイトへ配信するパイプライン。

## 設計原則（必ず守る）
1. **無料枠厳守**: 有料 LLM / 新規課金サービスを足さない（無料枠サービスは可）。Gemini は無料枠前提。
2. **部分失敗で止めない（graceful degradation）**: 1ソース/1出力先の失敗は握りつぶしてログに残し、後続を続行。
3. **DRY_RUN 尊重**: `DRY_RUN=true` で全ての外部書き込み（Notion / Sheets / Discord post）を抑制。
4. **設定駆動**: モデル選択・スコア重み・閾値・保持期間は TOML で変更でき、コード再デプロイ不要にする。
5. **監視対象はデータで管理**: 収集対象は CSV を正本にし、コードを触らず増減できる。
6. **秘密情報は env / GitHub Secrets**: `.env` と `config/secrets/*` は gitignore。鍵やWebhookをコミットしない。

## 技術スタック
Python 3.12 / `google-genai` / `twscrape`(X) / `feedparser`+`httpx`+`selectolax`(RSS) / `gspread`+`google-auth`(Sheets) / `notion-client`(Notion, **API バージョン `2022-06-28` 固定**) / `pydantic` / `tomli` / `python-dotenv` / `tenacity` / `loguru`。サイトは Astro 6 + Tailwind 4 + Node 20、必要なら Cloudflare Pages Functions + D1。

## ディレクトリ構成
```
src/
  config.py          # env/settings アクセサ: env, env_json, env_bool, is_dry_run, settings
  models.py          # Pydantic モデル
  llm_client.py      # Gemini ラッパー: call_json, call_text, RPM throttle, 日次カウント, quota_status
  storage.py         # JSONL I/O
  watchlist.py       # config/watchlist.csv を正本として読む
  taxonomy.py        # サブカテゴリ体系（ジャンルごとに文字列）
  prompts.py         # 全プロンプト本文を集約
  dedup.py           # 重複検知（dedup_key を7日保持）
  circuit_breaker.py # 連続失敗で遮断
  logger.py          # loguru 構造化ログ
  collectors/        # x_twscrape, x_search, youtube_rss, youtube_search, youtube_trending, twitch_api, rss_generic
  processors/        # classify（2段階）, digest（日次/週次本文）
  outputs/           # notion, sheets, discord, markdown
  jobs/              # collect, process_digest, notify_priority, report_weekly, maintenance_monthly
  admin/             # health, init_notion_schema, prune_notion_schema
config/
  settings.toml      # models / batch_sizes / retry / circuit_breaker / notification_throttle / collectors / retention / scoring
  watchlist.csv      # 監視対象の正本
data/
  raw/<date>/<source_id>.jsonl     # RawItem
  processed/<date>/items.jsonl     # ProcessedItem
  cache/  logs/<date>.jsonl
docs/ digests|weekly|monthly       # Markdown 出力
.github/workflows/                 # cron
.env.example  requirements.txt  README.md  SETUP.md
```

## データモデル（`models.py`）
```python
Genre      = Literal["games","anime","disney","both","neither"]
Importance = Literal["S","A","B","C"]
SourceRole = Literal["公式","メディア","個人","リーカー","大会","VTuber"]

WatchSource: id,name,handle,url,platform,genre,source_type,subcategory_hints[],priority,enabled,check_frequency,language,notes
  platform = X|YouTube|Twitch|RSS|Web|YouTubeSearch|YouTubeTrending|XSearch
  check_frequency = realtime|hourly|6h|daily

RawItem: source_id,platform,author,account_type,text,url,timestamp,extra{}
  fingerprint プロパティ = url or f"{author}|{timestamp}"

FilterResult: spam:bool, genre, confidence:float, reason

Flags: source_role, speed(速報/通常/アーカイブ), spoiler(なし/軽微/重大), language,
       content_type(text/image/video/live),
       source_reliability(公式確定/公式予告中/信頼リーカー/噂/二次), cross_genre

ProcessedItem: source_id, raw_fingerprint, timestamp, url, author, genre,
  subcategory_id, category_name, importance, summary, title_tags[], entity_tags[],
  flags, dedup_key, raw_text,
  # スコアリング(各0-100): risk_level, streamer_influence_score, clip_virality_score,
  #   game_trend_from_streamers_score, live_trend_score, video_trend_score, freshness_score
  final_priority(S/A/B/C),
  # 文脈メタ: streamer_name, streamer_group, is_clip, related_game_title, related_anime_title
```

## パイプライン
### 収集（`jobs/collect.py`）— tier で lookback と対象を変える
| tier | lookback | 対象 |
|---|---|---|
| realtime | 1h | check_frequency==realtime |
| hourly | 4h | realtime/hourly |
| 6h | 8h | realtime/hourly/6h |
| daily | 30h | 全部 |

各 collector は `collect(sources, since)->list[RawItem]`。自 platform のソースだけ処理、ソース単位失敗はログして継続。出力は `data/raw/<date>/<source_id>.jsonl`。

### 分類（`processors/classify.py`）— 2段階
1. `filter_and_genre`: スパム判定 + ジャンル判定（軽量モデル）
2. `classify_full`: taxonomy 注入で詳細分類 + スコアリング
- `both` は games→anime 両方分類し重要度が高い方を採用、`disney` は DISNEY_TAXONOMY を使用。

### スコアリング（`settings.toml [scoring]`）
`final_priority` = 重み付き合成（合計1.0）:
importance 0.5 / freshness 0.2 / streamer 0.15 / virality 0.10 / trend 0.05 / live 0.10 / video 0.10。
閾値 S=80 / A=60 / B=35（0-100）。鮮度: 24h=100/72h=70/1週=40/以降=10 を線形補間。

### 重複排除（`dedup.py`）
fingerprint(url or author|timestamp) で raw をスキップ。dedup_key を 7日保持。Discord 通知は 24時間保持。

### 出力（`outputs/`）
- Notion: genre 別 DB にページ作成。基本プロパティ Title/Importance/Category/Genre/URL/Author/Timestamp/**TagsText(rich_text)**/Spoiler/Source/DedupKey。**タグは絶対に multi_select にしない**（unique option が schema 上限 ~489KB に達し全書き込みが落ちる）。存在しないプロパティは schema 取得できたら落とす。
- Sheets: ジャンル別 worksheet に append。
- Discord: priority(S/A即時) / ops(運用) / alerts(障害) の3 Webhook。
- Markdown: docs/digests|weekly|monthly。

## ジョブ（`jobs/`）
- `collect.py`(tier 引数) / `process_digest.py`(当日 raw→無ければ前日にフォールバック) / `notify_priority.py`(直近 raw を簡易分類しS/Aのみ通知) / `report_weekly.py`(直近7日) / `maintenance_monthly.py`(月次統計+古い raw/log 削除、直近30日<50件ならAI分析スキップ)。

## 設定（`config/settings.toml`）
```toml
[models]   # 無料枠で。JSON出力系は thinking なしの軽量モデルを使う
filter = classify = dedup = "<軽量・JSON安定モデル>"
digest = "<中位>"; weekly_report = maintenance = "<上位>"
[batch_sizes] classify_batch=50; dedup_batch=50
[retry] network_max=3; ratelimit_max=5; backoff_base=2.0; backoff_max=300; jitter_pct=0.2
[circuit_breaker] x_consecutive_failures=3; notion_failure_rate_24h=0.5
[notification_throttle] same_error_window_minutes=30; priority_dedup_window_hours=24
[collectors.x] tweets_per_user_max=50
[collectors.youtube] rss_entries_max=15
[collectors.twitch] recent_streams_max=10; recent_videos_max=5
[retention] raw_days=60; logs_days=30; processed_days=60
[scoring] # 上記の重み・閾値・鮮度
```

## GitHub Actions（`.github/workflows/`）
| workflow | cron | コマンド |
|---|---|---|
| collect_realtime | 30分ごと | collect realtime |
| notify_priority | 30分ごと | notify_priority |
| collect_regular | 3時間ごと | collect 6h |
| collect_daily | 22:00 UTC | collect daily |
| process_digest | 22:00 UTC | process_digest |
| report_weekly | 日 23:00 UTC | report_weekly |
| maintenance_monthly | 毎月1日 00:00 UTC | maintenance_monthly |

各 workflow は生成物を `git pull --rebase --autostash` 後に commit/push。Workflow permissions は Read and write。

## 環境変数（`.env.example` に列挙）
`GEMINI_API_KEY` / `X_ACCOUNTS`(JSON配列, 空ならX収集スキップ) / `YOUTUBE_API_KEY` / `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` / `GOOGLE_SHEETS_CREDENTIALS`(service account JSON) / `GOOGLE_SHEETS_ID` / `NOTION_TOKEN` / `NOTION_DATABASE_ID_GAMES|ANIME|DISNEY` / `DISCORD_WEBHOOK_PRIORITY|OPS|ALERTS` / `DRY_RUN`。

## 実装の進め方（この順で、各段で DRY_RUN 動作確認）
1. `config.py` / `models.py` / `logger.py` / `storage.py` の土台
2. `llm_client.py`（throttle + quota_status）と `prompts.py` / `taxonomy.py`
3. collectors を1つずつ（まず youtube_rss → rss_generic は API キー不要で検証しやすい）
4. `jobs/collect.py` で raw が貯まることを確認
5. `processors/classify.py` → `jobs/process_digest.py`
6. outputs（markdown → discord → sheets → notion の順、DRY_RUN で）
7. `.github/workflows/` と `SETUP.md`
8. （任意）Astro サイト

各段で「外部キー無しでも import / 簡易実行が通る」ことを確認。テストは env 無し前提（`monkeypatch.setenv`）で書く。

## カスタマイズ指示の例（ここを書き換えると別物になる）
- ジャンルを変える: `Genre` Literal と `taxonomy.py`、`watchlist.csv` の genre を差し替え。
- 配信先を減らす: 不要な `outputs/*` と env を削る（例: Notion だけにする）。
- スコアリング不要: ProcessedItem の β フィールドと `[scoring]` を省き importance をそのまま final_priority に。

===== ここまで =====
