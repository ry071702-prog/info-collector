# Claude Code 向けプロジェクト案内

このファイルは Claude Code が起動時に自動的に読み込みます。
このリポジトリで作業する際の前提・規約・状態を記載しています。

---

## プロジェクト概要

**info-collector**: X / YouTube / Twitch から「ゲーム&esports」「アニメ&漫画」の情報を
自動収集し、Gemini で分類・要約して Notion / Google Sheets / Discord / Markdown に
配信するパイプライン。GitHub Actions の cron で完全自動化。

## 重要な前提

- **完全無料運用が必須**: Gemini API は無料枠のみ。Anthropic API などの**有料サービスは絶対に追加しない**
- **個人プロジェクト**: ユーザー1人が運用。複雑な認証・ロール管理は不要
- **データの取りこぼし最小化を優先**: graceful degradation / 部分故障で全体停止させない

## 開発の進め方

このプロジェクトは Cowork で設計・スキャフォールドが完成済み。
ここから先は **セットアップ → ローカル動作確認 → GitHub push → 本番稼働** のフェーズ。

ユーザーは Python やシェル操作はある程度できるが、毎回最善のコマンドを覚えているわけではない。
**コマンドは省略せず正確に提示**し、想定する出力も簡単に伝える。

## 技術スタック

- Python 3.12
- `google-generativeai` (Gemini API)
- `twscrape` (X/Twitter スクレイピング)
- `feedparser` (YouTube/RSS)
- `gspread` (Google Sheets)
- `notion-client`
- `httpx`, `pydantic`, `tenacity`, `loguru`, `tomli`
- GitHub Actions (cron)

## アーキテクチャ

```
[GitHub Actions cron]
   ↓
[コレクター: src/collectors/] → data/raw/ にJSONL
   ↓
[プロセッサー: src/processors/] → Geminiで分類・要約 → data/processed/
   ↓
[出力: src/outputs/] → Notion / Sheets / Discord / docs/digests/
```

## ディレクトリ構成

```
src/
├── llm_client.py        # Gemini APIラッパー（throttle込み）。LLM呼び出しはここを通す
├── claude_client.py     # llm_clientへの薄いリダイレクト（互換用、編集不要）
├── config.py            # settings.toml / .env 読込み
├── logger.py            # loguru ベースの構造化ログ
├── models.py            # Pydanticモデル（WatchSource/RawItem/ProcessedItem 等）
├── watchlist.py         # Google Sheets / CSV から監視対象読込み
├── taxonomy.py          # 分類カテゴリの文字列定数
├── prompts.py           # Geminiに渡す全プロンプト
├── dedup.py             # dedup_keyベースの重複検知
├── storage.py           # JSONL I/O
├── circuit_breaker.py   # サーキットブレーカー
├── collectors/          # x_twscrape, youtube_rss, twitch_api, rss_generic
├── processors/          # classify, digest
├── outputs/             # notion, sheets, discord, markdown
└── jobs/                # 各cronジョブのエントリポイント

config/
├── settings.toml        # モデル選択、リトライ、バッチサイズ等
└── watchlist.csv        # 監視対象（Sheets未接続時のフォールバック）

.github/workflows/       # 7本のcronワークフロー
data/                    # 生データ・処理済データ・キャッシュ
docs/                    # 生成されたMarkdown（digest/weekly/monthly）
```

## よく使うコマンド

```bash
# 仮想環境セットアップ
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 環境変数ファイル準備
cp .env.example .env
# → .env を編集して各APIキーを入れる

# DRY_RUN（外部書き込みなしで動作確認）
DRY_RUN=true python -m src.jobs.collect hourly
DRY_RUN=true python -m src.jobs.process_digest
DRY_RUN=true python -m src.jobs.notify_priority

# 本番実行
python -m src.jobs.collect realtime
python -m src.jobs.process_digest

# Gemini無料枠の使用量確認
python -c "from src.llm_client import quota_status; import json; print(json.dumps(quota_status(), indent=2))"
```

## カスタマイズの仕方

| 何を変えたいか | どこを編集 |
|---|---|
| 監視対象を増やす | Google Sheetsの`watchlist`シート（コード触らず） |
| 分類ルール調整 | `src/prompts.py` |
| 新カテゴリ追加 | `src/taxonomy.py` |
| モデル切替 | `config/settings.toml` |
| cronスケジュール | `.github/workflows/*.yml` |
| リトライ・スロットル | `config/settings.toml` の`[retry]`セクション、`src/llm_client.py`の`RPM_LIMITS` |

## 設計ドキュメント

詳細は親フォルダ（情報収集ルート）にも以下のファイルがあります（参考用、編集対象外）:

- `分類タクソノミー_詳細版.md` - 全カテゴリの完全リスト（チェックボックス形式）
- `ウォッチリスト_設計.md` - 監視対象の3層構造設計
- `プロンプト集_最終版.md` - 全プロンプトの設計理由
- `エラーハンドリング設計.md` - エラーマトリックス・サーキットブレーカー仕様

## セットアップ進捗

ユーザーが進めている `SETUP.md` のチェックリストを基準に進捗を確認してください。
セッション開始時に「今どこまで終わってる？」と聞くか、`.env` の存在確認・GitHub remote の確認・最新コミットなどから推測。

## 作業時の注意

1. **既存ファイルの構造を尊重する** - 大幅リファクタは避け、追記・調整中心に
2. **命名規約**: snake_case / 日本語コメントOK / 型ヒント必須
3. **新しい依存追加は慎重に** - requirements.txt が膨らまないように
4. **プロンプト編集は `src/prompts.py` で完結** - 他に散らばらせない
5. **コミットメッセージは日本語OK**
6. **シークレット (.env, *.json) を絶対にコミットしない** - .gitignoreに反映済みだが必ず確認
7. **動作確認は DRY_RUN=true から** - 外部書き込みするコマンドはユーザーに確認してから

## 不明な状況に遭遇したら

- 設計ドキュメント（親フォルダの `*.md`）を参照
- ユーザーに「これは仕様 or 不具合？」を確認
- 推測で書き換えない
