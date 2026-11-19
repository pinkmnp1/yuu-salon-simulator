# 買取店の自動取得対象（2026-11-19 調査・実装）

`update_prices.py` が毎時自動で取る店と、取れなかった店の理由をまとめたもの。
スキャナーの「15社」は `index.html` の `YS.SCAN_SHOP15` と同じ並び。

## 自動取得している店（8社）

| 店 | 取得元 | 取るもの | 1回の件数 | 備考 |
|---|---|---|---|---|
| 買取商店 | `https://www.kaitorishouten-co.jp/api/v1/products` | 新品 | 約5,813件 | robots.txt で明示許可された公開API。全件巡回 |
| 家電市場 | `https://www.kaden-ichiba.com/item/…` の商品カード | 新品（`prices["0"]`） | 3,595件（JAN判明23件） | 一覧にJANが無いので未登録商品だけ詳細ページでJAN確認（1回40件） |
| 買取ルデヤ | `https://kaitori-rudeya.com/category/detail/{id}` | 新品 | 1,820件 | 63カテゴリ |
| **森森買取**（新） | `https://www.morimori-kaitori.jp/category/{03,01,05,06,04,19,02,31,09,14,15}?page=N` | 新品（`data-cond-new-price`） | 1,563件 | 1ページ50件・最大44ページ。WAFが強く403/タイムアウトが出たらその回は即中断 |
| **携帯空間**（新） | `https://www.keitaispace.co.jp/product/?ca={id}&p={page}` | 未使用／未開封品 | 370件 | 1ページ12件。商品名に `JAN:xxx` が入っている商品だけ（iPhone等はJAN非掲載） |
| **トゥインクル**（新） | `https://twinkle-mobile.com/shop/products/category/0/{1,12,101,111,147/148}?page=N&pageSize=100` | 未開封品／新品 | 749件 | 1ページ100件。iPhone・iPad・ゲーム・カメラ・家電 |
| **ドラゴンモバイル**（新） | `https://mobileone.co.jp/sell.html?cat1={140,142,141,436}&page=N` | 新品 | 604件 | 1ページ24件・最大58ページ。JANが載っている商品のみ |
| **ジェーシカ**（新） | `https://www.jcka-mobile.co.jp/kaitori_price/` | 未開封 | 84件 | 1ページに全機種の価格表。JANｺｰﾄﾞの記載がある機種のみ |

- 追加店はすべて「新品・未開封」の額だけを採用。前回値は消さない（各店の公開範囲が日で変わるため）。
- 失敗した店はその回だけ飛ばし、他店の額と前回値は残す。全店失敗の時だけ終了コード1で止める。

## 取れなかった店（除外リスト）

| 店 | URL | 理由 |
|---|---|---|
| ゲオ | buy.geo-online.co.jp | HTTP 403（WAFがボットを遮断）。UAを変えても不可 |
| 買取楽園 | keitairakuen.com | 一覧にJANが無い（13桁は画像ファイル名だけ）。商品ページも個別取得が必要で非現実的 |
| ケータイゴッド | keitai-god.com | 価格表にJANが無い。状態別（新品/未使用）の区別も無い単一価格 |
| 買取1丁目 | 1-chome.com | Vue製SPA。商品データは `/api` 配下だがエンドポイント仕様が非公開で特定できず |
| 買取ミナモト | kaitoriakiba.com | React製SPA。`/search` は robots.txt で Disallow、商品APIも非公開 |
| モバイルミックス | mobile-mix.jp | ログイン前提のSPA。商品一覧のHTML/APIが無い |
| 買取ホムラ | kaitori-homura.com | SPA（tamagui）。初期HTMLに商品データが無い |
| エノキング | newenoking-kaitori.com | トップは200だが `/products` が HTTP 403 |
| サクモバ | sakumoba.jp | 全商品ページが9MB超でJANは15件のみ。毎時取得に不向き |
| じゃんぱら | janpara.co.jp | 買取価格表にJANが無い |
| イオシス | iosys.co.jp | HTTP 403 |
| 買取Wiki / 海峡通信 / 家電買取アキバ | — | ドメインが解決できない（現存サイトを確認できず） |
| 森森買取の「トレカ」カテゴリ | morimori-kaitori.jp/category/24 | PSA鑑定品が混在し、JANでない13桁番号（2,000,000円級）が入るため対象外 |

## 追加するとしたら次に狙うところ

- ゲオ・イオシスはブラウザ経由（Playwright等）なら読める可能性があるが、GitHub Actions の標準Pythonだけでは不可。
- 買取1丁目・買取ミナモトはAPIの特定ができれば一気に取れる（要ブラウザで通信を観察）。
