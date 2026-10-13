# PACE（電子・イオン）

PACE（Plasma energy Angle and Composition Experiment）は、KAGUYAに搭載された4台の粒子分析器です。
SOPRANは公開PBF1（v3.0）を読み、4台とも同じ変数名で扱います。

| 入口 | センサー | 測る粒子 |
|---|---|---|
| `kg.esa1` | ESA-S1 | 電子 |
| `kg.esa2` | ESA-S2 | 電子 |
| `kg.ima` | IMA | イオン（質量分析） |
| `kg.iea` | IEA | イオン |

## 変数

| 変数 | 次元 | 単位 | 内容 |
|---|---|---|---|
| `counts` | `time, energy, look` | count | 生のカウント |
| `energy_flux` | `time, energy, look` | eV/(cm^2 s sr eV) | 校正テーブルでカウントから求めた微分エネルギーフラックス |
| `energy` | `energy` | channel / eV | 未校正ではエネルギーチャンネル番号、校正済みではエネルギー中心値（eV） |
| `quality` | `time` | flag | 記録の品質フラグ |

`look`は検出器の視線方向の番号で、方向そのものではありません。方向（極角・方位角）を得るには
校正テーブルが必要で、下のピッチ角スペクトルはこれを使って計算します。
`energy_flux`には別名`eflux`、`differential_energy_flux`があります。

## 読み込む

```python
kg = spn.kaguya
time = spn.day("2008-01-01")

flux = kg.esa1.energy_flux.load(time)       # SopranArray
esa1 = kg.esa1.load(time)                   # 機器単位の読み込み結果

esa1.counts, esa1.energy_flux, esa1.quality
esa1.to_xarray()                            # 全変数の xarray.Dataset
esa1.to_polars("counts", reduce_look="sum") # look を合計した表
esa1.files                                  # 元ファイル
esa1.pace                                   # デコード直後のヘッダーと記録
```

元ファイルを直接デコードするには`sopran.missions.kaguya.read_pace_pbf(files)`を使います。
デコードはRust拡張で行い、拡張が無い環境ではPythonの参照実装に切り替わります（`backend="auto"`）。

## エネルギーフラックスの校正

`energy_flux`は次の式でカウントから求めます。

$$
\mathrm{energy\_flux} = \frac{\mathrm{counts}}{t_\mathrm{integ}\; G\; \varepsilon}
$$

$t_\mathrm{integ}$は積分時間、$G$はPACE INFOテーブルのgファクター、$\varepsilon$は検出効率です。
$\varepsilon$の既定値0.6は、SPEDASの`kgy_esa1_get3d.pro`・`kgy_esa2_get3d.pro`が使う一様な値です。
別の値を使うときは`kg.esa1.load(time).to_energy_flux(efficiency=...)`を呼びます。

校正テーブル（INFOとFOV）は既定で自動的に読み込みます。取得元はSPEDASの`kgy_read_inf.pro`・`kgy_read_fov.pro`と
同じ配布元で、HTTPでのみ公開されています。取得したテーブルはURLとsha256をStoreの元ファイル台帳に記録します。
テーブルが無いと`energy_flux`の読み込みは例外になり、未校正の値を返すことはありません。
校正後は`energy`座標がeVの中心値になり、元のチャンネル番号は`energy_channel`座標に残ります。

```python
cal = kg.esa1.load_calibration(download="never")   # テーブルを明示的に読む
esa1 = kg.esa1.load(time, calibration=cal)
```

4台とも同じ式とテーブルの読み方で計算します。回帰テストはESA1で行っており、
ESA2・IMA・IEAのフラックスはSPEDASとの数値照合をまだ行っていません。

## 欠測値65535

PBF1のカウントは16ビット符号なし整数です。SOPRANは、SPEDASのPACE読み込み処理（`kgy_read_pbf.pro`、
`kgy_esa1_get3d.pro`）に合わせて、最大値`65535`を欠測としてNaNに変えます。
確認したPDS3ラベルには`MISSING_CONSTANT`のような欠測値の宣言はありません。ゼロのカウントはゼロのまま残します。

## ピッチ角スペクトル

`pitch_angle_spectrum()`は、校正テーブルで`look`を方向に戻し、磁場とのなす角でビンに分けて
`time × energy × pitch_angle`の配列を作ります。

```python
from sopran.missions.kaguya import selene_spice_kernels

b = kg.lmag.magnetic_field.load(time)                         # MOON_ME
frames = spn.FrameContext(spice_kernels=selene_spice_kernels(kg.store, time))   # 月と機体姿勢のカーネルを取得

pas = kg.esa1.energy_flux.pitch_angle_spectrum(
    time,
    magnetic_field=b,
    frame_context=frames,             # MOON_ME の磁場を PACE の視線の座標系へ回す
    pitch_bins="native",
    cache="use",
)
pas.plot()                                          # ピッチ角と時刻、エネルギーと時刻の2段
pas.energy_spectrogram(pitch=(0.0, 30.0), log_color=True)
```

`magnetic_field=[1.0, 0.0, 0.0]`のように視線と同じ座標系の固定ベクトルを渡せば、カーネル無しで試せます。

| 引数 | 意味 |
|---|---|
| `magnetic_field` | 必須。PACEの視線と同じ座標系のベクトル、または座標系を持つ`SopranArray` |
| `look_frame`、`magnetic_frame` | 視線（既定`SELENE_M_SPACECRAFT`）と磁場の座標系。異なるときは`frame_context`に`FrameContext`を渡す |
| `pitch_bins` | `"native"`（4×16方向の記録は16ビン、16×64方向は32ビン。混在する日は大きい方）、ビン数、またはビン境界 |
| `min_look_bins` | ピッチ角ビンに入る視線の最小数 |
| `count_correction` | `"none"`（既定）、`"event"`、`"trash"`、`"event_trash"`。SPEDASの`/cntcorr`に相当する補正 |
| `cache` | `"use"`なら同じ引数の結果を`features`層に保存して再利用する |

`count_correction="trash"`は、捨てられたカウント（trash counter）を方位方向に配り直し、`"event"`は隣り合う
エネルギーの組をイベントカウンターに合わせて拡大します。補正は倍率として別に持ち、生のカウントは整数のまま残します。

結果には、記録ごとの露出時間と、`pace_data_mode`、`pace_data_type`、`pace_submode`、`pace_svs_tbl`、
`pace_data_quality`、`record_duration_seconds`の座標が付きます。ピッチ角に使える記録かどうかは
観測モードから判定しており、その規則は[PACE ESAのmode判定](esa-mode-policy.md)にあります。

## Parquetに保存する

```python
record = (
    kg.esa1.energy_flux.pipeline(spn.period("2008-01-01", "2008-01-03"))
    .calibrate(calibration="auto")
    .write("kaguya.esa1.energy_flux", layer="normalized", partition="day")
    .run()
)
```

カウントのまま保存するときは`kg.esa1.counts.pipeline(...)`から`calibrate`を除きます。
実行方法の詳細は[バッチ処理](../../guide/pipeline.md)にあります。

## 制約

- 保存したParquetには、`look`の方向（極角・方位角）とエネルギーの座標情報をまだ含めていません。
- ESA2・IMA・IEAのエネルギーフラックスは、SPEDASとの数値照合が未実施です。
- `data_quality`のビットの意味は公開資料で確定していないため、値はそのまま`pace_data_quality`に残します。

## 出典

- [PACE形式説明（JAXA DARTS）](https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20071107/document/PACE_Format_en_V01.pdf)
- [SPEDAS `kgy_read_pbf.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_read_pbf.pro)、
  [`kgy_esa1_get3d.pro`](https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro)
