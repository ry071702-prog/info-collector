#!/usr/bin/env bash
# launchd から定時(7:40/11:40/17:40 JST)に呼ばれ、GitHub の send_catchup
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
GH=/opt/homebrew/bin/gh
REPO=ry071702-prog/info-collector

# ローカル(JST)時で便を決める。launchd 発火時刻なら境界に余裕がある:
#   7:40→morning / 11:40→noon / 17:40→evening (send_catchup の <10/<15/else と一致)
# 10# は date が返す 08/09 を8進数解釈してエラーになるのを防ぐ(遅延起床対策)。
h=$((10#$(date +%H)))
if   [ "$h" -lt 10 ]; then slot=morning
elif [ "$h" -lt 15 ]; then slot=noon
else                       slot=evening
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
