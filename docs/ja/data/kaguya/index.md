# KAGUYA/SELENE

KAGUYA（SELENE）は2007年から2009年まで月を周回したJAXAの探査機です。SOPRANは、JAXA DARTSが公開している
PDS3アーカイブから、プラズマ・磁場・電波の観測データと、それに付随する軌道幾何を読み込みます。

```python
import sopran as spn

kg = spn.kaguya          # または spn.Kaguya(store=..., download=...)
time = spn.day("2008-01-01")

flux = kg.esa1.energy_flux.load(time)
b = kg.lmag.magnetic_field.load(time)
wfc = kg.lrs.wfc.ey_power_spectral_density.load(time)
```

## 機器と変数

| 入口 | 機器 | 主な変数 | ページ |
|---|---|---|---|
| `kg.esa1`、`kg.esa2` | PACE ESA-S1/S2（電子） | `counts`、`energy_flux`、`quality` | [PACE](pace.md) |
| `kg.ima`、`kg.iea` | PACE IMA/IEA（イオン） | `counts`、`energy_flux`、`quality` | [PACE](pace.md) |
| `kg.lmag` | LMAG（磁力計） | `magnetic_field`、`magnetic_field_gse`、`magnetic_field_magnitude`、`magnetic_connection` | [LMAGと軌道](lmag-orbit.md) |
| `kg.orbit` | 軌道幾何（LMAGファイルの位置から計算） | `position`、`altitude`、`subpoint`、`sza`など | [LMAGと軌道](lmag-orbit.md) |
| `kg.lrs` | LRS（NPW、WFC） | `npw.rx1`、`wfc.ey_power_spectral_density`など | [LRS](lrs.md) |

各変数の次元と単位は[スキーマ](../../reference/schemas.md)に一覧があります。
`kg.info()`で機器の一覧、`kg.guide()`で同梱の説明を表示できます。

## 元ファイルの取得と置き場所

`download="missing"`（既定）では、Storeに無い元ファイルをDARTSの公開アーカイブから取得し、
配布元のディレクトリ構成のまま`raw/kaguya/pds3/`に置きます。

```text
raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/YYYYMMDD/data/IPACE_PBF1_YYMMDD_<ESA1|ESA2|IMA|IEA>_V003.dat.gz
  sln-l-lmag-3-mag-ts-v1.0/nominal/YYYYMMDD/data/MAG_TSYYYYMMDD.dat
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

既に手元にあるアーカイブを使う場合は、同じ構成でこの下に置くか、`spn.Kaguya(data_root=...)`で
アーカイブのルートを指定します。読み込む前に必要なファイルを確かめるには`plan(time)`を使います。

```python
kg.esa1.counts.plan(time)                         # 必要な元ファイル
kg.esa1.select("2008-01-01").remote_files()       # 配布元でのパス
```

PACEの校正テーブルはSPEDASと同じ配布元から、SPICEカーネルはNAIFとDARTSから取得します。
それぞれ[PACE](pace.md)と[座標変換](../../guide/frames.md)を参照してください。

## 共通の引数

KAGUYAのエンドポイントは`download`、`missing`（既定`"empty"`）、派生量では`cache`を受け取ります。
意味は[データ一覧](../index.md#共通の引数)にまとめています。

## データの有無を調べる

長期間を解析する前に、`coverage()`で日ごと・月ごとのサンプル数と取得済みファイル数を確かめられます。

```python
daily = kg.esa1.counts.coverage(spn.month("2008-02"), freq="day")
```

列の意味は[Storeにデータを保存する](../../guide/store.md#データの有無を集計する)にあります。
