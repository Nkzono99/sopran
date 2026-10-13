# データ一覧

SOPRANで扱えるデータ源と、それぞれで実装済みの機能をまとめます。
各ページには、変数の次元・単位・座標系、取得元、校正と品質の扱い、既知の制約を書いています。

## 対応状況

| データ源 | 入口 | 自動取得 | 読み込み | 校正・派生量 | キャッシュ | Pipeline |
|---|---|---|---|---|---|---|
| [KAGUYA PACE](kaguya/pace.md) | `spn.kaguya.esa1`など | ○ DARTS | ○ | エネルギーフラックス、ピッチ角スペクトル | ○ | ○ |
| [KAGUYA LMAG・軌道](kaguya/lmag-orbit.md) | `spn.kaguya.lmag`、`spn.kaguya.orbit` | ○ DARTS | ○ | 軌道幾何、太陽天頂角、磁力線の接続 | ○ | — |
| [KAGUYA LRS](kaguya/lrs.md) | `spn.kaguya.lrs` | ○ DARTS | ○ | 電場強度、パワースペクトル密度 | ○ | — |
| [ARTEMIS](artemis.md) | `spn.artemis` | ○ SPDF | ○ | — | 元ファイルのみ | — |
| [Lunar Prospector](lunar-prospector.md) | `spn.lunar_prospector` | ○ PDS PPI | ○ | — | 元ファイルのみ | — |
| [OMNI](omni.md) | `spn.omni` | ○ SPDF | ○ | 観測時刻への対応付け | 元ファイルのみ | — |
| [月面マップ](moon/index.md) | `spn.moon` | DEMのみ | ○ | 太陽天頂角、日照、影 | — | — |
| [磁気異常カタログ](moon/magnetic-anomalies.md) | `spn.moon.magnetic_anomalies()` | 不要（同梱） | ○ | — | — | — |

「自動取得」は、`download="missing"`（既定）のときに足りない元ファイルを取得してStoreの`raw/`へ置くことを指します。
「キャッシュ」は、計算結果を`cache="use"`でStoreに残せることを指します（[Storeにデータを保存する](../guide/store.md)）。

研究用の試作（電子反射法、波動候補の抽出）は通常の入口から分けて、[試作API](../experimental/index.md)にまとめています。

## 共通の引数

時系列のエンドポイントは、次の引数を共通に受け取ります。

| 引数 | 値 | 意味 |
|---|---|---|
| `time` | `TimeRange` | 期間。`View`や`Case`から呼ぶときは省略できる |
| `download` | `"missing"`、`"never"`、`"always"` | 元ファイルの取得方針（[設定](../guide/configuration.md#ダウンロード方針)） |
| `missing` | `"empty"`、`"warn"`、`"error"` | 元ファイルが無いときに、空の結果を返す・警告して返す・例外にする |
| `cache` | `"use"`、`"refresh"`、`"never"` | 計算結果の再利用（派生量のみ） |

`missing`はKAGUYAのエンドポイントが受け取り、既定は`"empty"`です。元ファイルが欠けても例外にならないため、
長期間を処理するときは欠測を見落とさないよう`missing="warn"`か`"error"`を明示してください。

## 欠測とゼロ

SOPRANは、未取得・未観測・欠損値（fill value）・観測されたゼロを区別して返します。
欠損値は各データの仕様（PACEの`65535`、LRSのCDFのpad値、OMNIの変数別fill値など）に従ってNaNに変え、
観測されたゼロ計数はゼロのまま残します。データごとの規則は各ページにあります。
