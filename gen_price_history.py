#!/usr/bin/env python3
"""価格推移データ生成 (v10, 2026-11-24)

history/YYYY-MM-DD.json の日次スナップショットから、商品ごとの
「日付×最高買取価格＋上位3店」系列を price_history.json に書き出す。
対象は最高買取価格が変動した商品のみ（ファイルサイズ抑制）。
cron_hourly.sh の publish 前（ステップ2.6）に実行される。
"""
import json
import os
import glob
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
HIST_DIR = os.path.join(BASE, "history")
OUT = os.path.join(BASE, "price_history.json")
MAX_DAYS = 21


def main():
    files = sorted(glob.glob(os.path.join(HIST_DIR, "*.json")))[-MAX_DAYS:]
    days, per_day = [], []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        days.append(d.get("date") or os.path.basename(f)[:-5])
        per_day.append(d.get("quotes") or {})
    if not days:
        print("price_history: no history snapshots")
        return 1

    ids = set()
    for q in per_day:
        ids.update(q.keys())

    items = {}
    for iid in ids:
        maxs = []
        shop_series = {}
        for di, q in enumerate(per_day):
            qq = q.get(iid) or {}
            maxs.append(max(qq.values()) if qq else None)
            for name, price in qq.items():
                if name not in shop_series:
                    shop_series[name] = [None] * len(per_day)
                shop_series[name][di] = price
        vals = [v for v in maxs if v]
        if len(vals) < 2 or len(set(vals)) < 2:
            continue  # 変動なし・データ不足は対象外

        def latest(series):
            for v in reversed(series):
                if v:
                    return v
            return 0

        top = sorted(shop_series.items(), key=lambda kv: -latest(kv[1]))[:3]
        items[iid] = {"m": maxs, "s": {name: ser for name, ser in top}}

    out = {"days": days, "items": items}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    print("price_history: %d days, %d items, %d bytes"
          % (len(days), len(items), os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
