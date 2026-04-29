# info-collector

X / YouTube / Twitch から推しジャンルの情報を自動収集し、Gemini が分類・要約して
Notion / Google Sheets / Discord / Markdown に配信するパイプライン。

GitHub Actions の cron で完全自動化、**Google Gemini API の無料枠だけ**で運用可能。

## 機能

- **収集**: X (twscrape)、YouTube (RSS)、Twitch API、汎用 RSS
- **分類**: タクソノミー約50カテゴリで Gemini が自動分類
- **重要度判定**: S/A/B/C で振り分け、S/A は Discord に即時通知
- **多重出力**: Notion DB（ジャンル別）、Google Sheets、Markdown、Discord
- **トレンド分析**: 週次レポート、月次メンテレポート
- **エラー耐性**: サーキットブレーカー、graceful degradation、レート制限スロットル
- **完全無料**: Gemini無料枠 + GitHub Actions無料枠で月額0円運用

## アーキテクチャ

```
[GitHub Actions cron]
   ↓
[コレクター] → data/raw/ にJSONL保存（git commit）
   ↓
[プロセッサー] → Gemini APIで分類・要約 → data/processed/
   ↓
[出力] Notion / Sheets / Discord / docs/digests/
```

## ディレクトリ構成

```
info-collector/
├── .github/workflows/    # 7本のcronワークフロー
├── src/
│   ├── collectors/       # X, YouTube, Twitch, RSS
│   ├── processors/       # 分類, ダイジェスト生成
│   ├── outputs/          # Notion, Sheets, Discord, Markdown
│   ├── jobs/             # ワークフローのエントリポイント
│   ├── llm_client.py     # Gemini API ラッパー（throttle込み）
│   ├── watchlist.py      # Sheets/CSVから監視対象読み込み
│   ├── taxonomy.py       # サブカテゴリ定義
│   ├── prompts.py        # 全プロンプト
│   ├── dedup.py          # 重複検知
│   ├── circuit_breaker.py
│   ├── storage.py        # JSONL I/O
│   ├── models.py         # Pydanticモデル
│   ├── logger.py
│   └── config.py
├── config/
│   ├── settings.toml     # モデル選択、リトライ等
│   └── watchlist.csv     # 監視対象一覧（Sheetsの代替/キャッシュ）
├── data/
│   ├── raw/              # コレクター生データ（.gitignore対象を除き保存）
│   ├── processed/        # 分類済みデータ
│   ├── cache/            # dedup_keys, api_usage 等
│   └── logs/             # JSONL構造化ログ
├── docs/
│   ├── digests/          # 日次ダイジェスト
│   ├── weekly/           # 週次レポート
│   └── monthly/          # 月次メンテ
└── requirements.txt
```

## セットアップ

詳細は [SETUP.md](SETUP.md) を参照。要点だけ:

1. GitHub にプライベートリポジトリ作成、このコードを push
2. GitHub Secrets に必要なキーを設定（[SETUP.md](SETUP.md)に一覧）
3. Notion DB 2つ作成（ゲーム用・アニメ用）。スキーマは [SETUP.md](SETUP.md) 参照
4. Google Sheets 作成、サービスアカウントに共有
5. Discord サーバーに3チャンネル + Webhook作成
6. ワークフローを `Actions` タブで手動キック (`workflow_dispatch`) してテスト
7. cron スケジュールが自動で回り始める

## 動作確認 (ローカル)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 値を埋める
DRY_RUN=true python -m src.jobs.collect hourly
DRY_RUN=true python -m src.jobs.process_digest
```

`DRY_RUN=true` で外部書き込みを抑制。

## カスタマイズ

- **監視対象を増やす**: Google Sheets の `watchlist` シートを編集（コード触らず）
- **分類ルール変更**: `src/prompts.py` のテンプレートを編集
- **新カテゴリ追加**: `src/taxonomy.py` の文字列に追加
- **モデル変更**: `config/settings.toml` で各処理のモデルを切替
- **スケジュール変更**: 各 `.github/workflows/*.yml` の cron 式を編集

## トラブルシューティング

| 症状 | 確認ポイント |
|---|---|
| ワークフローが失敗続き | Actions タブのログ → エラーコード（例: E_X_AUTH_001）を SETUP.md と照合 |
| X が全件失敗 | サーキットブレーカー作動の可能性。`vars.BREAKER_RESET=x_twscrape` で解除 |
| Gemini quota超過 | 1500回/日 (Flash) を超えた場合は翌UTC日まで待つ。Discordに警告通知 |
| Notion書き込み失敗 | DBプロパティ名・型が SETUP.md の指定と一致しているか |
| 収集はOKだが分類0件 | `data/raw/` には溜まっているのに `data/processed/` が空 → process_digest を手動キック |

## ライセンス

個人利用前提。各APIの利用規約に従ってください。
特にX scrapingは利用規約上グレーなので、低頻度・個人利用に留めてください。
