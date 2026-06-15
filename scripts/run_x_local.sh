#!/usr/bin/env bash
# ローカル Mac (居住者IP) で X collector だけを回し、data/raw を repo へ push する。
#
# 背景: X は GitHub Actions のデータセンターIPからのアクセスを 403 でブロックする。
# 居住者IPを持つこのマシンで X 収集だけを実行し、分類・ダイジェスト等は従来どおり
# GitHub Actions に任せる (X 以外の collector は Actions 側が回す)。
#
# launchd (com.infocollector.xcollect.plist) から 1日数回 (例: 9/15/21時) 起動される想定。
# 手動実行も可: bash scripts/run_x_local.sh
set -euo pipefail

REPO="${INFOCOLLECTOR_DIR:-$HOME/情報収集}"
cd "$REPO"

# venv (X 専用 .venv-x を優先。twscrape 0.18 は Python 3.10+ 必須なため
# 3.9 の既存 .venv とは別建て)。
if [ -f .venv-x/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv-x/bin/activate
elif [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# X collector だけを実行。.env の X_ACCOUNTS (cookies 入り) は config.py の
# load_dotenv が読む。API 負荷は tier 非依存なので取りこぼし最小の daily(30h) を使用。
export COLLECTORS=x,x_search
python -m src.jobs.collect daily

# 生成物を commit & push。Actions 由来 commit と競合しても -X theirs で吸収。
git add data/raw data/cache data/logs 2>/dev/null || true
if ! git diff --quiet --staged; then
  git commit -q -m "x raw (local mac) $(date -u +%FT%TZ)"
  for i in 1 2 3; do
    if git pull --rebase --autostash -X theirs && git push; then
      break
    fi
    git rebase --abort 2>/dev/null || true
    sleep $((i * 5))
  done
fi
