#!/usr/bin/env python3
# fetch_carrier_prices.py — キャリア公式オンラインショップの一括割引価格を収集し
# carrier_prices.json を生成する（ゆうサロンスキャナー「1円端末」MVP）。
#
# 対象:
#   - UQモバイル: uqwimax.jp 製品一覧の埋め込みカタログJSON（機種名・productCode）
#     + shop.uqmobile.jp 詳細ページ（サーバ描画: 機種代金/最大割引額が静的HTML内）
#   - 楽天モバイル: sitemap.xml の機種ページ + ページ専用JSチャンク内の価格表
#     （申込方法別 {storage: {lumpSum, division48,...}}）。
#     返却前提の買い替え超トクプログラムは price_type="return" として分離する。
#
# キャリア別に独立実行し、片方が失敗したらその旨を標準出力に残し、
# もう片方のデータで JSON を更新する（失敗したキャリア分は前回データを保持）。
# 標準ライブラリのみ使用。
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "carrier_prices.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
DELAY = 0.3


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def yen_int(s):
    return int(s.replace(",", "").replace("-", ""))


# ---------------------------------------------------------------- UQ mobile
UQ_CATALOG_URL = "https://www.uqwimax.jp/mobile/products/"
UQ_SHOP_BASE = "https://shop.uqmobile.jp"


def uq_parse_prices(html):
    """detail-otoku-pay ブロックから {storage_idx: (list_price, max_discount)} を返す。

    ページにより2形式ある:
      A) 1コンテナ内に dd が data-notation-storage 付きで容量別に並ぶ（iPhone等）
      B) 容量ごとに .detail-otoku-container が分かれ、ラッパ側に
         data-notation-storage が付く（Pixel等）
    コンテナ単位に切り分け、dd の属性が無い場合はコンテナ直前の
    data-notation-storage をその容量インデックスとして使う。
    """
    list_prices = {}
    discounts = {}
    starts = [m.start() for m in re.finditer(r'<div class="detail-otoku-container"', html)]
    segments = []
    if starts:
        for si, st in enumerate(starts):
            en = starts[si + 1] if si + 1 < len(starts) else len(html)
            seg_html = html[st:en]
            # コンテナ内の detail-price 等が持つ最初の data-notation-storage を
            # そのコンテナの容量インデックスとする（dd 属性が無い形式B用）
            head = seg_html.split("detail-otoku-pay", 1)[0]
            wm = re.findall(r'data-notation-storage="(\d+)"', head)
            default_idx = int(wm[0]) if wm else 0
            segments.append((default_idx, seg_html))
    else:
        segments = [(0, html)]
    for default_idx, seg_html in segments:
        blocks = re.findall(
            r'detail-otoku-pay__title">([^<]+)</dt>(.*?)(?=detail-otoku-pay__inner|</dl>)',
            seg_html, re.S)
        for title, seg in blocks:
            dds = re.findall(
                r'detail-otoku-pay__price"(?:\s+data-notation-storage="(\d+)")?>\s*(-?[0-9,]+)',
                seg)
            for idx_s, val_s in dds:
                idx = int(idx_s) if idx_s else default_idx
                val = yen_int(val_s)
                if "機種代金" in title:
                    if idx not in list_prices:
                        list_prices[idx] = val
                elif "最大割引額" in title:
                    if val > discounts.get(idx, 0):
                        discounts[idx] = val
    out = {}
    for idx, lp in list_prices.items():
        out[idx] = (lp, discounts.get(idx, 0))
    return out


def uq_conditions(html):
    m = re.search(r'表示されている機種代金・割引価格は「([^」]+)」かつ「([^」]+)」に加入の場合', html)
    if m:
        return f'最大割引は「{m.group(1)}」かつ「{m.group(2)}」加入時（のりかえ等の最大割引）'
    return "最大割引適用時（のりかえ等の条件あり・要公式確認）"


