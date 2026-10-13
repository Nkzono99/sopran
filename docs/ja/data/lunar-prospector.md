# Lunar Prospector

Lunar Prospector（LP）は1998年1月〜1999年7月に月を周回したNASAの探査機で、磁力計（MAG）と電子反射計（ER）を積んでいました。
ERは、月面の磁場で電子が反射される割合から表面磁場を推定する手法（電子反射法）の元になった観測です。
SOPRANはPDS PPIノードのLevel 1Bデータ（ボリュームLP_1201〜LP_1204、1998-01-16〜1999-07-29）の日別ASCII表を読みます。

## 変数

| 入口 | 次元 | 単位 | 内容 |
|---|---|---|---|
| `lp.mag.magnetic_field` | `time, component` | nT | 5秒平均の磁場（SSE）。別名`b` |
| `lp.mag.magnetic_field_sel` | `time, component` | nT | 同じ磁場をSEL座標で |
| `lp.mag.magnetic_field_rms` | `time` | nT | 5秒平均内の磁場のRMS |
| `lp.mag.position` | `time, component` | km | 月中心からの探査機の位置（SSE） |
| `lp.mag.position_sel` | `time, component` | km | 同じ位置をSEL座標で |
| `lp.er.electron_flux` | `time, energy_bin` | 1/(cm^2 s sr eV) | 約80秒（16スピン）の全方向の電子微分数フラックス。15エネルギー |
| `lp.er.electron_flux_3d` | `time, energy_bin, look` | 1/(cm^2 s sr eV) | 3次元電子分布。15エネルギー×88視線方向 |

`lp = spn.lunar_prospector`です。座標系の定義はPDSのラベルに従います。

| 座標系 | 定義 |
|---|---|
| SSE（selenocentric solar ecliptic） | X軸は月から太陽の向き、Z軸は黄道面の北向きの法線に平行 |
| SEL（selenographic） | Z軸は月の自転軸、X軸は経度0度の方向。デカルト座標 |

ERの値は、配布ファイルの列名は`EFLUX`ですが、単位は`CM**-2 * S**-1 * SR**-1 * eV**-1`の微分数フラックスです。
SOPRANは単位のとおり数フラックスとして扱い、名前を`electron_flux`にしています。

```python
lp = spn.lunar_prospector
time = spn.period("1998-02-01T00:00", "1998-02-01T06:00")

spn.stack(
    lp.er.electron_flux.spectrogram(time),
    lp.er.electron_flux_3d.spectrogram(time),     # 視線方向で平均
    lp.mag.magnetic_field.lines(time, components="xyz"),
).plot()
```

## エネルギー表

ERのエネルギーは記録ごとの座標`energy`（`time, energy_bin`、eV）です。
エネルギー表は2種類（16.7 keV〜39 eVと、15.9 keV〜7 eV）あり、1999年3月以降に4回切り替わります。
`E_BINS.TAB`の切り替え時刻から各記録に有効な表を選びます。`E_BINS.TAB`はどのボリュームでも同じ内容で、最初に1回だけ取得します。

## 3次元分布

`electron_flux_3d`の`time`はスペクトルの時刻（16スピン分の1スペクトル）で、配布ファイルの15行（エネルギー）を1スペクトルにまとめます。
各行の値は次の座標として残します。

| 座標 | 次元 | 内容 |
|---|---|---|
| `energy` | `time, energy_bin` | その行のエネルギー（eV） |
| `record_time` | `time, energy_bin` | その行の時刻 |
| `theta` | `look` | 検出器の仰角（度）。`THETA.TAB`の固定値 |
| `phi` | `time, energy_bin, look` | 方位角（度）。配布値のままで、0〜360度に折り返していない（450度などがある） |
| `bx_despun`、`by_despun`、`bz_despun` | `time, energy_bin` | 自転を除いた探査機座標の磁場（nT） |

15行に満たないスペクトルは、足りないエネルギーをNaNで埋めます。
ピッチ角はまだ計算しません。視線方向（`theta`・`phi`）と粒子の進行方向の符号の約束をLPの文献で確認してから加える予定です。

`spectrogram()`は、3次元分布を視線方向で平均してから描きます（`reduction="mean"`が既定）。合計にするときは`reduction="sum"`を渡します。

## 取得と置き場所

元ファイルは`https://pds-ppi.igpp.ucla.edu/volume/<ボリューム>/DATA/<MAG|ER_LO_TS|ER_3DIST>/<YY_MMMON>/`の
`MAyymmdd.TAB`・`ELyymmdd.TAB`・`3Dyymmdd.TAB`です。ボリュームは日付から決まります。
取得したファイルはStoreの`raw/lunar_prospector/pds3/`の下に同じ構成で置き、取得元とチェックサムを記録します。

| データ | 1日の大きさ |
|---|---|
| MAG | 約2.6 MB |
| ER（全方向） | 約0.2 MB |
| ER（3次元） | 約24 MB |

ミッション期間外の日と、配布元にファイルの無い日（404）は欠測として扱います。既定（`missing="empty"`）では空の結果を返し、
`missing="warn"`で警告、`missing="error"`で`DatasetNotFoundError`にします。期間外の日だけを読むときは何も取得しません。

## 解釈上の注意

- 欠損値はラベルの`MISSING_CONSTANT`（磁場`999.999`、位置`999999.99`、フラックス`9.999E-99`など）をNaNに変えます。
  観測されたゼロのフラックスはゼロのまま残します。
- 磁場とERは配布元の較正済みの値です。ERの宇宙機電位の補正やバックグラウンドの除去は行いません。
- 高時間分解能のER（`ER_HI_TS`、約5秒・2エネルギー）と、高次のデータ（LP_2001）はまだ読みません。

出典：[PDS PPI Lunar Prospector MAG/ER Level 1B](https://pds-ppi.igpp.ucla.edu/volume/LP_1201/AAREADME.HTM)
