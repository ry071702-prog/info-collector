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
        if acc["username"] in existing:
            continue
        await api.pool.add_account(
            acc["username"],
            acc.get("password", ""),
            acc.get("email", ""),
            acc.get("email_password", ""),
            cookies=acc.get("cookies") or None,
        )
    # cookie 勢 (ct0 入り) は active=true なので login_all() の対象外。
    # password 運用の垢だけがここでログインを試みる (居住者IP 前提)。
    await api.pool.login_all()
    return api
