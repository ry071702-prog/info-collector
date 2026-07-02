# Phase 1 計画 — 無料プランMVP（実装前のプランニング）

> ⚠️ 本書は **実装前の計画**です。本番実装はまだ行いません。
> 位置づけ: [MULTIUSER_DESIGN.md](MULTIUSER_DESIGN.md) の Phase 1 を具体化。ADR 0003 の決定に準拠。
> 対象: 全世界の一般人 / カタログ制ジャンル / operator-key + topic共有 / 日次メール配信 / Googleログイン。
> 調査日: 2026-07（無料枠・価格は変動するため実装直前に再確認）。

---

## 1. ジャンルカタログ（初期セット v0 — 約120ジャンル）

「よくあるジャンルを多数提示して選ばせる」ための初期カタログ案。既存タクソノミー（games/anime/disney）を核に、共通の人気ドメインへ拡張。
各ジャンルは内部的に **topic**（= Google News検索RSS のクエリ + YouTube search クエリ + curated RSS/YTソース）へマップする。

> 運用: まずは上位カテゴリごとに数ジャンルで小さく始め、需要を見て増やす。全部を初日に作らない。

### 🎮 ゲーム（既存タクソノミー活用）
Nintendo / PlayStation / Xbox / PCゲーム(Steam) / インディーゲーム / 新作・発売情報 / セール・無料配布 / eSports全般 / VALORANT / League of Legends / ストリートファイター/格ゲー / Apex・FPS / 原神・ホヨバ / ポケモン / スマブラ / マイクラ / 最新アップデート・パッチ / 実況・配信者

### 📺 アニメ・漫画（既存タクソノミー活用）
新作アニメ / 続編・2期情報 / 声優 / 少年ジャンプ / 漫画新刊 / 円盤・配信 / アニメ映画 / グッズ・フィギュア / イベント・舞台 / コミケ・同人 / VTuber / ホロライブ / にじさんじ

### 🏰 Disney・映画・海外ドラマ（既存タクソノミー活用）
Disney公式 / Marvel / Star Wars / Pixar / Disney+ / 洋画全般 / 邦画 / Netflix / Amazon Prime Video / 海外ドラマ / 映画館・興行

### ⚽ スポーツ（新規）
サッカー全般 / **Jリーグ** / **プレミアリーグ** / **ラ・リーガ** / **チャンピオンズリーグ** / 日本代表(サッカー) / 野球全般 / MLB / プロ野球(NPB) / NBA・バスケ / テニス / F1・モータースポーツ / ゴルフ / 格闘技・ボクシング / 大相撲 / オリンピック

> ※「サッカーだけ」「プレミアだけ」の粒度で選べるよう、スポーツは細分化しておく（要望例に直結）。

### 🤖 テクノロジー・AI（新規）
生成AI / ChatGPT・OpenAI / Claude・Anthropic / Google Gemini / AI開発ツール / スマホ・ガジェット / iPhone・Apple / Android / PC・自作 / Web開発 / プログラミング / スタートアップ / 暗号資産・Web3 / セキュリティ

### 🎵 エンタメ・音楽・カルチャー（新規）
J-POP / K-POP / 洋楽 / ライブ・フェス / アイドル / お笑い / YouTuber / TikTokトレンド / ドラマ(国内) / 声優ラジオ

### 📰 一般・生活（新規・任意）
国内ニュース / 世界ニュース / 経済・マーケット / ガジェット節約・セール / グルメ / 旅行 / 健康・フィットネス

**合計: 約120ジャンル**（上記は v0 の叩き台。カテゴリ単位で ON/OFF し段階投入）

---

## 2. メール送信基盤の選定

日次ダイジェストを各ユーザーのメールへ送る。**無料枠 = 実質「1日に何人へ送れるか」**（日次1通/人なら 上限/日 ≒ 収容ユーザー数）。

