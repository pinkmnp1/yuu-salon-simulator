# 買取店の自動取得対象（2026-11-19 夜・第2次拡張）

`update_prices.py` が毎時自動で取る店と、取れなかった店の理由をまとめたもの。
スキャナーの店ボタンは `index.html` の `YS.SCAN_SHOP15`（16社）と同じ並び。

## 自動取得している店（10社）

| # | 店 | 取得元 | 取るもの | 1回の件数 | 備考 |
|---|---|---|---|---|---|
| 1 | 買取商店 | `https://www.kaitorishouten-co.jp/api/v1/products` | 新品 | 約5,824件 | robots.txt で明示許可された公開API。全件巡回 |
| 2 | 家電市場 | `https://www.kaden-ichiba.com/item/…` の商品カード | 新品（`prices["0"]`） | 3,595件（JAN判明は少しずつ増加） | 一覧にJANが無いので未登録商品だけ詳細ページでJAN確認（1回40件） |
| 3 | 買取ルデヤ | `https://kaitori-rudeya.com/category/detail/{id}` | 新品 | 1,820件 | 63カテゴリ |
| 4 | 森森買取 | `https://www.morimori-kaitori.jp/category/{id}?page=N` | 新品 | 1,563件 | WAFが強いので間隔を広めに取る |
| 5 | 携帯空間 | `https://www.keitaispace.co.jp/product/?ca={id}&p={page}` | 未使用／未開封 | 370件 | 商品名にJANがある商品だけ |
| 6 | トゥインクル | `https://twinkle-mobile.com/shop/products/category/0/{id}?page=N` | 未開封品／新品 | 749件 | iPhone・iPad・ゲーム・カメラ・家電 |
| 7 | ドラゴンモバイル | `https://mobileone.co.jp/sell.html?cat1={id}&page=N` | 新品 | 607件 | スマホ・家電・ゲーム機・トレカ |
| 8 | ジェーシカ | `https://www.jcka-mobile.co.jp/kaitori_price/` | 未開封 | 84件 | 1ページに全機種。JAN記載のある機種だけ |
| **9** | **買取ホムラ**（新） | `https://api.kaitori-homura.com/api/v1/products?page=N` | 新品・未使用 | **996件**（全94ページ・1,861商品） | アプリ（kaitori-homura.com）が実際に使っている公開JSON API。JANコードと買取価格をそのまま返す |
| **10** | **買取wiki**（新） | `https://gamekaitori.jp/search?q={JAN}` | 買取価格（新品） | 実売データを集めた商品から順次（毎時ローテーション） | 一覧ページにページ送りが無い（Vue/ASP製・POST検索のみ）ため、JAN検索で1商品ずつ取得し `wiki_cache.json` に24時間キャッシュ |

- 追加店はすべて「新品・未開封」の額だけを採用。前回値は消さない（各店の公開範囲が日で変わるため）。
- 失敗した店はその回だけ飛ばし、他店の額と前回値は残す。全店失敗の時だけ終了コード1で止める。
- 買取wiki は JAN が分かっている商品だけの部分取得。`enrich.py` が毎時400件まで補充し、
  全1,800件（家電・カメラ・オーディオで実売価格を集める対象）を約5時間で一巡する。

## 実売価格（高還元家電ランキングの分母）

| 取得元 | 内容 | 更新 |
|---|---|---|
| 価格.com `https://search.kakaku.com/{JAN}/` | 同じJANの販売店一覧から**量販店最安**（ビックカメラ・ノジマ・ソフマップ・ヨドバシ・ヤマダ・Joshin・エディオン・ケーズデンキ・コジマ等）。無ければネット最安 | `enrich.py` が取得、`retail_cache.json` に72時間キャッシュ |

- 中古・ジャンク・箱不良・訳あり・バルク・展示品は価格から除外。
- 買取額が実売以上（還元率100%超）の商品は「限定・プレ値」とみなして
  🏬 高還元家電ランキングから外す（店頭に並ばない品を混ぜないため）。

## 取れなかった店（除外リスト・2026-11-19 夜に再調査）

| 店 | URL | 再調査の結果 |
|---|---|---|
| 買取1丁目 | 1-chome.com | Vue SPA。商品データは `/api/v1/products` だが **HTTP 401「ログインしていません」**。アプリ専用APIでゲスト取得不可 |
| モバイル一番 | mobile-ichiban.com | ASP.NET MVC。商品一覧が **POST検索（タグコード必須）** で、GETでは常に「該当する商品はありませんでした」。タグJSONはJSで組み立てるため未取得 |
| 買取ミナト | kaitoriminato.com | Vue SPA（初期HTML 1.6KB）。`app.js` にAPIパスが無く、価格は認証付きAPIのみ |
| エノキング | newenoking-kaitori.com | `/products` が **Cloudflare「Just a moment...」（HTTP 403）**。トップのみ200 |
| サクモバ | sakumoba.jp | トップは200だが検索が502/404。モバイル版は「現在、このページにアクセスすることはできません」で403 |
| ゲオ | buy.geo-online.co.jp | HTTP 403（WAF）。APIホストも名前解決不可 |
| イオシス | iosys.co.jp | HTTP 403（WAF）。`/api/*` も403 |
| じゃんぱら | janpara.co.jp | トップは200だが全パスが同一トップを返すSPA。買取価格表にJANが無い |
| 買取楽園 | keitairakuen.com | 一覧にJANが無い（13桁は画像ファイル名だけ） |
| ケータイゴッド | keitai-god.com | 価格表にJANが無い。状態別（新品/未使用）の区別も無い |
| 買取ミナモト | kaitoriakiba.com | React SPA。`/search` は robots.txt で Disallow、商品APIも非公開 |
| モバイルミックス | mobile-mix.jp | ログイン前提のSPA |
| ネットオフ | netoff.co.jp | 「買取ナビ」は WordPress のブログで価格検索ではない（`?s=JAN` は記事検索） |
| ブックオフ | bookoff.co.jp | 買取価格の検索ページが無い（404） |
| トレジャーファクトリー | treasure-factory.jp | ドメインが解決できない |
| 買取Wiki（旧ドメイン表記） | — | 現行は `gamekaitori.jp`（家電は `kadenkaitori.tokyo`）。**今回、JAN検索で取得に成功** |

## これ以上増やすなら

- 買取1丁目・買取ミナト・モバイル一番・エノキングは **ブラウザ経由（Playwright）** なら読める可能性が高い。
  GitHub Actions の標準Pythonだけでは不可、VPS の `/opt/pwenv` なら可能。
- ゲオ・イオシスは WAF が datacenter IP を遮断しているため、公式アプリのAPIでも見つからない限り不可。
- 「買取ホムラ」のAPIと同じ形（`/api/v1/products`）の店が他にもある可能性があるため、
  新しい店を見つけたらまず `/api/v1/...` を叩いてみるのが最短。
