#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""『ゆうサロンスキャナー』の買取価格を毎日自動更新する（GitHub Actions 用）。

買取商店・家電市場・買取ルデヤの公開API／公開一覧から最新の「新品・未開封」買取額を取得し、
同じリポジトリ直下の scan_db.json を書き換える。Python 標準ライブラリだけで動く
（pip install 不要・追加パッケージなし）。

    python3 scripts/update_prices.py              # 本番（scan_db.json を書き換える）
    python3 scripts/update_prices.py --dry-run    # 取得と差分表示だけ（ファイルは書かない）
    python3 scripts/update_prices.py --source kaitorishouten --limit 2   # 動作確認

取得できた店だけを更新し、落ちた店の前回値を消さない（安全なフォールバック）。
3社すべて失敗した時だけ終了コード1で止まり、ファイルは書き換えない。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "scan_db.json"
JST = dt.timezone(dt.timedelta(hours=9))

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
UA_FALLBACK = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

SHOP_KS = "買取商店"
SHOP_KI = "家電市場"
SHOP_RD = "買取ルデヤ"
SOURCES = (SHOP_KI, SHOP_RD, SHOP_KS)

KS_API = "https://www.kaitorishouten-co.jp/api/v1/products"
KI_BASE = "https://www.kaden-ichiba.com"
KI_DETAIL = KI_BASE + "/item/detail/"
KI_LISTS = [
    KI_BASE + "/item/all",
    KI_BASE + "/item/group/73/" + urllib.parse.quote("iPhone"),
    KI_BASE + "/item/group/35/" + urllib.parse.quote("ゲーム機"),
    KI_BASE + "/item/group/18/Android",
    KI_BASE + "/item/group/76/" + urllib.parse.quote("タブレット"),
]
RD_CATEGORY = "https://kaitori-rudeya.com/category/detail/"
# 買取ルデヤの公開カテゴリ（サイトマップから取得したID）
RD_CATS = [1, 2, 3, 4, 5, 10, 11, 12, 13, 23, 31, 32, 42, 44, 55, 57, 67, 71, 72, 73,
           74, 76, 81, 84, 114, 116, 120, 131, 136, 151, 159, 171, 172, 183, 184, 185,
           186, 202, 205, 214, 218, 219, 220, 221, 222, 223, 224, 225, 226, 232, 240,
           242, 244, 245, 246, 247, 248, 249, 250, 253, 254, 255, 258]

KI_DETAIL_BUDGET = 40       # 未登録商品のJAN調べ（1回の実行あたり）
PAGE_CAP = 45               # 一覧1本あたりの最大ページ数（暴走防止）
KI_GROUP_PROBE = True       # 未取得のカテゴリも1ページ目だけ見て新商品を拾う

CARD_RE = re.compile(r'x-data="itemCard\((\{.*?\})\)"', re.S)
RD_CARD_RE = re.compile(
    r'<h3 class="product-card-name">(.*?)</h3>\s*<p class="product-card-jan">(.*?)</p>.*?'
    r'<span class="product-card-price-value">([\d,]+)', re.S)


# ---------------------------------------------------------------- 共通ユーティリティ

def today_jst() -> str:
    return dt.datetime.now(JST).strftime("%Y-%m-%d")


def now_jst() -> str:
    """更新時刻（日本時間）。scan_db.json の updated_at_jst と画面表示に使う。"""
    return dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def jan_ok(j) -> bool:
    if not j or not re.fullmatch(r"\d{13}", str(j)):
        return False
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(str(j)[:12]))
    return (10 - s % 10) % 10 == int(str(j)[12])


def alias_of(name: str) -> str:
    return re.sub(r"[\s\u3000\-－・/\\（）()\[\]【】「」、]", "", name or "")