| サービス | 無料枠 | 日次換算(1通/人) | 備考 |
|---|---|---|---|
| **Resend** | 3,000通/月（永久）・100通/日 | 〜100人/日 | DX最良・実装が軽い。既存 slack系と相性。小規模MVP向き |
| **Brevo** | 300通/日（9,000通/月） | 〜300人/日 | 無料での日次収容が最大。連絡先10万まで |
| Mailgun | 100通/日（永久） | 〜100人/日 | 定番だが設定やや重い |
| Mailtrap | 4,000通/月 | 〜130人/日 | テスト用途に強い |
| SendGrid | ❌ 60日試用のみ（無料枠廃止） | — | 2026時点で新規無料枠なし。除外 |

**推奨**: MVPは **Resend で開始**（実装が最も軽く、Cloudflare/JSと好相性）。ユーザーが日次100人を超えたら **Brevo（300/日）へ切替**、さらに超えたら有料枠 or 収益化（Phase 3）。
**必須設定（グローバル配信）**: 独自ドメイン + SPF / DKIM / DMARC、**二重オプトイン**（登録確認メール）、全メールに**配信停止リンク**、バウンス処理。

出典: [Resend/SendGrid/Postmark 価格比較](https://www.buildmvpfast.com/api-costs/email) / [Brevo: Best Email API 2026](https://www.brevo.com/blog/best-email-api/) / [SendGrid無料枠廃止](https://dreamlit.ai/blog/best-sendgrid-alternatives)

---

## 3. 認証基盤の選定

要件: **全世界の一般人がGoogleでログイン**、ユーザーは自前D1で保有、Cloudflare(Pages Functions/Workers)上で動く、GDPR等でデータ所在を自分で管理したい。

| 選択肢 | 向き | 判定 |
|---|---|---|
| **Cloudflare Access (Zero Trust)** | 社内アプリのゲート。**無料は50ユーザーまで** | ❌ 一般公開の不特定多数には不適（人数上限・用途違い） |
| **Better Auth + D1** | TS製・V8(Workers)で動く・ユーザーを自分のDBで保有・Google OAuth対応 | ✅ **本命**。データ所在を自分で管理でき、D1連携の実績あり |
| Auth.js (NextAuth) + D1 adapter | 公式D1アダプタあり | ○ 代替。Astro/独自構成との相性を要確認 |
| Clerk | ホスト型で最速。UI部品込み | △ 早く出せるが**米国データ所在**でGDPR懸念・スケール時コスト。当面見送り |

**推奨**: **Better Auth + D1 + Google OAuth**。ユーザーデータを自前D1で保有でき、費用・データ所在を自分で握れる。まず Google ログインのみ、後でメールOTPを追加。
**注意**: Better Auth を Workers で使う際、セッション/DBアダプタの edge 互換に注意（D1直結の構成例が複数存在するのでそれに倣う）。

出典: [Better Auth vs Clerk 2026](https://makerkit.dev/blog/tutorials/better-auth-vs-clerk) / [Better Auth on Cloudflare (Hono)](https://hono.dev/examples/better-auth-on-cloudflare) / [Auth.js D1 adapter](https://authjs.dev/getting-started/adapters/d1) / [Cloudflare Access = Google IdP](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/google/)

---

## 4. Phase 1 データモデル・画面/API・作業順・見積り

### 4.1 データモデル（Cloudflare D1）

```sql
-- ユーザー（Better Auth のテーブルと統合 or 併存）
users(id PK, email, name, auth_provider, created_at, verified_at, unsubscribed_at)

-- ジャンルカタログ（運営が管理・topicへマップ）
genres(id PK, category, name, slug, gnews_query, yt_query, curated_sources_json, enabled)

-- 購読（ユーザー × ジャンル）
subscriptions(user_id FK, genre_id FK, min_importance DEFAULT 'A', created_at, PRIMARY KEY(user_id,genre_id))

-- 収集・要約済みアイテム（topic=genre単位で共有）
items(id PK, genre_id FK, url, title, summary, importance, source, published_at, dedup_key, created_at)

-- 通知ログ（重複配信防止）
notify_log(user_id FK, item_id FK, channel, sent_at, PRIMARY KEY(user_id,item_id,channel))

-- メール配信ダイジェスト履歴（任意）
digests(id PK, user_id FK, sent_at, item_ids_json)
```

要点: `items` は **genre単位で1回だけ**作る（topic共有）。ユーザーへの配信は `subscriptions` × `items` の結合で組み立て、`notify_log` で二重送信を防ぐ。

### 4.2 画面（フロント / Astro + Pages Functions）
- **ランディング**: 価値提案 + 「Googleで始める」
- **オンボーディング**: ジャンルカタログをカテゴリ別に提示 → **複数選択**（X風）→ 登録
- **設定**: 購読ジャンルの追加/削除、重要度しきい値、配信停止、退会
- **フィード(任意)**: 選択ジャンルの最新アイテム一覧（サイト閲覧）
- **メールテンプレ**: 日次ダイジェスト（ジャンル別・重要度順・配信停止リンク付き）

### 4.3 API（Pages Functions）
- `POST /api/auth/*`（Better Auth ハンドラ / Google OAuth コールバック）
- `GET  /api/genres`（カタログ取得）
- `GET/PUT /api/subscriptions`（購読の取得/更新）
- `GET  /api/feed?genre=`（購読フィード）
- `POST /api/unsubscribe`（ワンクリック配信停止・トークン式）
- `GET  /api/me` / `DELETE /api/me`（プロフィール/退会=データ削除）

### 4.4 バッチ（GitHub Actions cron — 既存を拡張）
- **collect（genre駆動）**: 各 enabled genre の gnews_query/yt_query/curated で収集 → 正規化 → dedup → `items`（既存 collector 流用）
- **summarize（top-N）**: genre×当日の未要約 items のうち重要度上位のみ operator-key で要約（既存 classify/digest 流用）
- **send_daily_digest（新規）**: 各ユーザーの購読 × 当日 items を組み立て、未送信分をメール送信 → `notify_log` 記録

### 4.5 作業順（依存順）
1. D1 スキーマ + `genres` カタログ投入（§1 を seed）
2. Better Auth + Google OAuth（ログインできる状態）
3. オンボーディングUI（ジャンル選択 → `subscriptions` 保存）
4. collect を genre駆動に拡張（`items` が貯まる）
5. summarize（top-N・operator-key）
6. send_daily_digest（メール送信 + notify_log）※Resend 疎通・SPF/DKIM
7. 設定/配信停止/退会（法対応の最低限）
8. ランディング + 計測（登録・開封・配信停止率）

### 4.6 ざっくり見積り（実装する場合の目安・1人開発）
| ブロック | 目安 |
|---|---|
| D1スキーマ + カタログ投入 | 0.5〜1日 |
| 認証(Better Auth+Google) | 1〜2日 |
| オンボUI + 購読API | 1〜2日 |
| collect genre駆動化（既存流用） | 1日 |
| summarize top-N（既存流用） | 0.5〜1日 |
| 日次メール配信 + Resend/SPF | 1〜2日 |
| 設定/配信停止/退会 | 1日 |
| ランディング/計測 | 0.5〜1日 |
| **合計** | **約7〜11日**（MVP範囲） |

> 前提: 既存の collector / classify / digest / D1 / Pages Functions を最大流用。ゼロからではない。

---

## 5. Phase 1 の Go 判断に必要な確定事項（実装前チェック）
- [ ] カタログ v0 の初期投入ジャンル（まず何カテゴリ・何件で始めるか）
- [ ] メール: Resend アカウント + 送信元独自ドメイン + SPF/DKIM/DMARC
- [ ] 認証: Better Auth + Google OAuth のCloudflare構成を1本疎通（PoC）
- [ ] 法対応最小: プライバシーポリシー・二重オプトイン・配信停止・退会削除
- [ ] 計測指標の定義（登録数・開封率・配信停止率・継続率）

---

現行システム仕様: [SPEC.md](SPEC.md) / 全体設計: [MULTIUSER_DESIGN.md](MULTIUSER_DESIGN.md) / やさしい概要: [OVERVIEW.md](OVERVIEW.md)