def fetch_uq(now_iso):
    html = fetch(UQ_CATALOG_URL)
    i = html.find("[", html.find("_productsTxt"))
    if i < 0:
        raise RuntimeError("UQ catalog JSON not found")
    catalog, _ = json.JSONDecoder().raw_decode(html[i:])
    by_link = {}
    for p in catalog:
        if p.get("terminal") != "スマホ":
            continue
        if str(p.get("end_flg")) == "1":
            continue
        link = (p.get("link_shop") or "").strip().split("?")[0]
        if not link:
            continue
        if link not in by_link:
            by_link[link] = p
    records = []
    for link, p in sorted(by_link.items()):
        time.sleep(DELAY)
        page = fetch(link)
        m = re.search(r'<h1 class="page-title">(.*?)</h1>', page, re.S)
        name = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else \
            re.sub(r"\s*\d+(GB|TB)\s*$", "", (p.get("name") or "").strip())
        name = re.sub(r"を購入$", "", name).strip()
        storages = []
        mj = re.search(r'(/detail/data/[^"\']+\.js)', page)
        if mj:
            try:
                js = fetch(UQ_SHOP_BASE + mj.group(1))
                si = js.find('"storage_types"')
                seg = js[si:si + 20000] if si >= 0 else js
                storages = re.findall(r'"name"\s*:\s*"(\d+(?:GB|TB))"', seg)
            except Exception as e:
                print(f"UQ: data JS fetch failed for {link}: {e}")
        prices = uq_parse_prices(page)
        cond = uq_conditions(page)
        code = (p.get("productCode") or "").strip()
        for idx, (lp, disc) in sorted(prices.items()):
            if disc <= 0 or lp <= 0:
                continue
            storage = storages[idx] if idx < len(storages) else ""
            records.append({
                "carrier": "UQモバイル",
                "channel": "online",
                "model_name": name,
                "model_code": code,
                "storage": storage,
                "list_price": lp,
                "discount": disc,
                "lump_price": lp - disc,
                "price_type": "lump",
                "conditions": cond,
                "source_url": link,
                "fetched_at": now_iso,
            })
    return records


# ---------------------------------------------------------------- Rakuten
RK_BASE = "https://network.mobile.rakuten.co.jp"
RK_SITEMAP = RK_BASE + "/sitemap.xml"
RK_EXCLUDE_SLUGS = {"comparison", "fee", "stock", "features", "top"}


