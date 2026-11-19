#!/usr/bin/env bash
# ゆうサロンスキャナー: 生成した scan_db.json を GitHub（pinkmnp1/yuu-salon-simulator）へ push
# 2026-11-19 復旧: 専用 Fine-grained PAT（/opt/scanner/.gh_token, Contents: Read and write,
# 期限 2027-02-17）を http.extraHeader で使用。トークンは .git/config に残さない。
set -uo pipefail
cd /opt/scanner || exit 1
LOG=/var/log/scanner_push.log
ts() { TZ=Asia/Tokyo date '+%F %T'; }

TOKEN="$(tr -d '\r\n' < /opt/scanner/.gh_token 2>/dev/null)"
if [ -z "$TOKEN" ]; then
  TOKEN=$(sed -n 's/^GITHUB_TOKEN=//p' /opt/yuubot/.env 2>/dev/null | head -1 | tr -d '\r')
fi
if [ -z "$TOKEN" ]; then
  echo "=== $(ts) トークンが見つからない（/opt/scanner/.gh_token）" >>"$LOG"
  exit 1
fi

export GIT_TERMINAL_PROMPT=0
AUTH="http.extraHeader=Authorization: Basic $(printf 'x-access-token:%s' "$TOKEN" | base64 -w0)"
git config user.name "kaitori-price-bot"
git config user.email "actions@users.noreply.github.com"

# 未コミットの差分があればコミット（cron_hourly.sh から毎時呼ばれる）
if ! git diff --quiet -- scan_db.json; then
  git add scan_db.json
  git commit -m "価格を自動更新 $(TZ=Asia/Tokyo date +%F\ %H:%M)" >>"$LOG" 2>&1 || true
fi

REMOTE=$(git -c "$AUTH" ls-remote origin refs/heads/main 2>>"$LOG" | cut -f1)
if [ -n "$REMOTE" ] && [ "$(git rev-parse HEAD)" = "$REMOTE" ]; then
  echo "=== $(ts) 公開側と同一（push 不要）HEAD=$(git rev-parse --short HEAD)" >>"$LOG"
  exit 0
fi

for attempt in 1 2 3; do
  if git -c "$AUTH" push origin main >>"$LOG" 2>&1; then
    echo "=== $(ts) push 成功（attempt $attempt, $(git rev-parse --short HEAD), remote=${REMOTE:0:7}）" >>"$LOG"
    exit 0
  fi
  echo "=== $(ts) push 失敗（attempt $attempt）。rebase して再試行" >>"$LOG"
  git -c "$AUTH" pull --rebase --autostash origin main >>"$LOG" 2>&1 || sleep 5
done
echo "=== $(ts) push 最終失敗" >>"$LOG"
exit 1
