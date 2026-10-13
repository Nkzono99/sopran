# ARTEMIS

ARTEMISは、THEMISのP1・P2の2機を月周回軌道へ移したNASAのミッションです。
SOPRANでは探査機・機器・変数の順にたどる入口を用意していますが、**元ファイルの取得とCDFの読み込みはまだ実装していません。**
現在読めるのは、利用者がStoreに保存した正規化済みのParquetだけです。

## 変数

| 入口 | 次元 | 単位 | 内容 |
|---|---|---|---|
| `art.p1.fgm.magnetic_field`（`p2`も同じ） | `time, component` | nT | FGMの磁場ベクトル。別名`b` |
| `art.p1.esa.ion_energy_flux` | `time, energy` | eV/(cm^2 s sr eV) | ESAのイオン微分エネルギーフラックス |

## 読み込む

```python
art = spn.artemis
time = spn.day("2011-07-01")

art.p1.fgm.magnetic_field.plan(time)       # 読みに行くデータセットID
b = art.p1.fgm.magnetic_field.load(time)

spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time, y="energy", log_color=True),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
).plot()
```

`load()`は`normalized`層の`artemis.p1.fgm.magnetic_field`のようなデータセットを読みます。
データセットが無いと、作り方の案内を付けた`DatasetNotFoundError`になります。
別の手段で用意した表は`Store.write_parquet_dataset(..., layer="normalized")`で保存すると読めるようになります。

```python
lazy = store.scan_dataset("artemis.p1.fgm.magnetic_field", layer="normalized")
```

## 今後

CDAWeb・HAPIからの取得、CDFの読み込み、座標系・成分・エネルギービンのメタデータの保存が未実装です。
