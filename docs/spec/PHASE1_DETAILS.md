# Phase 1 詳細設計 — カタログ / 認証PoC / メール / 法対応・計測

> ⚠️ **実装前の詳細プランニング**。本番実装はまだ行わない。
> [PHASE1_PLAN.md](PHASE1_PLAN.md) §5 の4項目を具体化。調査日 2026-07（無料枠・API仕様は実装直前に再確認）。

---

## A. ジャンルカタログ確定（topic マッピング付き）

各ジャンル = 1 topic。topic は下記3ソースへ展開する（既存 `rss_generic` / `youtube_search` collector を流用）:
1. **Google News 検索RSS**（任意ジャンルの主力・無料）
2. **YouTube search クエリ**（動画・人気トピックのみ、quota節約）
3. **curated RSS/YT**（公式・大手メディアの固定フィード。質担保。任意）

### A.1 Google News RSS クエリ構文（確定）
ベース: `https://news.google.com/rss/search?q=<QUERY>&hl=ja&gl=JP&ceid=JP:ja`
- 期間: `when:7d`（7日）/ `when:1d` / `when:12h`
- サイト限定: `site:famitsu.com` / 除外: `-噂` / 完全一致: `"完全一致"` / タイトル内: `intitle:サッカー`
- 例（サッカーのプレミアリーグ・日本語・過去1日）:
  `.../search?q=プレミアリーグ+when:1d&hl=ja&gl=JP&ceid=JP:ja`
- 英語圏トピックは `hl=en-US&gl=US&ceid=US:en` に切替（language 列で制御）。

### A.2 カタログ・スキーマ（`genres` テーブルの実データ例）

| slug | category | name | gnews_query | yt_query | curated（例） | lang |
|---|---|---|---|---|---|---|
| games-nintendo | ゲーム | 任天堂 | `任天堂 OR Nintendo when:2d` | `任天堂 Direct` | 任天堂公式YT, ファミ通RSS | ja |
| games-playstation | ゲーム | PlayStation | `PlayStation OR PS5 when:2d` | `PlayStation 発表` | PS Blog RSS | ja |
| games-valorant | ゲーム | VALORANT | `VALORANT when:2d` | `VALORANT アップデート` | 4Gamer VALORANT | ja |
| games-genshin | ゲーム | 原神・ホヨバ | `原神 OR ホヨバース when:2d` | `原神 アップデート` | — | ja |
| anime-new | アニメ | 新作アニメ | `新作アニメ OR アニメ化 when:3d` | `新作アニメ PV` | コミックナタリーRSS | ja |
| anime-jump | アニメ | 少年ジャンプ | `"少年ジャンプ" when:3d` | — | ジャンプ＋公式 | ja |
| anime-vtuber | アニメ | VTuber | `VTuber OR ホロライブ OR にじさんじ when:2d` | `ホロライブ 切り抜き` | — | ja |
| disney-marvel | Disney | Marvel | `Marvel OR マーベル when:3d` | `Marvel trailer` | Marvel公式 | multi |
| disney-starwars | Disney | Star Wars | `"Star Wars" OR スターウォーズ when:3d` | `Star Wars trailer` | — | multi |
| sports-soccer | スポーツ | サッカー全般 | `サッカー when:1d` | `サッカー ハイライト` | — | ja |
| sports-jleague | スポーツ | Jリーグ | `Jリーグ when:1d` | — | Jリーグ公式 | ja |
| sports-premier | スポーツ | プレミアリーグ | `プレミアリーグ when:1d` | — | — | ja |
| sports-ucl | スポーツ | CL | `"チャンピオンズリーグ" when:1d` | — | — | ja |
| sports-npb | スポーツ | プロ野球 | `プロ野球 OR NPB when:1d` | — | — | ja |
| sports-nba | スポーツ | NBA | `NBA when:1d` | `NBA highlights` | — | multi |
| sports-f1 | スポーツ | F1 | `F1 OR フォーミュラ1 when:2d` | — | — | ja |
| tech-genai | テクノロジー | 生成AI | `生成AI OR "ChatGPT" OR Gemini when:1d` | `生成AI 解説` | — | ja |
| tech-apple | テクノロジー | iPhone・Apple | `Apple OR iPhone when:2d` | — | — | ja |
| tech-gadget | テクノロジー | ガジェット | `ガジェット OR 新製品 when:2d` | — | — | ja |
| music-kpop | 音楽 | K-POP | `K-POP when:2d` | `K-POP MV` | — | ja |
| music-jpop | 音楽 | J-POP | `J-POP OR 新曲 when:2d` | — | — | ja |
| news-japan | 一般 | 国内ニュース | `ニュース when:12h` | — | NHK RSS | ja |

