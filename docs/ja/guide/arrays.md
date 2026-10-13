# 読み込んだ配列を扱う

エンドポイントの`load()`が返す`SopranArray`は、`xarray.DataArray`に変数名・スキーマ（次元・単位・座標系）・
期間・出典ファイル・処理履歴を付けた型です。このページでは、切り出し・集約・再ビン化・表への変換・保存を扱います。
図の描き方は[可視化](plotting.md)、別の機器の時刻へ合わせる方法は[時刻をそろえる](alignment.md)にあります。

## 中身を確かめる

```python
flux = spn.kaguya.esa1.energy_flux.load(time)

flux.info()       # 名前、次元、期間、単位
flux.schema       # VariableSchema（次元・単位・座標系・別名）
flux.trange       # 読み込んだ期間（TimeRange）
flux.files        # 出典の元ファイル
flux.metadata     # 型・名前・期間・スキーマ・出典・処理履歴をまとめた辞書
flux.xr           # 中身の xarray.DataArray
```

`metadata`はJSONに書き出せる形で、図やStoreへ保存するときの来歴（provenance）としてそのまま使われます。

## 切り出しと集約

xarrayでよく使う操作は`SopranArray`から直接呼べます。結果も`SopranArray`で、スキーマの次元は結果に合わせて更新されます。

```python
band = flux.isel(energy=slice(4, 12)).mean("energy")
positive = flux.where(flux.xr > 0)
hour = flux.sel(time=slice("2008-02-01T03:00", "2008-02-01T04:00"))
```

時間方向の平均化には`resample`を使います。

```python
ten_min = flux.resample(time="10min").mean()     # mean, sum, median, max, first, last
```

これら以外の操作は`flux.xr`でxarrayへ降りて行います。その結果は素の`DataArray`になり、単位や出典は引き継がれません。

## ビンを組み直す

`rebin`は、数値の座標を持つ軸を指定したビン境界で集計し直します。エネルギー、ピッチ角、周波数、
地図の経度・緯度に同じ書き方が使えます。

```python
coarse = flux.rebin(axis="energy", bins=[10, 30, 100, 300, 1000], reduction="mean")

# 複数の軸は辞書で一度に指定する（pas はピッチ角スペクトル）
pas.rebin(bins={
    "energy": [10, 100, 1000, 10000],
    "pitch_angle": [0, 30, 60, 90, 120, 150, 180],
})
```

`reduction`の既定は`"sum"`です。カウントは足し合わせ、フラックスのように平均すべき量は`"mean"`を指定してください。
ほかに`"median"`、`"min"`、`"max"`、`"count"`を使えます。

## 処理履歴

`rebin`、`resample`、`peak_trace`、`resample_like`、`transform`は、操作名と引数を
`metadata["operations"]`に追記します。

```python
coarse.metadata["operations"]
# [{'operation': 'rebin', 'parameters': {'axis': 'energy', 'bins': [10.0, ...], 'reduction': 'mean'}}]
```

この履歴は`quicklook()`の記録と、`write_parquet()`で作るStoreのマニフェスト（`parameters.operations`）に
自動で引き継がれます。`sel`・`isel`・`mean`・`where`は次元を更新しますが、履歴には記録しません。

## 表に変換する

| 呼び出し | 返り値 |
|---|---|
| `to_xarray()` | `xarray.DataArray` |
| `to_polars(layout=...)` | `polars.DataFrame` |
| `to_pandas(layout=...)` | `pandas.DataFrame` |

`layout`は表の形を決めます。

| `layout` | 形 |
|---|---|
| `"auto"`（既定） | 3次元以上なら`"array"`、それ以外は`"long"` |
| `"array"` | 時刻ごとに1行。残りの次元は`pl.Array`型の1列に入る |
| `"long"` | 全次元を展開した縦長の表。各次元の座標が列になる |

`"long"`は要素数がそのまま行数になるため、PACEの`time × energy × look`を1日分展開すると非常に大きくなります。
既定では1000万行を超えると例外にしています。上限は`max_rows`で変えられ、`allow_large=True`で解除できます。
PACEの機器単位の読み込み結果では、`esa1.to_polars("counts", reduce_look="sum")`のように
`look`を合計してから表にできます。

## Parquetに保存する

1つの配列をStoreのデータセットとして保存するには`write_parquet`を使います。

```python
record = coarse.write_parquet(store, dataset_id="analysis.esa1.coarse_flux", layer="features")
record.scan().collect()
```

マニフェスト・スキーマ・カタログが一緒に作られ、後から`store.scan_dataset(...)`で読めます。
既存のデータセットがあると止まります。上書きは`overwrite=True`、追記は`append=True`を明示します。
長期間を日ごとに保存するなら[バッチ処理](pipeline.md)のほうが向いています。
Storeの層の使い分けは[Storeにデータを保存する](store.md)を参照してください。
