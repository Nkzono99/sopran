# LRS（プラズマ波動・電波）

LRS（Lunar Radar Sounder）のうち、SOPRANは自然の電波・プラズマ波動を測る2つの受信機の公開スペクトル（CDF）を読みます。

| 入口 | 受信機 | 内容 |
|---|---|---|
| `kg.lrs.npw` | NPW（Natural Plasma Wave） | 受信機1・2のスペクトル |
| `kg.lrs.wfc` | WFC-H（Waveform Capture、高周波側） | 電場スペクトルと、ゲイン・モードなどの付随情報 |

## 変数

| 入口 | 次元 | 単位 | 内容 |
|---|---|---|---|
| `npw.rx1`、`npw.rx2` | `time, frequency` | dB | NPWのスペクトル |
| `npw.mode` | `time` | flag | NPWのモード |
| `wfc.ex_db`、`wfc.ey_db` | `time, frequency` | dB | WFCの生スペクトル |
| `wfc.ex_field`、`wfc.ey_field` | `time, frequency` | dB uV/m | ゲインと帯域を補正した電場強度 |
| `wfc.ex_power_spectral_density`、`wfc.ey_power_spectral_density` | `time, frequency` | (V/m)^2/Hz | 電場のパワースペクトル密度 |
| `wfc.gain` | `time` | dB | Gainフラグから求めたゲイン |
| `wfc.mode`、`wfc.xymode`、`wfc.fband`、`wfc.omode`、`wfc.postgap` | `time` | flag | 生のModeバイトと、そこから取り出した各モード・PostGapフラグ |
| `wfc.pdc_ti`、`wfc.pdc_ti_words` | `time`（`pdc_word`） | count | 探査機の時刻カウンター（UTCではない） |

`kg.lrs.wfc_ey_power_spectral_density`のように、機器直下の名前でも同じエンドポイントに届きます。

```python
kg = spn.kaguya
time = spn.period("2008-04-01T00:00:00", "2008-04-01T02:00:00")

npw = kg.lrs.npw.rx1.load(time, missing="warn")
psd = kg.lrs.wfc.ey_power_spectral_density.load(time)

spn.stack(
    npw.spectrogram(y="frequency", log_color=True),
    psd.spectrogram(y="frequency", log_color=True),
    kg.lrs.wfc.gain.load(time).line(),
).plot()
```

## 元ファイル

NPWは1日1ファイル、WFCは2時間ごとのファイルです。01:00〜01:30のように奇数時から始まる期間でも、
直前の00:00のWFCファイルを読みます。

```text
raw/kaguya/pds3/
  sln-l-lrs-5-npw-spectrum-v1.0/YYYYMMDD/data/LRS_NPW_V010_YYYYMMDD.cdf
  sln-l-lrs-4-wfc-spectrum-v1.0/YYYYMMDD/data/LRS_WFC_V010_YYYYMMDDhhmmss.cdf
```

## キャッシュ

LRSのエンドポイントは`cache="use"`（既定）で、読んだ結果をStoreに保存します。
NPWとWFCの生スペクトルは`normalized`層、ゲイン・電場強度・パワースペクトル密度・モードは`features`層です。
同じ期間を次に読むときはCDFを読み直しません。元ファイルが欠けて`missing="empty"`や`"warn"`で読んだ結果は保存しません。

## 補正と欠測の扱い

- 電場強度とパワースペクトル密度は、SPEDAS（`kgy_lrs_load.pro`）とlunarsatの実装に合わせたdB補正と帯域幅の正規化で求めています。
- CDFの疎な格納で埋められた値（pad）と、観測されたゼロを区別します。WFCの付随変数ではUINT1の`254`、
  PDC-TIでは`[65534, 0, 65534]`を欠測として扱います。CDFの`FILLVAL=0`とは別のものです。
- 時刻はCDFの`Epoch`（UTC）です。`wfc_pdc_ti`は上位・中位・下位の3つの16ビット語からなる48ビットの機上カウンターで、
  変換表なしにUTCへは直しません。生の3語は`wfc_pdc_ti_words`に残します。

## 制約

- 読めるのはWFC-Hのスペクトルです。WFC-Lの波形（10 Hz〜100 kHz）は公開スペクトルとは別の製品で、読み込みに対応していません。
- 実データを使ったSPEDASとの長期の照合テストはまだありません。

波動イベントの候補抽出は[試作API](../../experimental/waves.md)にあります。

## 出典

- Y. Kasahara et al., "Plasma wave observation using waveform capture in the Lunar Radar Sounder on board the SELENE spacecraft,"
  *Earth, Planets and Space* 60, 341–351 (2008). [doi:10.1186/BF03352799](https://doi.org/10.1186/BF03352799)
- [DARTS KAGUYAアーカイブ](https://darts.isas.jaxa.jp/en/missions/kaguya)