> これは **代表22件の確定例**。残り（PHASE1_PLAN §1 の全120件）は同じルールで機械的に展開できる。
> **生成規則**: `gnews_query = <ジャンル名/主要キーワードを OR> + when:<粒度>`、更新頻度が高いジャンル（スポーツ/ニュース）は `when:12h〜1d`、遅いジャンル（アニメ新作等）は `when:3d`。

### A.3 初期投入の段取り（初日に全部作らない）
- **v0.1（ローンチ）**: 自分の強み領域＝ゲーム/アニメ/Disney の 20〜25 ジャンル + スポーツ(サッカー中心) 6 + テック(生成AI) 3 ≒ **約30ジャンル**。
- 需要（購読数）を見て、反応の良いカテゴリから追加。curated ソースは人気ジャンルだけ後付け。

### A.4 収集の「安い前処理層」（Gemini前・実測で確定）

2026-07-04 の収集PoC（要約なし・代表7ジャンル・実データ482件）で、**Gemini に渡す前の安い前処理だけでノイズを約31%除去**できることを確認した。要約件数が減る＝**Geminiコストが直接下がる**ため、この層を正式な設計要素にする。

適用順（すべてルールベース・LLM不使用）:
1. **グローバル・ブロックリスト**: SEOスパム/無関係の常連ソースを除外（PoCで観測: `Mshale`, `richardajkeys`, `fanpiece` 等）。運用で追記していく。
2. **YouTube個人配信の除外**: 動画主体でないジャンルは source が YouTube のものを落とす。
3. **同一ドメイン上限**（既定 5件/ジャンル）: **最も効く単一ルール**。1アグリゲータの寡占を防ぐ（PoC: 原神で GameWith 等 51件をカット、100→39）。

実測（raw→有効 / 除去率）: 原神 100→39(61%) / Jリーグ 100→67(33%) / 生成AI 100→79(21%) / 新作アニメ 100→80(20%) / プレミア 35→25 / VALORANT 38→32 / **合計 482→331（31%除去）**。

**クエリ設計の教訓**（PoCで判明）:
- キーワード衝突は `-除外` で潰す（例: `プレミアリーグ -U-11 -少年 -ユース`）。
- **精緻化は絞りすぎ注意**（`国内ニュース` を `intitle:速報 when:6h` にしたら9件まで枯れた）。
- **広域ジャンル（国内ニュース/世界ニュース等）はキーワードでなく curated ソース（NHK等の固定RSS）で持つ**方が安定。
- 更新の速いジャンルは `when:12h〜1d`、遅いジャンルは `when:3d`。

> この前処理は既存 `dedup` / `classify` の**前段**に薄いフィルタとして差し込む。PoCスクリプト: `scratchpad/gnews_poc2.py`（依存なし・xml.etree）。

