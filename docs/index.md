# SOPRAN

SOPRAN は **Satellite Observation Package for Retrieval, Analysis, and
Navigation** の略です。月・惑星圏の衛星データを Python から取得、変換、
保存、可視化するためのライブラリとして整備しています。

主導線は、`spn.kaguya` / `spn.moon` のような shortcut でデータツリーをたどり、
解析時には `View` に期間や領域を束ねる形です。

```python
import sopran as spn

counts = spn.kaguya.esa1.counts.load(spn.day("2008-01-01"))
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy")

view = spn.view(time=spn.day("2008-01-01"), frame="SSE")
flux = view.kaguya.esa1.energy_flux.load()
```

## 入口

| 入口 | 役割 |
| --- | --- |
| `spn.kaguya` / `spn.artemis` / `spn.moon` | default config を使う普段使いの shortcut |
| `Kaguya()` / `Artemis()` / `Moon()` | Store や source を明示する低レベル object |
| `Store()` | raw、normalized parquet、features、database を管理する |
| `Project()` | 使用する `Store`、成果物、project 設定をまとめる |
| `View()` / `spn.view()` | time、region、frame などの一時解析コンテキストを束ねる |
| `Case()` | 保存済み `View` として再現したい解析条件を扱う |
| `Moon()` | DEM、SVM、SZA、shadow などの月面マップを扱う |
| `spn.stack()` | SPEDAS/tplot 的な多段時系列表示を作る |

## データの流れ

```text
provider raw files
  -> Store.raw
  -> decode / normalize
  -> Store.normalized parquet
  -> PlotStack quicklook
  -> time_bins / SampleTable
  -> Store.features or Store.databases
```

## 次に読む

- [インストール](getting-started/installation.md)
- [最初の解析](getting-started/first-analysis.md)
- [KAGUYA/SELENE](missions/kaguya/index.md)
- [実装状況](reference/status.md)
