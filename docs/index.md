# SOPRAN

SOPRAN は **Satellite Observation Package for Retrieval, Analysis, and
Navigation** の略です。月・惑星圏の衛星データを Python から取得、変換、
保存、可視化するためのライブラリとして整備しています。

最初に目指す利用感は、ミッションや観測機器をオブジェクトとしてたどる形です。

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
moon = spn.Moon()

time = spn.day("2008-01-01")
counts = kg.esa1.counts.load(time)
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy")
```

## 入口

| 入口 | 役割 |
| --- | --- |
| `Kaguya()` / `Artemis()` | ミッション、探査機、観測機器をたどる |
| `Store()` | raw、normalized parquet、features、database を管理する |
| `Project()` / `Case()` | 解析期間、領域、成果物、既定値をまとめる |
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