出典: [Google News RSS 検索パラメータ](https://www.newscatcherapi.com/blog-posts/google-news-rss-search-parameters-the-missing-documentaiton) / [Google News RSS 無料URL 2026](https://www.wprssaggregator.com/google-news-rss-feed/) / 自前PoC実測（2026-07-04）

---

## B. 認証 PoC 手順書（Better Auth + D1 + Google OAuth）

> **重要な最新事実**: Better Auth は **Cloudflare D1 をネイティブ対応**（D1 binding を直接渡せる。カスタムアダプタ不要）。これで PoC が大幅に簡単になった。

### B.1 事前準備
1. **Google Cloud Console** → OAuth 同意画面（External）→ 認証情報 → OAuth クライアントID（Webアプリ）作成
   - 承認済みリダイレクトURI: `https://<本番ドメイン>/api/auth/callback/google` と `http://localhost:8788/api/auth/callback/google`（ローカル）
   - 取得: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
2. **Cloudflare D1** DB 作成（既存 `info-collector-saves` とは別、例 `info-collector-users`）。`wrangler.toml` に binding。
3. Secrets（Pages/Workers）: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`。

### B.2 セットアップ手順（PoC = 「Googleでログインできる」まで）
1. `npm i better-auth`。
2. auth インスタンスを **リクエストごとに生成**（Workers の D1 binding は request context 経由のため）。D1 を DB として渡し、`socialProviders.google` に client id/secret を設定、`emailAndPassword` は後回し。
3. Better Auth のスキーマ（user/session/account/verification）を **D1 にマイグレーション**（Better Auth CLI or 生成SQLを `wrangler d1 migrations apply`）。
4. `/api/auth/*` を Pages Functions のキャッチオール（`functions/api/auth/[[route]].ts`）で Better Auth handler にルーティング。
5. フロントに「Googleで続ける」ボタン → `signIn.social({ provider: "google" })`。
6. コールバック後、`getSession()` でユーザー確認。`users` プロフィール行を upsert。

### B.3 落とし穴（事前に潰す）
- **リダイレクトURI 不一致**が最頻エラー → 本番ドメインを Google 側に必ず登録。
- **auth インスタンスをモジュールトップで生成しない**（D1 が無い状態で初期化され落ちる）。リクエスト内で生成しコンテキストに載せる。
- セッション Cookie の `secure` / `domain` を本番ドメインに合わせる。
- Better Auth のバージョンで D1 ネイティブ対応の可否が変わる → **1.5+ を使う**（実装直前に最新版とD1対応状況を確認）。

### B.4 PoC 合格条件
- ローカルと本番の両方で「Googleログイン→セッション取得→`users`に行が作られる」を確認。
- ログアウト・再ログインでセッションが正しく張り直る。

出典: [Better Auth on Cloudflare (Hono)](https://hono.dev/examples/better-auth-on-cloudflare) / [Better Auth 1.5（D1ネイティブ）](https://better-auth.com/blog/1-5) / [better-auth-cloudflare（D1/CLI）](https://github.com/zpg6/better-auth-cloudflare) / [React Router + D1 手順](https://dev.to/atman33/setup-better-auth-with-react-router-cloudflare-d1-2ad4)

---

## C. メール配信設計（Resend + 到達性 + 日次ダイジェスト）

### C.1 ドメイン認証（到達性の土台・必須）
送信元は **独自ドメイン**（例 `mail.<yourdomain>`）。Resend にドメイン登録すると出る DNS を設定:
- **SPF**: `TXT` … `v=spf1 include:_spf.resend.com ~all`（Resend 指定値に従う）
- **DKIM**: Resend 発行の `CNAME`/`TXT` を追加（署名鍵）
- **DMARC**: `TXT _dmarc.<domain>` … `v=DMARC1; p=none; rua=mailto:dmarc@<domain>`（まず monitoring の `p=none` で開始 → 安定後 `quarantine`）
- 送信元例: `info-collector <digest@mail.yourdomain>`、Reply-To に問い合わせ先。

### C.2 二重オプトイン（登録フロー）
1. ユーザーがジャンル選択＋メール登録 → `users.verified_at = NULL` で仮登録。
2. 確認メール送信（トークンリンク）。
3. リンク踏むと `verified_at` セット → 以後のダイジェスト送信対象に。
- 未確認アドレスへはダイジェストを送らない（スパム判定・バウンス回避）。

### C.3 日次ダイジェスト生成・送信
- cron `send_daily_digest`（既存 GitHub Actions に追加）:
  1. verified かつ未 unsubscribed のユーザーを取得。
  2. `subscriptions × items(当日, importance>=min_importance)` を結合、`notify_log` で未送信分に絞る。
  3. ジャンル別・重要度順にHTML組み立て → Resend API で送信 → `notify_log` 記録。
  4. 送信失敗/バウンスはログ化、連続バウンスは自動停止。
- **1ユーザー1日1通に集約**（無料枠=送信数なので集約が最重要）。0件の日は送らない。
- テンプレ: ヘッダ(日付) / ジャンル見出し / 記事(タイトル・自作要約・元リンク) / フッタに **配信停止リンク**（1クリック・トークン式）と設定リンク。

### C.4 無料枠の運用ライン
- Resend 無料 = 3,000通/月・100通/日 → **〜100 verified ユーザー/日**まで無料。
- 超えたら Brevo（300/日）へ切替 or Resend 有料。切替は送信ラッパを1箇所にして差し替え可能に。

出典: [email API 無料枠比較](https://www.buildmvpfast.com/api-costs/email) / [Brevo Email API 2026](https://www.brevo.com/blog/best-email-api/)

---

## D. 法対応（最小）・計測設計

### D.1 法対応の最小セット（グローバル公開の必須ライン）
- **プライバシーポリシー**: 取得情報（メール・Googleプロフィール最小限・購読ジャンル）、利用目的（ダイジェスト配信のみ）、第三者送信（メール/認証ベンダー）、保持期間、問い合わせ先を明記。
- **利用規約**: 情報は各社ソースの要約・リンクであること、無保証、個人利用向けである旨。
- **同意**: 登録時に規約・プラポリ同意チェック＋二重オプトイン。
- **配信停止**: 全メールに1クリック解除リンク（ログイン不要のトークン式）。
- **退会=データ削除**: `DELETE /api/me` で users/subscriptions/notify_log を削除（GDPR/CCPA の削除権対応）。
- **データ最小化**: パスワードは持たない（Google OAuth）。プロフィールは email/name のみ。
- **著作権**: 本文全文転載をしない。「タイトル＋自作要約＋元記事リンク」に限定（元サイトへ送客）。
- **地域**: EU/英/加ユーザーを受けるなら Cookie 最小化・同意、データ削除フローを機能させる。ベンダーのデータ所在（メール=Resend、認証=自前D1）を把握。

### D.2 計測指標（Go/継続判断に使う）
| 指標 | 定義 | 目的 | 目安 |
|---|---|---|---|
| 登録転換率 | LP訪問→登録完了 | 需要の強さ | まず絶対数を見る |
| 確認完了率 | 仮登録→二重オプトイン完了 | 導線/意欲 | 低ければ導線見直し |
| 平均購読ジャンル数 | user あたり subscriptions | 刺さり度 | 1桁前半で十分 |
| メール開封率 | 開封/送信 | 件名・価値 | 20〜40%が目安帯 |
| クリック率 | 記事クリック/送信 | 中身の価値 | 低ければ要約/選定改善 |
| 配信停止率 | unsubscribe/送信 | 過剰配信/ミスマッチ | 高ければ頻度/精度調整 |
| 7日/30日継続 | 期間内アクティブ | リテンション | **最重要**。低ければピボット |

- 計測実装: 登録/確認/退会は自前イベントを D1 or ログに記録。開封/クリックは Resend のイベント or リンクのトラッキングパラメータ。
- **プライバシー両立**: トラッキングは最小限・匿名集計。個人単位の行動を過度に貯めない。

---

## まとめ（この詳細設計で分かったこと）
- **認証は想定より簡単**: Better Auth の D1 ネイティブ対応でアダプタ実装が不要に。
- **カタログは機械展開可能**: Google News RSS の `q + when` 規則で120件を量産でき、curated は人気ジャンルだけ後付け。
- **メールが唯一のスケール律速**: 到達性(SPF/DKIM/DMARC)＋二重オプトイン＋1日1通集約で、無料枠100人/日まで無料運用。
- **法対応は定型**: プラポリ/規約/配信停止/退会削除/全文非転載の5点を最初から入れる。

次段階（実装するなら）: B.4 認証PoC → C.1 ドメイン認証 → 最小の登録〜1通配信を通す縦串、が最短の「動く証明」。**本セッションはここまで（実装しない）。**
