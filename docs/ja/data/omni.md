# OMNI

NASAのOMNI2は、地球近傍の太陽風と惑星間磁場、地磁気指数を1時間ごとにまとめたデータセットです。
SOPRANはその1時間値を読み、月周辺の観測の上流条件として参照できるようにします。
年ごとのテキストファイルを、足りないときにNASA SPDFから取得してStoreに置きます。

読み込みには`xarray`、作図には`matplotlib`が必要です（`[kaguya,viz]`に含まれます）。

```python
import sopran as spn

time = spn.day("2008-05-01")

data = spn.omni.load(time)
data.to_dataframe()          # UTCの時刻を索引にしたスカラー変数の表（pandas）
data.to_xarray()             # GSEの磁場ベクトルも含む xarray.Dataset
data["bz_gsm"]               # SopranArray

spn.omni.pressure.plot(time)
spn.omni.variable("alpha_proton_ratio").plot(time)
```

`View`から使う場合は`view.omni.pressure.plot()`、Storeとダウンロード方針を独立させたい場合は
`spn.Omni(store=spn.Store("/path/to/sopran_data"), download="never")`を使います。

## 変数

| 名前 | 単位 | 内容 |
|---|---|---|
| `pressure` | nPa | 公開されている太陽風の動圧。密度と速度から再計算しない |
| `speed` | km/s | 太陽風の速さ |
| `density`、`temperature` | cm^-3、K | 陽子の密度・温度 |
| `magnetic_field` | nT | 平均磁場ベクトル（GSEのx/y/z） |
| `b_magnitude` | nT | 磁場の強さの平均。平均ベクトルの大きさとは異なる |
| `bx_gse`、`by_gse`、`bz_gse` | nT | GSE成分 |
| `by_gsm`、`bz_gsm` | nT | GSM成分 |
| `beta`、`alfven_mach`、`magnetosonic_mach` | 1 | プラズマベータ、マッハ数 |
| `alpha_proton_ratio` | 1 | アルファ粒子と陽子の数密度比 |
| `electric_field` | mV/m | 公開されている対流電場の指標（速度とGSMのBzから計算された値） |
| `kp` | 1 | Kp指数。ファイルのKp×10を0.1倍した値 |
| `dst`、`ae`、`al`、`au` | nT | 地磁気活動指数 |
| `imf_spacecraft_id`、`plasma_spacecraft_id` | 1 | 出典の探査機ID |
| `imf_sample_count`、`plasma_sample_count` | 1 | 1時間平均に使った元のサンプル数 |

代表的な変数は`spn.omni.pressure`のようなエンドポイントで、すべてのスカラー変数は`spn.omni.variable(name)`で使えます。

## 観測時刻に対応付ける

```python
upstream = spn.omni.at([
    "2008-05-01T00:10:00Z",
    "2008-05-01T00:59:59Z",
    "2008-05-01T01:00:00Z",
])
```

`at()`は各時刻を含む1時間の値を返します。上の例では、最初の2つが00:00〜01:00、最後が01:00〜02:00の値です。
入力の順序と重複を保ち、補間も欠損の前方埋めもしません。`source_time`列は対応した元の時間ラベルです。
その時間の記録自体が無ければ`NaT`、記録はあっても変数が欠損値ならその変数が`NaN`になります。
タイムゾーンの無い時刻はUTCとして扱い、`NaT`の入力は受け付けません。

`load(start, stop)`は時間ラベルについて半開区間`[start, stop)`を選びます。00:30から始めると00:00のラベルは含まれません。
00:30時点の上流条件が欲しいときは`at()`を使います。欠損は公式の変数別のfill値で判定し、記録の無い時間を補いません。

## 取得

| `download` | 動作 |
|---|---|
| `missing`（既定） | 未取得の年だけ取得する |
| `never` | 通信しない。足りないと`FileNotFoundError` |
| `always` | 取得し直す。進行中の年を更新するときにも使う |

取得はタイムアウト付きで一時ファイルへ書き、内容と年を確かめてから置き換えます。失敗しても以前のファイルは残ります。
新しく取得したファイルはチェックサムをStoreの台帳に記録します。置き場所は`raw/omni/omni2_YYYY.dat`です。

## 5分値（HRO）と速度ベクトル

`spn.omni.hro`は、CDAWebの月別CDF（`omni_hro_5min_YYYYMM01_v01.cdf`）から5分値を読みます。
1時間値に無い太陽風速度ベクトル`velocity`（GSE、km/s）と、NASAが時間シフトに使った`bsn_x`・`timeshift`を含みます。
読み込みには`cdflib`が必要です（`[kaguya]`に含まれます）。置き場所は`raw/omni/hro_5min/YYYY/`です。

```python
hro = spn.omni.hro.load(spn.period("2008-04-01", "2008-04-03"))
hro.to_dataframe()                     # vx_gse, vy_gse, vz_gse, speed, density, pressure, bsn_x, ...
hro.velocity                           # SopranArray (time, component) in GSE
hro.at(["2008-04-02T08:34:00Z"], tolerance_seconds=600)   # 最近傍の標本。補間しない
```

公開値の$V_y$は地球公転による収差を除いた値です。地心の流れ方向が必要なときは
`OMNI_ABERRATION_CORRECTION_KM_S`（$+29.8\,\mathrm{km/s}$）を一度足します。時刻はbow shock noseへの到達時刻のままで、
月への伝搬は[dHT座標系](../experimental/dht.md)が扱います。

## 解釈上の注意

- OMNIは地球近傍の上流条件を表す資料で、月の位置での太陽風の直接測定ではありません。
  月までの追加の時間ずれや、月が磁気圏の内側にいるかどうかの判定はこのAPIでは行いません。
- GSEとGSMの値をそのまま返します。`View`の`frame`を指定しても他の座標系へは回転しません。
- 1分値と、hourly・5分値それぞれの全変数の網羅には対応していません。

出典：[NASA OMNIの仕様](https://omniweb.gsfc.nasa.gov/html/ow_data.html)、
[NASA SPDFの公開ファイル](https://spdf.gsfc.nasa.gov/pub/data/omni/low_res_omni/)
