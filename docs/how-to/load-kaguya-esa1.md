# KAGUYA ESA1 を読む

## 前提

- `Store` root が決まっている
- KAGUYA PDS3 raw file がある、またはネットワークから取得できる
- 時刻範囲は半開区間 `[start, stop)` で考える

```python
import sopran as spn

store = spn.Store("F:/sopran_data")
kg = spn.Kaguya(store=store)
time = spn.day("2008-01-01")
```

## 1. 予定を確認

```python
kg.esa1.counts.plan(time)
kg.esa1.select("2008-01-01").remote_files()
```

## 2. 読み込む

```python
esa1 = kg.esa1.load(time)
counts = esa1.counts
array = counts.to_xarray()
table = esa1.to_polars("counts")
summed = esa1.to_polars("counts", reduce_look="sum")
```

`counts.to_xarray()` は `time x energy x look` の dense array を返します。
現時点の `energy` は物理 eV ではなく channel index です。
`esa1.to_polars("counts")` は既定で `time` ごとに 1 行を作り、`counts` 列を
`pl.Array` として保持します。完全な long table が必要な場合は
`layout="long"` を明示しますが、未削減の `time x energy x look` は非常に大きく
なるため、通常の表形式出力では `reduce_look="sum"` などで look 次元を畳んでから
使います。SPEDAS 互換の正規化として、
PACE raw count の `65535` は欠測として NaN に変換されます。根拠と注意点は
`kg.esa1.guide()` を参照してください。

pitch angle ごとの energy spectrum が必要な場合は `pitch_angle_spectrum()` を使います。
`look` は index であり、方向そのものではありません。`kg.esa1.energy_flux` endpoint
から呼ぶと、必要な PACE calibration table を読み、結果を Store の `features` layer に
cache してから同じ `SopranArray` として返します。

```python
pas = kg.esa1.energy_flux.pitch_angle_spectrum(
    time,
    magnetic_field=[1.0, 0.0, 0.0],
    cache="use",
)
```

## 3. 図にする

```python
counts.plot()
counts.quicklook("kaguya_esa1_counts", root="reports", y="energy", log_color=True)
pas.plot()
pas.pitch_spectrogram(log_color=True)
pas.energy_spectrogram(pitch=(0.0, 30.0), log_color=True)
kg.esa1.energy_flux.pitch_spectrogram(
    time,
    magnetic_field=[1.0, 0.0, 0.0],
    cache="use",
    log_color=True,
)
```

`plot()` と `quicklook()` は既定で `mode="auto"` です。`time x energy` の
データは energy spectrogram、`time x energy x pitch_angle` のデータは
pitch/time と energy/time の 2 panel overview を選びます。xarray の生の
plot が必要な場合は `plot(mode="raw")` を使います。

`cache="use"` は同じ引数から作った Store variant があれば読み、なければ作成して保存します。
`cache="refresh"` は再計算して上書きし、`cache="never"` は保存せずその場で計算します。
定数磁場や数値配列は自動で variant 化します。外部処理由来の磁場で cache key を固定したい場合は
`variant_id="..."` を明示します。

## download policy

`Kaguya()` の既定は `download="missing"` です。local store に raw file がない場合は
DARTS public PDS3 archive から取得して `Store.raw_path("kaguya", "pds3")` 以下に保存します。

```python
kg.esa1.counts.load(time)
```

offline 解析では `download="never"` を明示します。

```python
kg = spn.Kaguya(store=store, download="never")
```

`SOPRAN_OFFLINE=1` でも既定 policy は `never` になります。