def rk_parse_price_table(js):
    """価格表 [{label, prices:{storage:{lumpSum, division48}}}] を抽出する。"""
    entries = []
    for m in re.finditer(r'\{label:"([^"]+)",prices:\{', js):
        label = m.group(1)
        start = m.end() - 1  # prices object の '{'
        depth = 0
        end = None
        for j in range(start, len(js)):
            c = js[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            continue
        body = js[start:end + 1]
        prices = {}
        for sm in re.finditer(r'"([^"]+)":\{([^{}]*)\}', body):
            vals = sm.group(2)
            lm = re.search(r'lumpSum:(\d+)', vals)
            if not lm:
                continue
            dm = re.search(r'division48:(\d+)', vals)
            # 容量キー（128GB等）以外は単一容量扱い（キーなし）に寄せる
            key = sm.group(1) if re.fullmatch(r'\d+(GB|TB)', sm.group(1)) else ""
            prices[key] = {
                "lumpSum": int(lm.group(1)),
                "division48": int(dm.group(1)) if dm else None,
            }
        if prices:
            entries.append({"label": label, "prices": prices})
    return entries


def rk_campaign_notes(js):
    notes = []
    for pat in (r'最大[0-9,]+円値引き', r'[0-9,]+ポイント還元', r'[0-9,]+円相当ポイント'):
        for t in re.findall(pat, js):
            if t not in notes:
                notes.append(t)
    return notes


def fetch_rakuten(now_iso):
    sm = fetch(RK_SITEMAP)
    paths = sorted(set(re.findall(
        r'/product/(?:smartphone|iphone)/[a-z0-9-]+/', sm)))
    records = []
    for path in paths:
        slug = path.rstrip("/").split("/")[-1]
        if slug in RK_EXCLUDE_SLUGS:
            continue
        url = RK_BASE + path
        time.sleep(DELAY)
        try:
            page = fetch(url)
        except Exception as e:
            print(f"Rakuten: page fetch failed {path}: {e}")
            continue
        # JSON-LD (Product) から機種名・定価・在庫状態
        name = None
        ld_price = None
        in_stock = False
        for lm in re.finditer(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
            try:
                ld = json.loads(lm.group(1))
            except Exception:
                continue
            if isinstance(ld, dict) and ld.get("@type") == "Product":
                name = ld.get("name")
                offers = ld.get("offers") or {}
                if isinstance(offers, dict):
                    if offers.get("price"):
                        ld_price = int(float(offers["price"]))
                    if "InStock" in str(offers.get("availability", "")):
                        in_stock = True
        if not name or not in_stock:
            continue
        cm = re.search(r'/_next/static/chunks/pages/product/[^"\']+\.js', page)
        if not cm:
            continue
        try:
            js = fetch(RK_BASE + cm.group(0))
        except Exception as e:
            print(f"Rakuten: chunk fetch failed {path}: {e}")
            continue
        entries = rk_parse_price_table(js)
        if not entries:
            continue
        notes = rk_campaign_notes(js)
        # 返却プログラムの基準エントリ（のりかえ/MNP優先、なければ先頭）
        ret_entry = None
        for e in entries:
            if "乗り換え" in e["label"] or "MNP" in e["label"]:
                ret_entry = e
                break
        if ret_entry is None:
            ret_entry = entries[0]
        storages = set()
        for e in entries:
            storages.update(e["prices"].keys())
        for storage in sorted(storages):
            lumps = [e["prices"][storage]["lumpSum"] for e in entries
                     if storage in e["prices"]]
            if not lumps:
                continue
            base = max(lumps)
            best = min(lumps)
            if best < base:
                cond = "一括割引適用時（申込方法により価格が異なる）"
                if notes:
                    cond += "／キャンペーン: " + "・".join(notes)
                records.append({
                    "carrier": "楽天モバイル",
                    "channel": "online",
                    "model_name": name,
                    "model_code": slug,
                    "storage": storage,
                    "list_price": base,
                    "discount": base - best,
                    "lump_price": best,
                    "price_type": "lump",
                    "conditions": cond,
                    "source_url": url,
                    "fetched_at": now_iso,
                })
            # 返却前提（買い替え超トクプログラム）: 48回分割を24回払い+返却で残額免除
            rp = ret_entry["prices"].get(storage)
            if rp and rp.get("division48"):
                eff = rp["division48"] * 24
                if 0 < eff < base:
                    cond = ("買い替え超トクプログラム利用時（48回分割のうち24回支払い＋"
                            f"端末返却で残額免除）／{ret_entry['label']}の月額×24回で算出")
                    if notes:
                        cond += "／キャンペーン: " + "・".join(notes)
                    records.append({
                        "carrier": "楽天モバイル",
                        "channel": "online",
                        "model_name": name,
                        "model_code": slug,
                        "storage": storage,
                        "list_price": base,
                        "discount": base - eff,
                        "lump_price": eff,
                        "price_type": "return",
                        "conditions": cond,
                        "source_url": url,
                        "fetched_at": now_iso,
                    })
    return records


# ---------------------------------------------------------------- main
def main():
    now_iso = datetime.now(JST).isoformat(timespec="seconds")
    old = {}
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, encoding="utf-8") as f:
                for r in json.load(f).get("items", []):
                    old.setdefault(r.get("carrier"), []).append(r)
        except Exception:
            old = {}
    results = {}
    for carrier, fn in (("UQモバイル", fetch_uq), ("楽天モバイル", fetch_rakuten)):
        try:
            recs = fn(now_iso)
            if recs:
                results[carrier] = recs
                print(f"{carrier}: {len(recs)} records")
            else:
                print(f"{carrier}: 0 records — keeping previous data (possible site change)")
                if carrier in old:
                    results[carrier] = old[carrier]
        except Exception as e:
            print(f"{carrier}: FETCH FAILED: {e} — keeping previous data")
            if carrier in old:
                results[carrier] = old[carrier]
    items = []
    for carrier in ("UQモバイル", "楽天モバイル"):
        items.extend(results.get(carrier, []))
    items.sort(key=lambda r: (0 if r["price_type"] == "lump" else 1, r["lump_price"]))
    out = {"updated_at": now_iso, "count": len(items), "items": items}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {OUT_PATH}: {len(items)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
