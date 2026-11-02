#!/usr/bin/env bash
# launchd から定時(11:40 JST の1日1便)に呼ばれ、GitHub の send_catchup
# workflow を即時トリガーする (workflow_dispatch)。
#
# なぜ launchd→dispatch か:
#   GitHub の cron(schedule) は実発火が数時間遅れる/稀に落ちる。一方 launchd は
#   定時に正確に発火し、workflow_dispatch した run は遅延なく即実行される。
#   配信シークレット(Gmail/Slack/Discord)は GitHub 側にあるのでローカルには不要
#   (gh 認証だけ要る)。cron スケジュールは保険として残す(Mac スリープ時の
#   フォールバック)。同一便を両方が送っても catchup_sent.json の dedup +
#   concurrency 直列化で二重送信されない。
set -euo pipefail
source "$HOME/.claude/lib/automation-stamp.sh"   # 成功/失敗を記録 (automation-health.sh が見る)
JOB="info-catchup"
GH="${GH:-/opt/homebrew/bin/gh}"
REPO=ry071702-prog/info-collector

# 1日1便なので便は常に noon (dedup は便×日付単位  別の便名で送ると同じ日に2通届く)
slot=noon

# 11:40 より前に起動されたら送らない (当日 11:40 の発火と GitHub の cron に任せる)
#   起動されうる経路: 寝ている間に過ぎた発火を launchd が起床時にまとめて1回走らせる / 自己修復 (automation-selfheal) が起動し直す
#   2026-11-02 9:16 に自己修復が起動し直し、時刻から morning 便と判定されて昼便と合わせて2通届いた
# 10# は date が返す 0916 などを8進数として解釈させないため
hm=$((10#$(date +%H%M)))
if [ "$hm" -lt 1140 ]; then
  echo "$(date '+%F %T') 11:40 前の起動なので送らない"
  auto_ok "$JOB" "skip (11:40 前の起動)"
  exit 0
fi

# dispatch は起床直後にネット未確立で落ちることがある  数回リトライしてから諦める
for i in 1 2 3 4 5; do
  if "$GH" workflow run send_catchup.yml --repo "$REPO" -f slot="$slot" -f dry_run=false; then
    echo "$(date '+%F %T') triggered send_catchup slot=$slot (try $i)"
    auto_ok "$JOB" "dispatch OK (slot=$slot)"
    exit 0
  fi
  echo "$(date '+%F %T') dispatch 失敗 (try $i)  $((i * 30))秒後に再試行" >&2
  sleep $((i * 30))
done
auto_die "$JOB" "send_catchup の dispatch に5回失敗 (slot=$slot  ネット未確立 or gh 認証切れ)"