def clean_name(n: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", n or "")).strip()


GAME_KW = ("Nintendo Switch", "Switch", "PlayStation", "PS5", "PS4", "Xbox", "PS Vita", "ゲームソフト",
           "Steam Deck", "Steam Machine", "ROG Ally", "Legion Go", "ゲーム機", "プレイステーション", "プレステ")
CAM_KW = ("EOS", "ILCE", "LUMIX", "FUJIFILM", "NIKON", "NIKKOR", "OM SYSTEM", "ライカ", "Leica", "ハッセルブラッド",
          "ミラーレス", "一眼", "レンズ", "SIGMA", "TAMRON", "GoPro", "Insta360", "DJI Osmo", "ビデオカメラ",
          "デジタルカメラ", "サイバーショット", "COOLPIX", "PowerShot", "α7", "α9", "α1", "α6700", "ZV-E",
          "ILME", "FX3", "FX30", "GFX", "X100", "X-T5", "X-H2")
PC_KW = ("MacBook", "Mac mini", "Mac Studio", "Mac Pro", "iMac", "LAVIE", "ThinkPad", "Surface", "ノートPC", "FMV",
         "デスクトップ", "ゲーミングPC", "ROG ", "Legion", "IdeaPad", "YOGA", "dynabook")
AUDIO_KW = ("ヘッドホン", "イヤホン", "AirPods", "WH-1000", "WF-1000", "スピーカー", "サウンドバー", "Walkman",
            "ウォークマン", "BOSE", "ゼンハイザー", "オーディオテクニカ", "NW-WM", "NW-ZX", "NW-A")
LENS_KW = ("SEL", "FE ", "ボディ", "レンズキット", "マウントアダプター", "RICOH GR", "PENTAX", "GR III", "GR IV",
           "OLYMPUS", "OM-D", "PEN E-", "VLOGCAM", "ダブルズーム", "ズームキット", "Z6II", "Z50II", "Z fc",
           "Z 5 ", "Z 6", "Z 7", "Z 8", "Z 9", "ZR ボディ")
XR_KW = ("Meta Quest", "Vision Pro", "Ray-Ban Meta", "VIVE", "PICO ", "Steam Frame")
WEAR_KW = ("Apple Watch", "Galaxy Watch", "Pixel Watch", "fitbit", "スマートウォッチ", "HUAWEI Watch")
TCG_KW = ("ポケモンカード", "ONE PIECEカード", "ワンピースカード", "遊戯王", "UNION ARENA", "デュエル・マスターズ",
          "ドラゴンボール", "STORY BOOSTER", "[BOX]", "ブースターパック", "拡張パック", "初版BOX")
TAB_KW = ("iPad", "タブレット", "LAVIE Tab", "Galaxy Tab", "MediaPad", "Fire HD", "Fire Max", "Nexus 7")
PHONE_BRANDS = ("iPhone", "Galaxy", "Pixel", "Xperia", "AQUOS", "OPPO", "moto", "arrows", "nubia", "Redmi", "Xiaomi",
                "HUAWEI", "Honor", "Zenfone", "Ace", "Libero", "BASIO", "かんたん", "isai")


def map_cat(site_cat, name: str) -> str:
    """サイトのカテゴリを土台に、名称から明らかなものだけ細分類（推測はしない）。"""
    n = name or ""
    if site_cat == "お酒":
        return "お酒"
    if any(k in n for k in TCG_KW):
        return "トレカ"
    if any(k in n for k in WEAR_KW):
        return "ウェアラブル"
    if any(k in n for k in XR_KW):
        return "XR"
    if (any(k in n for k in CAM_KW) or any(k in n for k in LENS_KW)
            or re.search(r"\d+-?\d*mm\s*F\d", n) or re.search(r"\d+mm$", n)):
        return "カメラ"
    if any(k in n for k in GAME_KW):
        return "ゲーム機"
    if any(k in n for k in AUDIO_KW):
        return "オーディオ"
    if any(k in n for k in PC_KW):
        return "PC"
    if any(k in n for k in TAB_KW):
        return "タブレット"
    if site_cat == "スマホ" or any(k in n.lower() for k in [b.lower() for b in PHONE_BRANDS]):
        return "端末"
    if site_cat == "おもちゃ":
        return "おもちゃ"
    return "家電"


# ---------------------------------------------------------------- 取得

class Fetcher:
    """礼儀正しい取得（待ち時間・再試行・UA切替）。失敗は例外にせず None を返す。"""

    def __init__(self, delay: float = 0.35, retries: int = 2, timeout: int = 30):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.requests = 0
        self.failures = 0
        self.last_error = 0          # 直近のHTTPステータス（404/410 は一覧の終わりとみなす）

    def get(self, url: str, byte_range: str | None = None) -> bytes | None:
        self.last_error = 0
        for attempt in range(self.retries + 1):
            ua = UA if attempt % 2 == 0 else UA_FALLBACK
            req = urllib.request.Request(url, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en;q=0.8",
                "Range": byte_range or "",
            } if byte_range else {
                "User-Agent": ua,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en;q=0.8",
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as res:
                    self.requests += 1
                    body = res.read()
                time.sleep(self.delay)
                if body and len(body) > 200:
                    return body
            except urllib.error.HTTPError as e:
                self.last_error = e.code
                if e.code in (404, 410):        # ページの終わり。再試行しない
                    return None
                self.failures += 1
                print(f"    取得失敗 {url} (HTTP {e.code})", flush=True)
                time.sleep(1.0 + attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self.failures += 1
                self.last_error = -1
                print(f"    取得失敗 {url} ({type(e).__name__}: {e})", flush=True)
                time.sleep(1.0 + attempt)
        return None

    def get_text(self, url: str, byte_range: str | None = None) -> str | None:
        b = self.get(url, byte_range)
        return b.decode("utf-8", "ignore") if b else None


def new_item(jan: str, name: str, cat: str, price: int, shop: str, today: str, note: str) -> dict:
    name = clean_name(name)
    return {"id": "jan-" + jan, "name": name, "cat": cat, "jan": jan, "model": "",
            "alias": alias_of(name), "msrp": 0, "price": int(price), "shop": shop,
            "date": today, "note": note, "quotes": {shop: int(price)}}


def fetch_kaitorishouten(f: Fetcher, limit: int = 0) -> tuple[dict, bool]:
    """買取商店: robots.txt で明示許可された公開API。/api/v1/products?per_page=100&page=N"""
    out: dict[str, dict] = {}
    page, total, fails, pages_ok = 1, None, 0, 0
    while page <= 120:
        raw = f.get(f"{KS_API}?per_page=100&page={page}")
        if raw is None:
            fails += 1
            if fails >= 3:
                break
            page += 1
            continue
        try:
            data = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            fails += 1
            page += 1
            continue
        total = int(data.get("total") or total or 0)
        items = data.get("items") or []
        if not items:
            break
        pages_ok += 1
        for it in items:
            jan = str(it.get("jan") or "")
            if not jan_ok(jan):
                continue
            pn = it.get("price_new") or {}
            amt = pn.get("amount")
            label = "新品"
            if not amt:
                cands = [p for p in (it.get("prices") or [])
                         if str(p.get("label", "")).startswith("新品") and p.get("amount")]
                if cands:
                    best = max(cands, key=lambda p: p["amount"])
                    amt, label = best["amount"], best["label"]
            if not amt or int(amt) <= 0:
                continue
            cur = out.get(jan)
            if cur and cur["price"] >= int(amt):
                continue
            out[jan] = {"price": int(amt), "name": it.get("name") or "",
                        "cat": map_cat(it.get("category"), it.get("name") or ""),
                        "note": f"新品・サイト更新{it.get('update_date')}" if it.get("update_date") else label}
        print(f"    買取商店 {page}ページ目: 累計 {len(out):,}件 / 全{total or '?'}件", flush=True)
        if limit and page >= limit:
            break
        if total and page * 100 >= total:
            break
        page += 1
    complete = total > 0 and fails == 0 and pages_ok >= -(-total // 100)
    return out, complete


def parse_ki_cards(text: str) -> list[dict]:
    import html as html_mod
    out = []
    for m in CARD_RE.finditer(text):
        try:
            d = json.loads(html_mod.unescape(m.group(1)))
        except Exception:
            continue
        if d.get("cco"):
            out.append(d)
    return out


def ki_pages(text: str) -> int:
    nums = [int(x) for x in re.findall(r"[?&]page=(\d+)", text)]
    return max(nums) if nums else 1


def fetch_kaden_ichiba(f: Fetcher, known_cco: set[str], limit: int = 0) -> tuple[dict, dict, bool]:
    """家電市場: 一覧ページの x-data から「新品」価格を読む。

    返り値: ({cco: {"price","name"}}, {cco: jan}, 全件取れたか)
    JAN は一覧に出ないので、DBに無い商品だけ詳細ページの頭を読んで調べる（上限あり）。
    """
    cards: dict[str, dict] = {}
    seen_groups: set[str] = set()
    ok_pages = 0
    bad_pages = 0

    def read_list(url: str, max_page: int = 0) -> None:
        nonlocal ok_pages, bad_pages
        first = f.get_text(url)
        if not first:
            bad_pages += 1
            return
        ok_pages += 1
        last = ki_pages(first) if not max_page else max_page
        last = min(last, PAGE_CAP)
        for c in parse_ki_cards(first):
            cards.setdefault(c["cco"], c)
        for p in range(2, last + 1):
            if limit and p > limit:
                break
            sep = "&" if "?" in url else "?"
            t = f.get_text(f"{url}{sep}page={p}")
            if not t:
                if f.last_error in (404, 410):
                    break                       # ページ番号の表示より実ページが少ないことがある
                bad_pages += 1
                continue
            ok_pages += 1
            got = parse_ki_cards(t)
            if not got:
                break
            for c in got:
                cards.setdefault(c["cco"], c)

    for url in KI_LISTS:
        name = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        print(f"    家電市場 一覧 {name}", flush=True)
        read_list(url)
        seen_groups.add(url)

    # 未取得カテゴリの1ページ目だけ見て新商品を拾う
    if KI_GROUP_PROBE and not limit:
        top = f.get_text(KI_BASE + "/item/all")
        if top:
            groups = sorted(set(re.findall(r"/item/group/(\d+)/[^\"']*", top)))
            for g in groups:
                url = f"{KI_BASE}/item/group/{g}"
                if url in seen_groups:
                    continue
                t = f.get_text(url)
                if not t:
                    bad_pages += 1
                    continue
                ok_pages += 1
                for c in parse_ki_cards(t):
                    cards.setdefault(c["cco"], c)
            print(f"    家電市場 サブカテゴリ{len(groups)}件の1ページ目も確認", flush=True)

    prices = {}
    for cco, c in cards.items():
        amt = (c.get("prices") or {}).get("0")
        if not amt or int(amt) <= 0:
            continue
        prices[cco] = {"price": int(amt), "name": c.get("name") or ""}

    # 未登録 cco の JAN 調べ（詳細ページの頭だけ）
    jan_map: dict[str, str] = {}
    todo = [cco for cco in prices if cco not in known_cco]
    todo.sort()
    for cco in todo[:KI_DETAIL_BUDGET]:
        head = f.get_text(KI_DETAIL + cco, byte_range="bytes=0-24000")
        if not head:
            continue
        desc = re.search(r'name="description" content="([^"]*)"', head)
        import html as html_mod
        text = html_mod.unescape(desc.group(1)) if desc else ""
        m = re.search(r"JAN\s*[:：]\s*(\d{13})", text)
        if m and jan_ok(m.group(1)):
            jan_map[cco] = m.group(1)
    if todo:
        print(f"    家電市場 新商品{len(todo)}件のうち{min(len(todo), KI_DETAIL_BUDGET)}件のJANを確認"
              f"（{len(jan_map)}件判明）", flush=True)
    return prices, jan_map, bad_pages == 0


def parse_rd(text: str) -> list[dict]:
    import html as html_mod
    out = []
    for m in RD_CARD_RE.finditer(text):
        head, janblock, price = m.group(1), m.group(2), m.group(3)
        cond = "新品" if "is-new" in head else ("中古" if "is-used" in head else "")
        nm = re.search(r'product-card-name-link"[^>]*>(.*?)</a>', head, re.S)
        name = html_mod.unescape(re.sub(r"<[^>]+>", "", nm.group(1)).strip()) if nm else ""
        jan = re.search(r"JAN:\s*(\d{8,14})", html_mod.unescape(re.sub(r"<[^>]+>", " ", janblock)))
        out.append({"name": name, "cond": cond, "jan": jan.group(1) if jan else None,
                    "price": int(price.replace(",", ""))})
    return out


def fetch_rudeya(f: Fetcher, limit: int = 0) -> tuple[dict, bool]:
    out: dict[str, dict] = {}
    fails = 0
    cats = RD_CATS[:limit] if limit else RD_CATS
    for i, cid in enumerate(cats, 1):
        t = f.get_text(f"{RD_CATEGORY}{cid}")
        if not t:
            fails += 1
            continue
        got = 0
        for r in parse_rd(t):
            jan = str(r.get("jan") or "")
            if not jan_ok(jan) or r["cond"] != "新品" or r["price"] <= 0:
                continue
            cur = out.get(jan)
            if cur and cur["price"] >= r["price"]:
                continue
            out[jan] = {"price": r["price"], "name": r["name"]}
            got += 1
        if i % 10 == 0:
            print(f"    買取ルデヤ {i}/{len(cats)}カテゴリ: 累計 {len(out):,}件", flush=True)
    complete = fails == 0 and len(out) > 0
    return out, complete


# ---------------------------------------------------------------- 反映

AUTO_NOTE_RE = re.compile(r"^(新品・|新品／)")


def note_for(quotes: dict) -> str:
    order = [SHOP_KI, SHOP_RD, SHOP_KS]
    parts = [f"{s}{quotes[s]:,}円" for s in order if quotes.get(s)]
    return ("新品／" + "・".join(parts)) if parts else ""


def apply(db: dict, ks: dict | None, ks_complete: bool, ki: dict | None, ki_jan: dict | None,
          rd: dict | None, rd_complete: bool, today: str) -> dict:
    items = db.get("items") or []
    by_jan = {it["jan"]: it for it in items if it.get("jan")}
    by_id = {it["id"]: it for it in items}
    by_cco = {it["kc"]: it for it in items if it.get("kc")}
    stat = {"更新": 0, "据え置き": 0, "新規": 0, "値上がり": 0, "値下がり": 0,
            "買取商店": 0, "家電市場": 0, "買取ルデヤ": 0}
    refreshed = set()
    if ks:
        refreshed.add(SHOP_KS)
    if ki:
        refreshed.add(SHOP_KI)
    if rd:
        refreshed.add(SHOP_RD)

    def source_rec(jan: str, name: str, cat: str, price: int, note: str) -> dict:
        """JANの商品を返す（DBに無ければ新規作成）。"""
        rec = by_jan.get(jan)
        if rec:
            return rec
        rec = new_item(jan, name, cat, price, SHOP_KS, today, note)
        items.append(rec)
        by_jan[jan] = rec
        by_id[rec["id"]] = rec
        stat["新規"] += 1
        return rec

    # 1) 買取商店（全件そろった時だけ「載っていない＝掲載終了」として前回値を消す）
    if ks is not None:
        for jan, row in ks.items():
            rec = source_rec(jan, row["name"], row["cat"], row["price"], row["note"])
            rec["quotes"][SHOP_KS] = row["price"]
            stat["買取商店"] += 1
        if ks_complete:
            for jan, rec in list(by_jan.items()):
                q = rec["quotes"]
                # 今日の一覧に載っていない＝掲載終了。ほかの店の額が残っている時だけ消す
                if SHOP_KS in q and jan not in ks and len(q) > 1:
                    del q[SHOP_KS]

    # 2) 家電市場（cco で照合。前回値は消さない＝カテゴリ巡回は部分的なため）
    if ki is not None:
        for cco, row in ki.items():
            rec = by_cco.get(cco)
            if not rec:
                jan = (ki_jan or {}).get(cco)
                if not jan:
                    continue
                rec = by_jan.get(jan)
                if not rec:
                    rec = source_rec(jan, row["name"], map_cat(None, row["name"]), row["price"],
                                     "新品・公開一覧の通常買取額")
                rec["kc"] = cco
                by_cco[cco] = rec
            rec["quotes"][SHOP_KI] = row["price"]
            stat["家電市場"] += 1

    # 3) 買取ルデヤ（JANで照合。前回値は消さない）
    if rd is not None:
        for jan, row in rd.items():
            rec = by_jan.get(jan)
            if not rec:
                rec = source_rec(jan, row["name"], map_cat(None, row["name"]), row["price"],
                                 "新品・カテゴリ別価格表")
            rec["quotes"][SHOP_RD] = row["price"]
            stat["買取ルデヤ"] += 1

    # 4) 最高額と更新日を決め直す（15社の外の店の額は、その店の額として持ち続ける）
    for rec in items:
        q = rec.get("quotes") or {}
        if rec.get("price") and rec.get("shop"):
            own = [x.strip() for x in re.split(r"[・、/]", re.sub(r"（[^）]*）|\([^)]*\)", "", rec["shop"]))
                   if x.strip()]
            for s in own:
                if s not in SOURCES:
                    q[s] = max(q.get(s, 0), int(rec["price"]))
            rec["quotes"] = q
        if not q:
            stat["据え置き"] += 1
            continue
        best_shop = max(q, key=lambda s: (q[s], -SOURCES.index(s) if s in SOURCES else -9))
        best = q[best_shop]
        old_price = int(rec.get("price") or 0)
        if best > old_price:
            stat["値上がり"] += 1
        elif best < old_price:
            stat["値下がり"] += 1
        rec["price"] = int(best)
        if best_shop not in (rec.get("shop") or ""):
            rec["shop"] = best_shop               # 「家電市場（新品）」の表記はそのまま残す
        if best_shop in refreshed:
            rec["date"] = today
        if AUTO_NOTE_RE.match(rec.get("note") or "") or not rec.get("note"):
            n = note_for(q)
            if n:
                rec["note"] = n
        stat["更新"] += 1

    stamp = now_jst()
    db["updated_at"] = today                       # 画面の新旧判定用（YYYY-MM-DD）
    db["updated_at_jst"] = stamp + " JST"          # 実際に取得した時刻
    qu = dict(db.get("quotes_updated") or {})
    quj = dict(db.get("quotes_updated_jst") or {})
    for s in SOURCES:
        if s in refreshed:                         # 取れた店だけ時刻を進める
            qu[s] = today
            quj[s] = stamp
    db["quotes_updated"] = qu
    db["quotes_updated_jst"] = quj
    db["count"] = len(items)
    return stat


# ---------------------------------------------------------------- メイン

def main() -> int:
    ap = argparse.ArgumentParser(description="買取価格の自動更新（scan_db.json）")
    ap.add_argument("--db", default=str(DB_PATH), help="scan_db.json の場所")
    ap.add_argument("--dry-run", action="store_true", help="書き換えずに結果だけ表示")
    ap.add_argument("--source", default="all",
                    choices=["all", "kaitorishouten", "kadenichiba", "rudeya"], help="取得する店を限定")
    ap.add_argument("--limit", type=int, default=0, help="各店のページ数上限（動作確認用）")
    ap.add_argument("--delay", type=float, default=0.2, help="リクエスト間の待ち時間（秒）")
    ap.add_argument("--cache-dir", default="", help="取得結果をこのフォルダに保存（デバッグ用）")
    ap.add_argument("--from-cache", default="", help="取得済みの結果を読む （--cache-dir の保存先）")
    args = ap.parse_args()

    path = Path(args.db)
    if not path.exists():
        print(f"NG: {path} がありません。GitHub から取得した scan_db.json を置いてください。")
        return 1
    try:
        db = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"NG: scan_db.json を読めません: {e}")
        return 1
    if isinstance(db, list):                     # 旧形式（配列だけ）も受け付ける
        db = {"updated_at": today_jst(), "items": db}
    items = db.get("items") or []
    print(f"読み込み: {len(items):,}件（更新日 {db.get('updated_at')}）")

    today = today_jst()
    f = Fetcher(delay=args.delay)
    known_cco = {it["kc"] for it in items if it.get("kc")}
    ks = ki = ki_jan = rd = None
    ks_complete = ki_complete = rd_complete = False

    want_all = args.source == "all"
    cache_in = Path(args.from_cache) if args.from_cache else None
    cache_out = Path(args.cache_dir) if args.cache_dir else None
    if cache_out:
        cache_out.mkdir(parents=True, exist_ok=True)

    def cached(name: str):
        p = (cache_in or cache_out) / f"{name}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save(name: str, data, complete: bool) -> None:
        if not cache_out:
            return
        (cache_out / f"{name}.json").write_text(
            json.dumps({"complete": complete, "at": today, "data": data}, ensure_ascii=False),
            encoding="utf-8")

    if want_all or args.source == "kaitorishouten":
        hit = cached("kaitorishouten") if cache_in else None
        if hit:
            ks, ks_complete = hit.get("data") or {}, bool(hit.get("complete"))
            print(f"[1/3] 買取商店 キャッシュから {len(ks):,}件")
        else:
            print(f"[1/3] 買取商店 公開API（{KS_API}）")
            ks, ks_complete = fetch_kaitorishouten(f, args.limit)
            save("kaitorishouten", ks, ks_complete)
        print(f"      → {len(ks):,}件・{'全件取得' if ks_complete else '一部のみ/失敗あり'}")
    if want_all or args.source == "kadenichiba":
        hit = cached("kadenichiba") if cache_in else None
        if hit:
            ks_ = hit.get("data") or {}
            ki, ki_jan, ki_complete = ks_.get("prices") or {}, ks_.get("jan") or {}, bool(hit.get("complete"))
            print(f"[2/3] 家電市場 キャッシュから 新品価格 {len(ki):,}件")
        else:
            print("[2/3] 家電市場 公開一覧")
            ki, ki_jan, ki_complete = fetch_kaden_ichiba(f, known_cco, args.limit)
            save("kadenichiba", {"prices": ki, "jan": ki_jan}, ki_complete)
        print(f"      → 新品価格 {len(ki):,}件・JAN判明 {len(ki_jan):,}件・{'完全' if ki_complete else '失敗あり'}")
    if want_all or args.source == "rudeya":
        hit = cached("rudeya") if cache_in else None
        if hit:
            rd, rd_complete = hit.get("data") or {}, bool(hit.get("complete"))
            print(f"[3/3] 買取ルデヤ キャッシュから {len(rd):,}件")
        else:
            print("[3/3] 買取ルデヤ カテゴリ別価格表")
            rd, rd_complete = fetch_rudeya(f, args.limit)
            save("rudeya", rd, rd_complete)
        print(f"      → {len(rd):,}件・{'完全' if rd_complete else '失敗あり'}")

    if not any((ks, ki, rd)):
        print("NG: どの店からも取得できませんでした（ネットワーク遮断・サイト仕様変更の可能性）。"
              "scan_db.json は書き換えていません。")
        return 1

    stat = apply(db, ks, ks_complete, ki, ki_jan, rd, rd_complete, today)
    print(f"更新時刻: {now_jst()} JST")
    print("反映:", " / ".join(f"{k} {v:,}" for k, v in stat.items()))

    changed = stat["値上がり"] + stat["値下がり"] + stat["新規"]
    db["count"] = len(db["items"])
    text = json.dumps(db, ensure_ascii=False, separators=(",", ":"))
    if args.dry_run:
        print(f"ドライラン: {len(db['items']):,}件・価格変動 {changed:,}件（ファイルは書き換えていません）")
        return 0
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    print(f"書き込み: {path}（{len(db['items']):,}件 / {len(text):,}バイト / 更新日 {today}）")
    print(f"リクエスト {f.requests:,}回・失敗 {f.failures:,}回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
