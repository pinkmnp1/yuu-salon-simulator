#!/usr/bin/env python3
"""ゆうサロンスキャナー: 家電・カメラ向けの『実売価格（価格.com）』と『買取wiki』の価格を集める。

- 対象: scan_db.json の家電・カメラ・オーディオ商品（JANあり・買取3,000円以上）
- 実売: 価格.com の JAN 検索。量販店（ビック・ノジマ・ソフマップ・ヨドバシ・ヤマダ・Joshin等）の
        最安を採用し、無ければネット最安。中古・ジャンク・箱不良は除外。
- 買取wiki: gamekaitori.jp の JAN 検索（買取価格）。
- 結果は /opt/scanner/retail_cache.json と wiki_cache.json に貯め、24〜72時間は再利用。
"""
import json, os, re, sys, time, html, urllib.request, gzip

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
BASE = "/opt/scanner"
DB = BASE + "/scan_db.json"
RETAIL = BASE + "/retail_cache.json"
WIKI = BASE + "/wiki_cache.json"

GEN = ("炊飯", "レンジ", "オーブン", "トースター", "ドライヤー", "掃除機", "テレビ", "レコーダー",
       "カメラ", "レンズ", "スピーカー", "ヘッドホン", "イヤホン", "洗濯機", "冷蔵庫", "エアコン",
       "食洗", "ミシン", "コーヒー", "ケトル", "電気ポット", "ホットプレート", "空気清浄", "加湿",
       "扇風機", "アイロン", "シェーバー", "美顔", "電動歯ブラシ", "体重計", "ミキサー", "プリンタ",
       "照明", "炊きたて", "オーブンレンジ", "ヘルシオ", "ビエラ", "ブラビア", "アクオス", "レグザ",
       "プロジェクター", "スピーカー", "サウンドバー", "ウォークマン", "ラジオ", "ドライヤー", "ヘアアイロン")
BIG = ("ビックカメラ", "ノジマ", "ソフマップ", "ヨドバシ", "ヤマダ", "Joshin", "ジョーシン",
       "エディオン", "ケーズデンキ", "コジマ", "ベスト電器", "デオデオ", "ミドリ電化", "イオン",
       "楽天ビック", "キタムラ")  # 2026-11-19: Amazonは店頭値引き対象外なので入れない（ページ側の店頭判定と合わせる）
BAD = ("中古", "ジャンク", "訳あり", "箱不良", "箱損", "バルク", "再生", "質屋", "used", "USED",
       "アウトレット", "展示品", "開封", "傷あり", "現状品", "部品取り", "ジャンク品")

def now():
    return int(time.time())

def load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)

def fetch(url, timeout=20, enc=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja",
                                               "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        if enc:
            return b.decode(enc, "replace")
        ct = r.headers.get("Content-Type", "")
        return b.decode("cp932" if ("sjis" in ct or "shift_jis" in ct) else "utf-8", "replace")

def kakaku(jan):
    t = fetch("https://search.kakaku.com/%s/" % jan, enc="cp932")
    out = []
    for blk in re.split(r'class="c-list1_cell p-resultItem s-resultItem"', t)[1:]:
        m = re.search(r'<p class="p-item_name">\s*<a[^>]*>(.*?)</a>', blk, re.S)
        p = re.search(r'p-item_priceNum">([\d,]+)<', blk)
        s = re.search(r'<img[^>]*alt="([^"]{2,30})"[^>]*>', blk)
        if not (m and p):
            continue
        name = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        shop = html.unescape(s.group(1)).strip() if s else ""
        out.append({"name": name, "price": int(p.group(1).replace(",", "")), "shop": shop})
    clean = [r for r in out if r["price"] >= 500 and not any(w in r["name"] for w in BAD)]
    if not clean:
        return None
    big = [r for r in clean if any(b in r["shop"] for b in BIG)]
    best = min(big, key=lambda r: r["price"]) if big else min(clean, key=lambda r: r["price"])
    ps = sorted(r["price"] for r in clean)
    return {"retail": best["price"], "shop": best["shop"], "src": "量販店最安" if big else "ネット最安",
            "lo": ps[0], "hi": ps[-1], "n": len(clean), "at": now()}

def wiki(jan):
    t = fetch("https://gamekaitori.jp/search?q=%s" % jan)
    m = re.search(r"買取価格[:：]\s*(?:<[^>]+>\s*)*([\d,]+)\s*円", t)
    if not m:
        return {"price": 0, "at": now()}
    nm = re.search(r'<li class="sub-pro-name">[\s\S]{0,200}?<a[^>]*title="([^"]*)"', t)
    return {"price": int(m.group(1).replace(",", "")), "at": now(),
            "name": html.unescape(nm.group(1))[:90] if nm else ""}

PRIORITY = ("炊飯", "炊きたて", "電子レンジ", "オーブンレンジ", "レンジ", "オーブン",
            "ドライヤー", "ヘアアイロン", "掃除機", "クリーナー", "シェーバー", "美顔",
            "テレビ", "レコーダー", "カメラ", "レンズ", "イヤホン", "ヘッドホン", "スピーカー")

def _prio(name):
    for i, k in enumerate(PRIORITY):
        if k in name:
            return i
    return 99


def candidates(db):
    items = db.get("items", [])
    out = []
    for it in items:
        jan = it.get("jan") or ""
        if len(jan) != 13 or not jan.isdigit():
            continue
        if it.get("cat") not in ("家電", "カメラ", "オーディオ", "XR"):
            continue
        if (it.get("price") or 0) < 3000:
            continue
        if not any(k in (it.get("name") or "") for k in GEN):
            continue
        out.append((_prio(it.get("name") or ""), jan))
    seen = set()
    ordered = []
    for _p, jan in sorted(out):
        if jan in seen:
            continue
        seen.add(jan)
        ordered.append(jan)
    return ordered

def main():
    only = None
    limit = 0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--limit":
            limit = int(args[i + 1])
        if a == "--jan":
            only = args[i + 1]
    db = load(DB, {})
    jans = [only] if only else candidates(db)
    retail = load(RETAIL, {})
    wik = load(WIKI, {})
    t0 = time.time()
    done = 0
    for jan in jans:
        r = retail.get(jan)
        if not r or now() - r.get("at", 0) > 72 * 3600 or r.get("retail", 0) == 0 and now() - r.get("at", 0) > 6 * 3600:
            try:
                got = kakaku(jan)
                if got:
                    retail[jan] = got
                else:
                    retail.setdefault(jan, {"retail": 0, "at": now()})
            except Exception as e:
                retail.setdefault(jan, {"retail": 0, "at": now(), "err": str(e)[:60]})
            time.sleep(0.6)
        w = wik.get(jan)
        if not w or now() - w.get("at", 0) > 24 * 3600:
            try:
                wik[jan] = wiki(jan)
            except Exception as e:
                wik[jan] = {"price": 0, "at": now(), "err": str(e)[:60]}
            time.sleep(0.5)
        done += 1
        if done % 25 == 0:
            save(RETAIL, retail)
            save(WIKI, wik)
            hit = sum(1 for v in retail.values() if v.get("retail"))
            wh = sum(1 for v in wik.values() if v.get("price"))
            print("[%d/%d] retail=%d wiki=%d %.1fmin" % (done, len(jans), hit, wh, (time.time() - t0) / 60), flush=True)
        if limit and done >= limit:
            break
    save(RETAIL, retail)
    save(WIKI, wik)
    print("done", done, "of", len(jans), "%.1f min" % ((time.time() - t0) / 60), flush=True)

if __name__ == "__main__":
    main()
