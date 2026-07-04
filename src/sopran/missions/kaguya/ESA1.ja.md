# PACE ESA1

PACE ESA1 は KAGUYA/SELENE の electron spectrum analyzer です。SOPRAN ではまず
raw PBF record を読み、`counts`, `energy_flux`, `energy`, `quality` を共通 schema に
沿って扱えるようにします。

## 主な変数

- `counts`: ESA1 count spectrum。
- `energy_flux`: 未較正 placeholder。現状は NaN で、物理 flux ではありません。
- `energy`: PACE ESA1 energy channel index。物理 eV / bin center は未適用です。
- `quality`: record quality flag。

`counts` は `time x energy x look` の dense array として扱います。Polars/Pandas へ
変換すると、既定では `time` ごとに 1 行を作り、`counts` 列を `pl.Array` として
保持します。完全な long table が必要な場合は `layout="long"` を明示します。
通常の表形式解析では `reduce_look="sum"` などで look 次元を畳んでから使います。

## pitch angle spectrum

`pitch_angle_spectrum()` は、PACE の look bin を FOV/INFO calibration table から
`theta`, `phi` の方向へ戻し、磁場ベクトルとの pitch angle で
`time x energy x pitch_angle` にビン化します。`look` 座標そのものは物理方向ではなく、
方向を表すには calibration table が必要です。

```python
kg = spn.Kaguya()
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration()
esa1 = kg.esa1.load(time, calibration=cal)

# magnetic_field は PACE look direction と同じ frame の 3-vector、
# または frame_context で変換できる SopranArray を渡します。
pas = esa1.pitch_angle_spectrum(
    magnetic_field=[1.0, 0.0, 0.0],
    pitch_bins="native",
)
pas.to_xarray()
pas.plot()
pas.pitch_spectrogram(log_color=True)
pas.energy_spectrogram(pitch=(0.0, 30.0), log_color=True)
```

`pitch_bins="native"` は 4x16 angular record では 16 bins、16x64 record では
32 bins を使います。混在する日は大きい側に合わせます。frame が一致しない磁場を
渡す場合は `spiceypy` と必要な SPICE kernel を設定した `FrameContext` が必要です。
`pas.plot()` は既定の `mode="auto"` により pitch/time と energy/time の 2 panel
overview を返します。

## raw count の 65535

JAXA/DARTS の PACE format 文書では、PBF1 の ESA count field は `USHORT cnt[...]`
として定義されています。例として ESA type 00 は `cnt[32][16][64]`、type 01 は
`cnt[32][4][16]` です。

ただし、確認した PDS3 label には `MISSING_CONSTANT = 65535` のような明示的な
missing-value 宣言はありませんでした。SOPRAN では SPEDAS の KAGUYA PACE reader に
合わせ、`uint(-1)`、つまり 16-bit unsigned の最大値 `65535` を欠測として NaN に
変換します。SPEDAS の `kgy_read_pbf.pro` は「`65535 = uint(-1)` と
`4294967295 = ulong(-1)` は NaN を意味する」と記述しており、`kgy_esa1_get3d.pro`
でも `cnt eq uint(-1)` を `!values.f_nan` に置き換えています。

参照:

- JAXA/DARTS PACE format: https://darts.isas.jaxa.jp/app/pdap/selene/help/en/PACE_Format_en_V01.pdf
- 例 PDS3 label: https://data.darts.isas.jaxa.jp/pub/pds3/sln-l-pace-3-pbf1-v3.0/20080802/data/IPACE_PBF1_080802_ESA1_V003.lbl
- SPEDAS `kgy_read_pbf.pro`: https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_read_pbf.pro
- SPEDAS `kgy_esa1_get3d.pro`: https://raw.githubusercontent.com/spedas/bleeding_edge/master/idl/projects/kaguya/map/pace/kgy_esa1_get3d.pro

PACE の FOV / INFO calibration table は低レベル reader で読み込めます。

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")
cal = kg.esa1.load_calibration(download="never")
cal.coverage("ESA1")

esa1 = kg.esa1.load(time, calibration=cal)
esa1.to_xarray().attrs["calibration"]
```

同じ reader は低レベル API としても使えます。

```python
from sopran.missions.kaguya import PaceCalibration, read_pace_fov, read_pace_info

cal = PaceCalibration(
    fov=read_pace_fov(["esas1-ch_angle", "esas1-pol_angle-RAM0"]),
    info=read_pace_info(["ESA-S1_ENE_POL_AZ_GFACTOR_4X16_20090828.dat"]),
)
cal.coverage("ESA1")
```

これは table を構造化する入口です。`calibration=cal` を渡すと coverage metadata は
`tables_loaded_not_applied` として残りますが、物理較正済み `energy_flux`、energy 座標、
look-angle 座標への全面的な適用はまだ今後の作業です。`pitch_angle_spectrum()` は
counts を pitch angle へ binning するために必要な範囲で calibration table を使います。

## 例

```python
import sopran as spn

kg = spn.Kaguya()
time = spn.day("2008-01-01")

esa1 = kg.esa1.load(time)
counts = esa1.counts
array = counts.to_xarray()
table = esa1.to_polars("counts")
summed = esa1.to_polars("counts", reduce_look="sum")
pas = esa1.pitch_angle_spectrum([1.0, 0.0, 0.0])
pas.plot()
item = counts.spectrogram(y="energy", log_color=True)
```

`energy_flux` などの variable endpoint からもこの guide を参照します。
