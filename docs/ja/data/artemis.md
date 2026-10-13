# ARTEMIS

ARTEMISは、THEMISの2機（P1 = THEMIS-B、P2 = THEMIS-C）を2011年から月周回軌道で運用しているNASAのミッションです。
SOPRANはNASA SPDF（CDAWeb）のLevel 2の日別CDFを取得し、FGMの磁場と、ESAのエネルギーフラックス・モーメントを読みます。
読み込みには`cdflib`と`xarray`が必要です（`[artemis]`）。

## 変数

| 入口（`p2`も同じ） | 次元 | 単位 | 内容 |
|---|---|---|---|
| `art.p1.fgm.magnetic_field` | `time, component` | nT | スピン周期（約3秒）の磁場ベクトル（FGS、GSE）。別名`b` |
| `art.p1.esa.ion_energy_flux` | `time, energy_bin` | eV/(cm^2 s sr eV) | イオンの微分エネルギーフラックス |
| `art.p1.esa.electron_energy_flux` | `time, energy_bin` | eV/(cm^2 s sr eV) | 電子の微分エネルギーフラックス |
| `art.p1.esa.ion_density` | `time` | cm^-3 | イオン密度（地上処理のモーメント） |
| `art.p1.esa.ion_velocity` | `time, component` | km/s | イオンの速度（GSE） |
| `art.p1.esa.electron_density` | `time` | cm^-3 | 電子密度 |

エネルギーフラックスのエネルギーは、記録ごとの座標`energy`（`time, energy_bin`、eV）です。
L2のエネルギー表は衛星電位の補正などで記録ごとに変わるため、共通の1本の軸にまとめず、元のビンのまま返します。
表に無いビンはエネルギーがNaNになり、作図ではそのビンを描きません。

```python
art = spn.artemis
time = spn.period("2011-07-01T06:00", "2011-07-01T08:00")

art.p1.fgm.magnetic_field.plan(time)          # データセットIDと取得元のディレクトリ
b = art.p1.fgm.magnetic_field.load(time)
flux = art.p1.esa.ion_energy_flux.load(time)
flux.to_xarray().coords["energy"]             # (time, energy_bin) のエネルギー表

spn.stack(
    art.p1.esa.ion_energy_flux.spectrogram(time),       # 縦軸は記録ごとのエネルギー、色・縦軸とも対数
    art.p1.esa.electron_energy_flux.spectrogram(time),
    art.p1.fgm.magnetic_field.lines(time, components="xyz"),
).plot()
```

## ESAのモード

ESAは観測モードごとに別の変数を持ちます。`mode=`で選び、既定は連続して得られる`"reduced"`です。

| `mode` | CDFの変数（P1のイオン） | 時間分解能 | 内容 |
|---|---|---|---|
| `"reduced"`（既定） | `thb_peir_*` | 約3秒 | 角度分解能を落とした連続データ |
| `"full"` | `thb_peif_*` | 約2分（2011-07-01のP1） | 角度分解能の高いデータ |
| `"burst"` | `thb_peib_*` | 不定期 | 短時間の高分解能データ |

```python
art.p1.esa.ion_energy_flux.load(time, mode="full")
art.p1.esa.ion_energy_flux.spectrogram(time, mode="full")
```

## 取得と置き場所

元ファイルは`https://spdf.gsfc.nasa.gov/pub/data/themis/<thb|thc>/l2/<fgm|esa>/YYYY/`にある
`thb_l2_fgm_YYYYMMDD_vNN.cdf`の形の日別ファイルです。版番号`vNN`は再処理で上がることがあるため、年ごとのディレクトリの一覧から
その日の最新版を選びます。取得したファイルはStoreの`raw/artemis/themis/<thb|thc>/l2/<fgm|esa>/YYYY/`に置き、
取得元とチェックサムを記録します。Storeに同じ日のファイルがあれば、`download="always"`のとき以外は通信しません。

| `download` | 動作 |
|---|---|
| `missing`（既定） | 無い日のファイルを取得する |
| `never` | 通信しない。無い日は欠測として扱う |
| `always` | 一覧を見直し、最新版を取得し直す |

FGMの1日分は約37 MB、ESAは約12 MBです。配布元にその日のファイルが無い場合や`download="never"`で手元に無い場合は、
既定（`missing="empty"`）では空の結果を返します。`missing="warn"`で警告、`missing="error"`で`DatasetNotFoundError`にします。

## 解釈上の注意

- 磁場はスピン周期の値（FGS）だけを読みます。高時間分解能の`fgl`・`fgh`は読みません。座標系はGSEで、
  `View`の`frame`を指定しても回転しません。
- ESAのモーメントは配布元の地上処理の値で、衛星電位の補正や品質フラグ（`*_data_quality`）の適用は配布元の処理のままです。
  品質フラグ自体はまだ読みません。
- イオンの速度は期間によってNaNになっています（例：2011-07-01のP1では09:24〜21:23 UTCのみ値がある）。
  密度など他の量が有効でも、配布ファイルの速度はNaNのことがあります。
- 月中心の位置や、月のウェイク・磁気圏に対する位置関係はまだ付けていません。

出典：[NASA SPDF THEMIS](https://spdf.gsfc.nasa.gov/pub/data/themis/)
