#!/usr/bin/env bash
# ゆうサロンスキャナー: 買取価格と実売価格を毎時23分に更新（XServer VPS / 2026-11-19）
# GitHub Actions の schedule が配信されないため、VPS から確実に毎時回す。
# 出力の scan_db.json は Bot の買取DB（ZEPHYR_DB_URL=file:///opt/scanner/scan_db.json）
# としても使われる。
set -uo pipefail
cd /opt/scanner || exit 1
LOG=/var/log/scanner_update.log
echo "=== $(TZ=Asia/Tokyo date '+%F %T') 開始" >> "$LOG"

# 1) 実売価格（価格.com）と買取wikiのJAN検索をローテーションで補充（キャッシュ済みは即スキップ）
#    1回400件まで。全件が終われば以降はキャッシュ更新だけで数秒。
if [ -x /opt/pwenv/bin/python ]; then
  # 二重起動しないようロックを取る（手動の全件収集が走っている間はスキップ）
  flock -n /var/lock/enrich.lock timeout 900 /opt/pwenv/bin/python enrich.py --limit 400 \
    >> /var/log/enrich.log 2>&1 || true
fi

# 2) 買取8社＋ホムラ＋wiki で価格を取り直し、前日比と実売を scan_db.json に載せる
/opt/pwenv/bin/python update_prices.py --delay 0.3 >> "$LOG" 2>&1
rc=$?
echo "=== $(TZ=Asia/Tokyo date '+%F %T') 終了 rc=$rc" >> "$LOG"
if [ "$rc" -ne 0 ]; then
  echo "更新失敗（rc=$rc）。前回の scan_db.json を保持しています。" >> "$LOG"
fi
# 3) 更新後に GitHub へ push（公開URLの毎時更新）
if [ -x /opt/scanner/publish.sh ]; then
  /opt/scanner/publish.sh
fi
exit 0
