# info-collector 公開パーソナライズ版 — 実現可能性検討 & プランニング

> ⚠️ 本書は **企画・実現可能性の検討ドキュメント**です。本番実装はまだ行いません。
> 「作れるか / いくらかかるか / 何が危ないか / どの順で確かめるか」を判断するための資料。
> 決定の背景は ADR 0003（Obsidian: `ADR/0003-info-collector-公開パーソナライズ版...`）参照。

---

## 1. やりたいこと（ゴール）

個人用の固定フィードを、**誰でも使えるパーソナライズ情報配信サービス**にする。

- ユーザーは自分の興味を選ぶ（例: 「日本のゲーム/アニメ/Disney」「生成AI」「サッカーだけ」）
- そのトピックの情報を集めて **AI が要約・重要度づけ**
- **メール(Gmail)と Discord** でその人向けに通知、サイトでも閲覧
- ログイン: **Google / メールアカウント**

## 2. 前提（確定した方針）

| 項目 | 決定 |
|---|---|
| 情報源 | **YouTube 公式 API + RSS（Google News 検索RSS 含む）+ 自作要約**。**X スクレイピングは使わない**（公開版）。 |
| パーソナライズ | ユーザーが任意ジャンル/キーワードを選択（A+ 発展形） |
| 収集モデル | **トピック単位の共有収集**（ユーザー単位で集めない） |
| 通知 | メール / Discord |
| 認証 | Google / メール |
| コスト方針 | 月額ほぼ0円を維持（超える要因を事前に特定・抑制） |

## 3. 実現可能性の核心：なぜ成立するか

### 3.1 任意ジャンルを安く・合法に集める
- **Google News 検索RSS**: `https://news.google.com/rss/search?q=<キーワード>&hl=ja&gl=JP&ceid=JP:ja`
  → 任意キーワード・任意言語のRSSが**無料で即生成**。「サッカーだけ」も1行で対応可能。
- **YouTube Data API `search.list`**: キーワード動画収集（既存 `youtube_search.py`）。※quota消費に注意（後述）。
- どちらも既存 collector（`rss_generic` / `youtube_search`）を流用でき、新規開発は薄い。

### 3.2 コストをユーザー数に比例させない鍵
**「トピック(ジャンル/キーワード)」をキーに1回だけ収集・要約 → 購読者全員に配る。**

```
ユーザーA: [ゲーム, アニメ]          topic:ゲーム  ──┐
ユーザーB: [ゲーム, サッカー]   →   topic:アニメ  ──┼─→ 各topicを1回収集・要約
ユーザーC: [サッカー, 生成AI]        topic:サッカー ─┤    → 購読者に配信
                                     topic:生成AI  ──┘
```
同じ「サッカー」を100人が選んでも収集・要約は1回。**収集はユーザー数でなく“異なるトピック数”に比例**。

## 4. アーキテクチャ案（既存資産の再利用）

```
[GitHub Actions cron]  ── 既存パイプラインを topic 駆動に拡張
   collectors (youtube_rss / youtube_search / rss_generic / GoogleNewsRSS)
     └─ topic ごとに収集 → 正規化(RawItem)
   processors (classify / 要約)
     └─ topic 単位で重要度づけ + 自作要約（top-N のみ）
   ↓
[Cloudflare D1]  ── users / subscriptions / topics / items / notify_log
   ↓
[Pages Functions]  ── オンボーディング, 認証, 購読管理, フィードAPI
   ↓
[配信] メール(Gmail/送信API) / Discord / サイト表示
```

再利用できるもの: 既存の collector 群・分類/スコアリング・Astro サイト・D1・Pages Functions。
新規に要るもの: 認証、topic/購読データモデル、topic 駆動の収集ループ、per-user 配信、オンボUI。

### データモデル案（D1）
- `users(id, email, auth_provider, created_at)`
- `topics(id, kind[genre|keyword], query, source_pack, created_at)`
- `subscriptions(user_id, topic_id, notify_email, notify_discord, min_importance)`
- `items(id, topic_id, url, title, summary, importance, published_at, dedup_key)`
- `notify_log(user_id, item_id, channel, sent_at)`  ← 重複通知防止

## 5. コストの正直な見積もりと抑制策

X 除去後、**新しいコスト主因は Gemini 要約量**。ユーザー数でなく **「異なるトピック数 × 件数」** に比例。

| コスト要因 | スケール | 抑制策 |
|---|---|---|
| Gemini 要約/分類 | 異なるトピック数 × 件数 | 重要度 **top-N のみ要約** / 1呼び出しに複数件バッチ / 閲覧時に遅延生成 |
| YouTube Data API | search は 1回=100 quota（無料 10,000/日） | RSS 優先、search は人気トピックのみ / 頻度を落とす |
| Google News RSS | 無料 | フェッチ頻度の上限設定 |
| メール送信 | 通知数（無料枠: 例 Resend 100通/日） | 日次ダイジェストにまとめる / Discord を主、メールは従 |
| Cloudflare D1/Pages | 行数・リクエスト（無料枠広い） | 保持期間で prune |

**結論**: 収集は安いまま。詰まるのは「ニッチkeywordが増えたときの要約量」と「メール無料枠」の2点のみで、いずれも設計で抑制可能。

## 6. リスクと対応（プリモーテム反映）

| リスク | 状態 | 対応 |
|---|---|---|
| X 規約・著作権 | ✅ 解消 | X を公開版から除外。配信は「タイトル+リンク+自作要約」に限定 |
| 需要（他人が使うか） | ❌ **未検証** | **Phase 0 スモークテスト**で先に測る |
| Discord 通知の per-user 実現 | ⚠ 要確認 | 個人版はサーバー直投稿で可。公開版は各自 webhook 登録 or bot DM の摩擦を要検証 |
| 要約コスト膨張 | ⚠ 管理対象 | top-N/バッチ/遅延生成 |
| 個人情報保持 | ⚠ 新規義務 | プラポリ・退会/削除フロー・最小限保持 |
| 個人運用の運用負荷 | ⚠ | 問い合わせ/障害/モデレーションを最小化する設計（自動化前提） |

## 7. 段階プラン（実装は各フェーズのGoゲート通過後）

- **Phase 0 — 需要計測（コード最小）**: 公開サイトに「ジャンル/キーワード選択 + メール登録」オンボUIだけ設置（フェイクドア）。配信ロジックは作らない。**他人が実際に登録するか**を測る。UIは本実装に流用。
  - Go条件: 意味のある登録数/継続意向が得られる。
- **Phase 1 — MVP**: Googleログイン + topic共有収集 + top-N要約 + 日次メール/Discord通知。ジャンルは curated pack 数個 + 代表keyword。
- **Phase 2 — 拡張**: keyword自動ソース化の一般化、通知チューニング、（必要なら）課金/上限設計。

## 8. いま出せる結論（Go / Pivot / Stop）

- **技術的実現性: 高**（既存資産流用 + Google News RSS が任意ジャンルの鍵。新規開発は認証・データモデル・配信層に限定）
- **コスト実現性: 中〜高**（トピック共有設計なら月額0円圏を維持可能。要約量とメール枠だけ要監視）
- **法務: 解消済み**（X除外・要約配信に限定）
- **最大の未知: 需要**。→ **Phase 0 のスモークテストを最初にやってから本実装を判断**、が推奨結論。

---

現行システムの仕様は [SPEC.md](SPEC.md)、やさしい概要は [OVERVIEW.md](OVERVIEW.md) を参照。
