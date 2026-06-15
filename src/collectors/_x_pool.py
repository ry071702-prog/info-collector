"""X collector 共通: twscrape アカウントプールの初期化。

X_ACCOUNTS (JSON 配列) の各要素:
  {"username": "...", "email": "...", "password": "...",
   "email_password": "...", "cookies": "auth_token=..; ct0=.."}

- cookies があれば cookie ログイン。ct0 を含む cookie を渡すと twscrape が
  そのアカウントを即 active=true 化し、username/password の自動ログイン
  フロー (= データセンターIPで 403 を食らう発生源) を login_all() で踏まない。
- cookies が無ければ従来どおり username/password でログイン (居住者IP 前提)。
- cookie 運用なら password / email / email_password は空文字でよい。

x_twscrape.py と x_search.py で同一だった _ensure_pool を一本化したもの。
0.18.x の accounts_info() はコルーチンで list[dict] を返す点に注意 (旧コードは
`async for` / 属性アクセスで書かれており 0.18 でクラッシュしていた)。
"""
from __future__ import annotations

from ..config import env_json


async def ensure_pool():
    """X_ACCOUNTS からプールを構築して API を返す。

    X_ACCOUNTS 未設定なら RuntimeError (呼び出し側が graceful skip 済み)。
    """
    from twscrape import API

    api = API()
    accounts = env_json("X_ACCOUNTS", default=[])
    if not accounts:
        raise RuntimeError("X_ACCOUNTS not configured")
    # 0.18.x: accounts_info() はコルーチン → await し dict でアクセス
    existing = {a["username"] for a in await api.pool.accounts_info()}
    for acc in accounts:
        cookies = acc.get("cookies") or None
        if acc["username"] in existing:
            if not cookies:
                continue  # id/pass 方式は既存のログイン状態を再利用
            # cookie 方式は .env を正とし毎回作り直す。これをしないと twscrape が
            # 「既存アカウントはスキップ」するため、cookie 失効後に .env を更新しても
            # 古い cookie が使われ続ける。delete→add で新 cookie を確実に反映。
            await api.pool.delete_accounts(acc["username"])
        await api.pool.add_account(
            acc["username"],
            acc.get("password", ""),
            acc.get("email", ""),
            acc.get("email_password", ""),
            cookies=cookies,
        )
    # cookie 勢 (ct0 入り) は active=true なので login_all() の対象外
    # (= X の Cloudflare 保護がかかったログインフローを踏まない)。
    # password 運用の垢だけがここでログインを試みる。
    await api.pool.login_all()
    return api
