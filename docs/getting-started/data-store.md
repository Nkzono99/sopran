# データストア

`Store` は raw file、normalized parquet、派生 features、解析 database を同じ
root の下で管理します。

```python
store = spn.Store("F:/sopran_data")
```

## レイヤ

| layer | 置くもの |
| --- | --- |
| `raw` | ダウンロードした provider 元ファイル |
| `normalized` | 観測機器の値を parquet 化したもの |
| `features` | 時間ビンで対応づけた特徴量や派生指標 |
| `models` | 較正、推定、学習済みモデル |
| `databases` | 利用者やプロジェクト固有の curated product |
| `cache` | 再生成可能な一時ファイル |

## raw file

Provider のディレクトリやファイル名は保ちます。

```text
F:/sopran_data/raw/kaguya/pds3/
  sln-l-pace-3-pbf1-v3.0/20080101/data/IPACE_PBF1_080101_ESA1_V003.dat.gz
```

## parquet dataset

正規化後の dataset は manifest、schema、catalog、shard を持ちます。

```text
dataset.json
schema.json
catalog.parquet
shards/
```

```python
lazy = store.scan_dataset("kaguya.esa1.counts", layer="normalized")
frame = lazy.collect()
```

## 探索

```python
index = store.datasets(refresh=True)
normalized = store.datasets(layer="normalized")
raw_files = store.raw_files(refresh=True, mission="kaguya")
```
